"""Capture real Claude agent-recovery and output-validation evidence through n8n.

This is an internal dogfood harness. It creates short-lived workflows in the configured
local n8n instance, invokes Claude through genuine n8n HTTP Request nodes, syncs the
result into Pisama, and retires the workflow inactive afterwards so n8n retains the
actual execution as regression evidence. It prints only a redacted summary; API keys
and full model content never leave the process.

Required environment variables: ANTHROPIC_API_KEY, PISAMA_N8N_API_KEY,
PISAMA_API_KEY. Optional: PISAMA_N8N_URL (default localhost:5681),
PISAMA_SERVER_URL (default localhost:8411).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any, Dict, Iterable, Optional, Sequence
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pisama_n8n_engine.detect.truncation import extract_stop_reason


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


def _truncation_workflow(credential: Dict[str, str]) -> Dict[str, Any]:
    """Create one real Anthropic call forced to end at its output token budget."""
    path = f"pisama-claude-truncation-{int(time.time() * 1000)}"
    request_body = "=" + json.dumps(
        {
            "model": MODEL,
            # Anthropic records stop_reason=max_tokens when this deliberately
            # undersized budget interrupts the requested long response.
            "max_tokens": 8,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Write a detailed 250-word explanation of why bounded "
                        "tool retries matter in production automation."
                    ),
                }
            ],
        },
        separators=(",", ":"),
    )
    return {
        "name": "Pisama temporary Claude truncation capture",
        "nodes": [
            _webhook("Truncation webhook", path),
            _http_node(
                "agent",
                "Claude constrained output",
                request_body,
                [220, 0],
                credential,
            ),
        ],
        "connections": _link("Truncation webhook", "Claude constrained output"),
        "settings": {},
        "_path": path,
    }


def _http_failure_workflow(
    label: str, node_name: str, url: str, options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Create one direct, real HTTP failure without an agent recovery wrapper."""
    path = f"pisama-{label}-{int(time.time() * 1000)}"
    return {
        "name": f"Pisama temporary {label} capture",
        "nodes": [
            _webhook(f"{label} webhook", path),
            {
                "parameters": {
                    "method": "GET",
                    "url": url,
                    "options": options or {},
                },
                "id": f"{label}-request",
                "name": node_name,
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.2,
                "position": [220, 0],
            },
        ],
        "connections": _link(f"{label} webhook", node_name),
        "settings": {},
        "_path": path,
    }


def _credential_workflow() -> Dict[str, Any]:
    """Create one real 401 without storing a credential or credential value."""
    # httpbin validates these fixed, public test credentials. Sending no Authorization
    # header makes this an actual HTTP 401, rather than a fabricated node error.
    return _http_failure_workflow(
        "credential-failure",
        "Observed credential rejection",
        "https://httpbin.org/basic-auth/pisama/dogfood",
    )


def _data_contract_workflow() -> Dict[str, Any]:
    """Create a real n8n Code-node missing-field failure from webhook data."""
    path = f"pisama-data-contract-{int(time.time() * 1000)}"
    return {
        "name": "Pisama temporary data contract capture",
        "nodes": [
            _webhook("Data contract webhook", path),
            {
                "parameters": {
                    "jsCode": "return [{ json: { value: $json.required.value } }];"
                },
                "id": "missing-field",
                "name": "Observed missing field",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [220, 0],
            },
        ],
        "connections": _link("Data contract webhook", "Observed missing field"),
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
        terminal_rows = []
        for _ in range(30):
            time.sleep(1)
            executions = _n8n("GET", "/api/v1/executions?limit=100")
            matching = [
                row
                for row in executions.get("data", [])
                if str(row.get("workflowId")) == workflow_id
            ]
            # n8n records failed executions with ``finished: false`` even after they
            # stop. ``stoppedAt`` is the terminal marker that covers both successful
            # and errored real workflows.
            terminal_rows = [row for row in matching if row.get("stoppedAt")]
            if terminal_rows:
                break
        if not matching:
            raise RuntimeError(
                "n8n did not retain an execution for the temporary workflow"
            )
        if not terminal_rows:
            raise RuntimeError("n8n did not stop the temporary workflow execution")
        execution_id = str(terminal_rows[0]["id"])
        execution = _n8n("GET", f"/api/v1/executions/{execution_id}?includeData=true")
        run_data = execution.get("data", {}).get("resultData", {}).get("runData", {})
        return {
            "workflow_id": workflow_id,
            "execution_id": execution_id,
            "status": execution.get("status"),
            "finished": execution.get("finished"),
            "stopped_at": execution.get("stoppedAt"),
            "nodes": list(run_data),
            "run_data": run_data,
        }
    except Exception:
        # n8n deletes execution history with a workflow. Keep incomplete real evidence
        # inactive rather than making a claim from a trace that cannot be inspected.
        try:
            _n8n("POST", f"/api/v1/workflows/{workflow_id}/deactivate")
        except RuntimeError:
            pass
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


def _truncation_reason(capture: Dict[str, Any]) -> Optional[str]:
    """Read only the provider's stop marker, never the model response text."""
    runs = capture["run_data"].get("Claude constrained output", [])
    if len(runs) != 1 or not isinstance(runs[0], dict):
        return None
    output = (runs[0].get("data") or {}).get("main")
    return extract_stop_reason(output)


def _has_truncation_finding(execution_id: str) -> bool:
    """Require the persisted finding associated with this real execution only."""
    rows = _request(
        "GET",
        f"{SERVER_URL}/api/v1/detections",
        {"Authorization": f"Bearer {_required('PISAMA_API_KEY')}"},
    )
    return any(
        isinstance(row, dict)
        and str(row.get("n8n_execution_id")) == execution_id
        and row.get("detected") is True
        and row.get("detector") == "truncation"
        and row.get("failure_mode") == "n8n_truncation"
        for row in rows
        if isinstance(rows, list)
    )


def _fired_fingerprints(
    captures: Dict[str, Dict[str, Any]],
) -> Dict[str, set[str]]:
    """Return detected fingerprints for these executions without exposing outputs."""
    rows = _request(
        "GET",
        f"{SERVER_URL}/api/v1/detections",
        {"Authorization": f"Bearer {_required('PISAMA_API_KEY')}"},
    )
    if not isinstance(rows, list):
        raise RuntimeError("Pisama detections endpoint did not return a list")
    labels = {
        str(capture["execution_id"]): label for label, capture in captures.items()
    }
    findings = {label: set() for label in captures}
    for row in rows:
        if not isinstance(row, dict) or row.get("detected") is not True:
            continue
        label = labels.get(str(row.get("n8n_execution_id")))
        detector = row.get("detector")
        failure_mode = row.get("failure_mode")
        if label and isinstance(detector, str) and isinstance(failure_mode, str):
            findings[label].add(f"{detector}:{failure_mode}")
    return findings


def _assert_core_findings(findings: Dict[str, set[str]]) -> None:
    """Require exact evidence-backed P0/P1 classes for each controlled run."""
    expected = {
        "provider": {"error:n8n_provider"},
        "rate_limit": {"error:n8n_rate_limit"},
        "timeout": {"error:n8n_timeout", "timeout:F13"},
        "data_contract": {"error:n8n_expression", "schema:n8n_data_contract"},
        "credential": {"error:n8n_credential"},
        "truncation": {"truncation:n8n_truncation"},
    }
    missing = {
        label: sorted(required - findings.get(label, set()))
        for label, required in expected.items()
        if required - findings.get(label, set())
    }
    if missing:
        raise RuntimeError(f"Pisama missed required core findings: {missing}")


def _capture_core_workflows(credential: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    """Run the smallest real workflow set that covers every released P0/P1 mode."""
    workflow_builders = {
        "provider": lambda: _http_failure_workflow(
            "provider-failure",
            "Observed provider failure",
            "https://httpbin.org/status/502",
        ),
        "rate_limit": lambda: _http_failure_workflow(
            "rate-limit", "Observed rate limit", "https://httpbin.org/status/429"
        ),
        "timeout": lambda: _http_failure_workflow(
            "timeout",
            "Observed timeout",
            "https://httpbin.org/delay/5",
            {"timeout": 500},
        ),
        "data_contract": _data_contract_workflow,
        "credential": _credential_workflow,
        "truncation": lambda: _truncation_workflow(credential),
    }
    captures: Dict[str, Dict[str, Any]] = {}
    try:
        for label, build_workflow in workflow_builders.items():
            captures[label] = _run_workflow(build_workflow())
        return captures
    except Exception:
        _retire_captures(captures.values())
        raise


def _retire_captures(captures: Iterable[Dict[str, Any]]) -> None:
    """Deactivate and verify real evidence workflows without deleting executions."""
    for capture in captures:
        _n8n("POST", f"/api/v1/workflows/{capture['workflow_id']}/deactivate")
        retained = _n8n("GET", f"/api/v1/executions/{capture['execution_id']}")
        if str(retained.get("id")) != str(capture["execution_id"]):
            raise RuntimeError("n8n did not retain the retired evidence execution")


def capture_truncation_evidence() -> None:
    """Capture, ingest, and verify one real P0 truncation execution."""
    capture: Optional[Dict[str, Any]] = None
    credential = _anthropic_credential()
    try:
        capture = _run_workflow(_truncation_workflow(credential))
        if capture.get("status") != "success" or capture.get("finished") is not True:
            raise RuntimeError(
                "constrained Claude execution did not finish successfully"
            )
        reason = _truncation_reason(capture)
        if reason != "max_tokens":
            raise RuntimeError(
                "Anthropic did not retain the expected max_tokens stop reason"
            )
        sync = _server_sync()
        execution_id = str(capture["execution_id"])
        if not _has_truncation_finding(execution_id):
            raise RuntimeError("Pisama did not retain the real truncation finding")
        print(
            json.dumps(
                {
                    "execution_id": execution_id,
                    "status": capture["status"],
                    "stop_reason": reason,
                    "sync": sync,
                    "fingerprint": "truncation:n8n_truncation",
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        if capture is not None:
            _retire_captures([capture])
        _n8n("DELETE", f"/api/v1/credentials/{credential['id']}")


def capture_core_evidence() -> None:
    """Capture, ingest, and verify the released P0/P1 corpus from real n8n runs."""
    captures: Dict[str, Dict[str, Any]] = {}
    credential = _anthropic_credential()
    try:
        captures = _capture_core_workflows(credential)
        if _truncation_reason(captures["truncation"]) != "max_tokens":
            raise RuntimeError(
                "Anthropic did not retain the expected max_tokens stop reason"
            )
        first_sync = _server_sync()
        findings = _fired_fingerprints(captures)
        _assert_core_findings(findings)
        second_sync = _server_sync()
        if second_sync.get("new") != 0:
            raise RuntimeError("Pisama did not deduplicate the second core sync")
        print(
            json.dumps(
                {
                    "executions": {
                        label: str(capture["execution_id"])
                        for label, capture in captures.items()
                    },
                    "findings": {
                        label: sorted(fingerprints)
                        for label, fingerprints in findings.items()
                    },
                    "first_sync": first_sync,
                    "second_sync": second_sync,
                    "truncation_stop_reason": _truncation_reason(
                        captures["truncation"]
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        _retire_captures(captures.values())
        _n8n("DELETE", f"/api/v1/credentials/{credential['id']}")


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
        _retire_captures(captures)
        _n8n("DELETE", f"/api/v1/credentials/{credential['id']}")


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--truncation-only",
        action="store_true",
        help="Capture and verify one real P0 token-limit execution only.",
    )
    mode.add_argument(
        "--core",
        action="store_true",
        help="Capture and verify all released P0/P1 modes with real n8n executions.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    if args.truncation_only:
        capture_truncation_evidence()
    elif args.core:
        capture_core_evidence()
    else:
        main()
