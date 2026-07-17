"""Capture real Claude agent-recovery and output-validation evidence through n8n.

This is an internal dogfood harness. It creates short-lived workflows in the configured
local n8n instance, invokes Claude through genuine n8n HTTP Request nodes, syncs the
result into Pisama, and deletes the workflow afterwards. It prints only a redacted
summary; API keys and full model content never leave the process.

Required environment variables: ANTHROPIC_API_KEY, PISAMA_N8N_API_KEY,
PISAMA_API_KEY. Optional: PISAMA_N8N_URL (default localhost:5681),
PISAMA_SERVER_URL (default localhost:8411).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Iterable
from urllib.error import HTTPError
from urllib.request import Request, urlopen


N8N_URL = os.getenv("PISAMA_N8N_URL", "http://127.0.0.1:5681").rstrip("/")
SERVER_URL = os.getenv("PISAMA_SERVER_URL", "http://127.0.0.1:8411").rstrip("/")
MODEL = "claude-haiku-4-5-20251001"


def _required(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _request(method: str, url: str, headers: Dict[str, str], body: Any = None) -> Any:
    encoded = None if body is None else json.dumps(body).encode()
    request = Request(url, data=encoded, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise RuntimeError(f"{method} {url} failed: {exc.code} {detail}") from exc


def _n8n(method: str, path: str, body: Any = None) -> Any:
    return _request(
        method,
        f"{N8N_URL}{path}",
        {
            "X-N8N-API-KEY": _required("PISAMA_N8N_API_KEY"),
            "Content-Type": "application/json",
        },
        body,
    )


def _server_sync() -> Dict[str, Any]:
    result = _request(
        "POST",
        f"{SERVER_URL}/api/v1/n8n/sync",
        {"Authorization": f"Bearer {_required('PISAMA_API_KEY')}"},
    )
    return result if isinstance(result, dict) else {}


def _headers() -> list[Dict[str, str]]:
    return [
        {"name": "anthropic-version", "value": "2023-06-01"},
        {"name": "content-type", "value": "application/json"},
    ]


def _anthropic_credential() -> Dict[str, str]:
    """Create an ephemeral n8n credential so workflow JSON never holds the key."""
    created = _n8n(
        "POST",
        "/api/v1/credentials",
        {
            "name": f"Pisama ephemeral Anthropic {int(time.time() * 1000)}",
            "type": "httpHeaderAuth",
            "data": {"name": "x-api-key", "value": _required("ANTHROPIC_API_KEY")},
        },
    )
    return {"id": str(created["id"]), "name": str(created["name"])}


def _http_node(
    node_id: str,
    name: str,
    body: str,
    position: list[int],
    credential: Dict[str, str],
) -> Dict[str, Any]:
    return {
        "parameters": {
            "method": "POST",
            "url": "https://api.anthropic.com/v1/messages",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth",
            "sendHeaders": True,
            "headerParameters": {"parameters": _headers()},
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": body,
        },
        "id": node_id,
        "name": name,
        "credentials": {"httpHeaderAuth": credential},
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": position,
    }


def _webhook(name: str, path: str) -> Dict[str, Any]:
    return {
        "parameters": {
            "path": path,
            "httpMethod": "POST",
            "responseMode": "onReceived",
        },
        "id": "webhook",
        "name": name,
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [0, 0],
        "webhookId": path,
    }


def _link(source: str, target: str) -> Dict[str, Any]:
    return {source: {"main": [[{"node": target, "type": "main", "index": 0}]]}}


def _merge_connections(*links: Dict[str, Any]) -> Dict[str, Any]:
    return {source: edge for link in links for source, edge in link.items()}


def _tool_request_body(tool_name: str, order_id: str) -> str:
    return "=" + json.dumps(
        {
            "model": MODEL,
            "max_tokens": 128,
            "tools": [
                {
                    "name": tool_name,
                    "description": "Look up an order by ID.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"order_id": {"type": "string"}},
                        "required": ["order_id"],
                    },
                }
            ],
            "tool_choice": {"type": "tool", "name": tool_name},
            "messages": [{"role": "user", "content": f"Look up order {order_id}."}],
        },
        separators=(",", ":"),
    )


def _error_link(source: str, target: str) -> Dict[str, Any]:
    return {source: {"main": [[], [{"node": target, "type": "main", "index": 0}]]}}


def _recovery_workflow(
    index: int, credential: Dict[str, str], recover: bool = True
) -> Dict[str, Any]:
    tool_name, order_id, tool_url, timeout = (
        ("lookup_order", "A-101", "https://httpbin.org/status/502", None),
        ("get_inventory", "A-102", "https://httpbin.org/status/429", None),
        ("fetch_customer", "A-103", "https://httpbin.org/delay/5", 500),
    )[index]
    path = f"pisama-claude-tool-recovery-{index}-{int(time.time() * 1000)}"
    build_result = (
        "const initial = $('Claude tool request').first().json;"
        "const call = initial.content?.find(block => block.type === 'tool_use');"
        "const failure = $json.error;"
        "if (!call?.id || !failure) throw new Error('Expected recorded n8n tool error');"
        "const message = failure.message || failure.description || JSON.stringify(failure);"
        "const tool_result = {type:'tool_result',tool_use_id:call.id,content:message,is_error:true};"
        "return [{json:{tool_result,recovery_request:{model:'claude-haiku-4-5-20251001',max_tokens:128,tools:"
        "[{name:'"
        + tool_name
        + "',description:'Controlled reliability tool',input_schema:{type:'object',properties:{order_id:{type:'string'}},required:['order_id']}}],"
        "messages:[{role:'user',content:'Use the tool for this reliability test.'},{role:'assistant',content:initial.content},{role:'user',content:[tool_result]}]}}}];"
    )
    nodes = [
        _webhook("Tool recovery webhook", path),
        _http_node(
            "agent",
            "Claude tool request",
            _tool_request_body(tool_name, order_id),
            [220, 0],
            credential,
        ),
        {
            "parameters": {
                "url": tool_url,
                "options": {"timeout": timeout} if timeout else {},
            },
            "id": "tool",
            "name": "Real tool HTTP failure",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [440, 0],
            "onError": "continueErrorOutput",
        },
        {
            "parameters": {"jsCode": build_result},
            "id": "failed-result",
            "name": "Recorded failed tool result",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [660, 0],
        },
        *(
            [
                _http_node(
                    "recovery",
                    "Claude recovery response",
                    "={{$json.recovery_request}}",
                    [880, 0],
                    credential,
                )
            ]
            if recover
            else []
        ),
    ]
    return {
        "name": f"Pisama temporary Claude tool {'recovery' if recover else 'unhandled failure'} {index + 1}",
        "nodes": nodes,
        "connections": _merge_connections(
            _link("Tool recovery webhook", "Claude tool request"),
            _link("Claude tool request", "Real tool HTTP failure"),
            _error_link("Real tool HTTP failure", "Recorded failed tool result"),
            *(
                [_link("Recorded failed tool result", "Claude recovery response")]
                if recover
                else []
            ),
        ),
        "settings": {},
        "_path": path,
    }


def _malformed_workflow(credential: Dict[str, str]) -> Dict[str, Any]:
    path = f"pisama-claude-malformed-output-{int(time.time() * 1000)}"
    prompt = (
        "Reply with exactly this plain sentence and no JSON: the order cannot be found"
    )
    request_body = "=" + json.dumps(
        {
            "model": MODEL,
            "max_tokens": 64,
            "messages": [{"role": "user", "content": prompt}],
        },
        separators=(",", ":"),
    )
    nodes = [
        _webhook("Malformed output webhook", path),
        _http_node("agent", "Claude prose output", request_body, [220, 0], credential),
        {
            "parameters": {
                "jsCode": "return [{json: JSON.parse($json.content[0].text)}];"
            },
            "id": "validate",
            "name": "Validate Claude JSON",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [440, 0],
        },
    ]
    return {
        "name": "Pisama temporary Claude malformed output capture",
        "nodes": nodes,
        "connections": _merge_connections(
            _link("Malformed output webhook", "Claude prose output"),
            _link("Claude prose output", "Validate Claude JSON"),
        ),
        "settings": {},
        "_path": path,
    }


def _run_workflow(workflow: Dict[str, Any]) -> Dict[str, Any]:
    path = workflow.pop("_path")
    created = _n8n("POST", "/api/v1/workflows", workflow)
    workflow_id = str(created["id"])
    try:
        _n8n("POST", f"/api/v1/workflows/{workflow_id}/activate")
        _request(
            "POST",
            f"{N8N_URL}/webhook/{path}",
            {"Content-Type": "application/json"},
            {},
        )
        matching = []
        for _ in range(20):
            time.sleep(1)
            executions = _n8n("GET", "/api/v1/executions?limit=100")
            matching = [
                row
                for row in executions.get("data", [])
                if str(row.get("workflowId")) == workflow_id
            ]
            if matching:
                break
        if not matching:
            raise RuntimeError(
                "n8n did not retain an execution for the temporary workflow"
            )
        execution_id = str(matching[0]["id"])
        execution = _n8n("GET", f"/api/v1/executions/{execution_id}?includeData=true")
        run_data = execution.get("data", {}).get("resultData", {}).get("runData", {})
        return {
            "workflow_id": workflow_id,
            "execution_id": execution_id,
            "status": execution.get("status"),
            "finished": execution.get("finished"),
            "nodes": list(run_data),
            "run_data": run_data,
        }
    except Exception:
        _n8n("DELETE", f"/api/v1/workflows/{workflow_id}")
        raise


def _summary(captures: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    return [
        {
            "execution_id": capture["execution_id"],
            "status": capture["status"],
            "nodes": capture["nodes"],
        }
        for capture in captures
    ]


def main() -> None:
    captures: list[Dict[str, Any]] = []
    credential = _anthropic_credential()
    try:
        captures = [
            _run_workflow(_recovery_workflow(index, credential)) for index in range(3)
        ]
        captures.append(_run_workflow(_malformed_workflow(credential)))
        captures.append(_run_workflow(_recovery_workflow(0, credential, recover=False)))
        sync = _server_sync()
        print(
            json.dumps(
                {
                    "recoveries": _summary(captures[:3]),
                    "malformed": _summary(captures[3:4]),
                    "unhandled_tool_failure": _summary(captures[4:]),
                    "sync": sync,
                },
                indent=2,
            )
        )
    finally:
        for capture in captures:
            _n8n("DELETE", f"/api/v1/workflows/{capture['workflow_id']}")
        _n8n("DELETE", f"/api/v1/credentials/{credential['id']}")


if __name__ == "__main__":
    main()
