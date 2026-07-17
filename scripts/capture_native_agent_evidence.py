#!/usr/bin/env python3
"""Capture real native n8n AI Agent tool telemetry for the dogfood corpus.

This internal harness creates three short-lived workflows in a disposable n8n lane:
one successful native tool call, one tool error followed by a native model recovery,
and one tool error with no later model recovery. It uses n8n's native AI Agent,
Anthropic Chat Model, and Code Tool nodes, then polls the configured Pisama server.

No model response, tool input, credential, or raw execution is printed. Workflows and
the temporary Anthropic credential are deleted after collection; n8n execution records
and the Pisama corpus remain as the real regression evidence.

Required environment variables: ANTHROPIC_API_KEY, PISAMA_N8N_API_KEY,
PISAMA_API_KEY. Optional: PISAMA_N8N_URL (default localhost:5681),
PISAMA_SERVER_URL (default localhost:8411).
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterable, List

from capture_claude_agent_evidence import (
    SERVER_URL,
    _n8n,
    _request,
    _required,
    _run_workflow,
    _server_sync,
)


MODEL = "claude-haiku-4-5-20251001"
_NATIVE_AGENT = "@n8n/n8n-nodes-langchain.agent"
_NATIVE_MODEL = "@n8n/n8n-nodes-langchain.lmChatAnthropic"
_NATIVE_TOOL = "@n8n/n8n-nodes-langchain.toolCode"


def _anthropic_credential() -> Dict[str, str]:
    """Create an ephemeral native Anthropic credential without serializing its key."""
    created = _n8n(
        "POST",
        "/api/v1/credentials",
        {
            "name": f"Pisama native Anthropic {int(time.time() * 1000)}",
            "type": "anthropicApi",
            "data": {"apiKey": _required("ANTHROPIC_API_KEY")},
        },
    )
    return {"id": str(created["id"]), "name": str(created["name"])}


def _webhook(path: str) -> Dict[str, Any]:
    return {
        "parameters": {
            "path": path,
            "httpMethod": "POST",
            "responseMode": "onReceived",
        },
        "id": "webhook",
        "name": "Native agent webhook",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [0, 0],
        "webhookId": path,
    }


def _agent(query: str, max_iterations: int) -> Dict[str, Any]:
    return {
        "parameters": {
            "agent": "toolsAgent",
            "promptType": "define",
            "text": (
                "Use the status_lookup tool exactly once with query "
                f"{query}. Do not answer before using it."
            ),
            "hasOutputParser": False,
            "options": {
                "maxIterations": max_iterations,
                "returnIntermediateSteps": True,
                "systemMessage": (
                    "You are a deterministic native n8n dogfood agent. "
                    "If a tool reports an error, do not call another tool. "
                    "Give one short fallback response."
                ),
            },
        },
        "id": "agent",
        "name": "Native AI Agent",
        "type": _NATIVE_AGENT,
        "typeVersion": 1.9,
        "position": [240, 0],
    }


def _model(credential: Dict[str, str]) -> Dict[str, Any]:
    return {
        "parameters": {
            "model": {"__rl": True, "mode": "id", "value": MODEL},
            # n8n 1.91's bundled Anthropic client forwards incompatible default
            # top_p/top_k values unless thinking mode supplies these invocation
            # options. This exact working configuration was captured in the live lane.
            "options": {
                "thinking": True,
                "thinkingBudget": 1024,
                "maxTokensToSample": 1536,
            },
        },
        "id": "model",
        "name": "Native Anthropic Chat Model",
        "credentials": {"anthropicApi": credential},
        "type": _NATIVE_MODEL,
        "typeVersion": 1.3,
        "position": [240, 180],
    }


def _tool(query: str, fails: bool) -> Dict[str, Any]:
    code = (
        "throw new Error(`Pisama native controlled tool failure for ${query}`);"
        if fails
        else "return `native status for ${query}`;"
    )
    return {
        "parameters": {
            "name": "status_lookup",
            "description": (
                "Returns the native dogfood status for the supplied query. "
                "Use it when asked for native status."
            ),
            "jsCode": code,
            "language": "javaScript",
            "specifyInputSchema": False,
        },
        "id": "tool",
        "name": "status_lookup",
        "type": _NATIVE_TOOL,
        "typeVersion": 1.2,
        "position": [240, 360],
    }


def _connections() -> Dict[str, Any]:
    return {
        "Native agent webhook": {
            "main": [[{"node": "Native AI Agent", "type": "main", "index": 0}]]
        },
        "Native Anthropic Chat Model": {
            "ai_languageModel": [
                [
                    {
                        "node": "Native AI Agent",
                        "type": "ai_languageModel",
                        "index": 0,
                    }
                ]
            ]
        },
        "status_lookup": {
            "ai_tool": [[{"node": "Native AI Agent", "type": "ai_tool", "index": 0}]]
        },
    }


def _workflow(
    name: str,
    query: str,
    credential: Dict[str, str],
    *,
    fails: bool,
    max_iterations: int,
) -> Dict[str, Any]:
    path = f"pisama-native-agent-{name}-{int(time.time() * 1000)}"
    return {
        "name": f"Pisama temporary native agent {name}",
        "nodes": [
            _webhook(path),
            _agent(query, max_iterations),
            _model(credential),
            _tool(query, fails),
        ],
        "connections": _connections(),
        "settings": {},
        "_path": path,
    }


def _runs(capture: Dict[str, Any], node_name: str) -> List[Dict[str, Any]]:
    runs = capture["run_data"].get(node_name, [])
    return [run for run in runs if isinstance(run, dict)]


def _index(run: Dict[str, Any]) -> int:
    value = run.get("executionIndex")
    if not isinstance(value, int):
        raise RuntimeError("native capture omitted n8n executionIndex")
    return value


def _assert_finished_capture(capture: Dict[str, Any]) -> None:
    if capture.get("status") != "success" or capture.get("finished") is not True:
        raise RuntimeError("native agent execution did not finish successfully")


def _capture_runs(
    capture: Dict[str, Any],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    agent_runs = _runs(capture, "Native AI Agent")
    model_runs = _runs(capture, "Native Anthropic Chat Model")
    tool_runs = _runs(capture, "status_lookup")
    return agent_runs, model_runs, tool_runs


def _assert_expected_run_shape(
    agent_runs: List[Dict[str, Any]],
    model_runs: List[Dict[str, Any]],
    tool_runs: List[Dict[str, Any]],
) -> None:
    if len(agent_runs) != 1 or len(tool_runs) != 1 or not model_runs:
        raise RuntimeError(
            "native agent capture did not retain the expected one-agent shape"
        )


def _assert_tool_outcome(tool: Dict[str, Any], *, fails: bool) -> None:
    if (tool.get("executionStatus") == "error") != fails:
        raise RuntimeError("native Code Tool did not retain the requested outcome")


def _assert_model_recovery_shape(
    tool: Dict[str, Any],
    model_runs: List[Dict[str, Any]],
    *,
    recovers: bool,
) -> None:
    tool_index = _index(tool)
    model_indexes = [_index(run) for run in model_runs]
    before_tool = [index for index in model_indexes if index < tool_index]
    if len(before_tool) != 1:
        raise RuntimeError("native capture lacks one model turn before the tool call")
    after_tool = [index for index in model_indexes if index > tool_index]
    if bool(after_tool) != recovers:
        raise RuntimeError("native capture did not retain the requested recovery shape")


def _agent_intermediate_steps(agent_run: Dict[str, Any]) -> List[Dict[str, Any]]:
    output = ((agent_run.get("data") or {}).get("main") or [[]])[0]
    steps: List[Dict[str, Any]] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        result = item.get("json")
        if not isinstance(result, dict):
            continue
        for step in result.get("intermediateSteps") or []:
            if isinstance(step, dict):
                steps.append(step)
    return steps


def _assert_agent_tool_step(agent_run: Dict[str, Any]) -> None:
    steps = _agent_intermediate_steps(agent_run)
    tool_name = (steps[0].get("action") or {}).get("tool") if len(steps) == 1 else None
    if len(steps) != 1 or tool_name != "status_lookup":
        raise RuntimeError(
            "native Agent did not retain one status_lookup intermediate step"
        )


def _assert_capture(capture: Dict[str, Any], *, fails: bool, recovers: bool) -> None:
    """Validate only the observed n8n native telemetry shape, never model content."""
    _assert_finished_capture(capture)
    agent_runs, model_runs, tool_runs = _capture_runs(capture)
    _assert_expected_run_shape(agent_runs, model_runs, tool_runs)
    tool = tool_runs[0]
    _assert_tool_outcome(tool, fails=fails)
    _assert_model_recovery_shape(tool, model_runs, recovers=recovers)
    _assert_agent_tool_step(agent_runs[0])


def _summary(captures: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summaries = []
    for capture in captures:
        tool = _runs(capture, "status_lookup")[0]
        summaries.append(
            {
                "execution_id": capture["execution_id"],
                "status": capture["status"],
                "finished": capture["finished"],
                "agent_run_count": len(_runs(capture, "Native AI Agent")),
                "model_execution_indexes": [
                    _index(run) for run in _runs(capture, "Native Anthropic Chat Model")
                ],
                "tool_execution_index": _index(tool),
                "tool_execution_status": tool.get("executionStatus"),
            }
        )
    return summaries


def _detection_rows() -> List[Any]:
    rows = _request(
        "GET",
        f"{SERVER_URL}/api/v1/detections",
        {"Authorization": f"Bearer {_required('PISAMA_API_KEY')}"},
    )
    if not isinstance(rows, list):
        raise RuntimeError("Pisama detections endpoint did not return a list")
    return rows


def _empty_findings(captures: Iterable[Dict[str, Any]]) -> Dict[str, List[str]]:
    execution_ids = {str(capture["execution_id"]) for capture in captures}
    return {execution_id: [] for execution_id in execution_ids}


def _record_finding(row: Any, findings: Dict[str, List[str]]) -> None:
    if not isinstance(row, dict) or not row.get("detected"):
        return
    execution_id = str(row.get("n8n_execution_id") or "")
    if execution_id not in findings:
        return
    detector = row.get("detector")
    failure_mode = row.get("failure_mode")
    if isinstance(detector, str) and isinstance(failure_mode, str):
        findings[execution_id].append(f"{detector}:{failure_mode}")


def _sorted_findings(findings: Dict[str, List[str]]) -> Dict[str, List[str]]:
    return {key: sorted(value) for key, value in findings.items()}


def _fired_by_execution(captures: Iterable[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Return only fired detector fingerprints for the new execution IDs."""
    rows = _detection_rows()
    findings = _empty_findings(captures)
    for row in rows:
        _record_finding(row, findings)
    return _sorted_findings(findings)


def _assert_detections(captures: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    findings = _fired_by_execution(captures)
    healthy, recovered, unhandled = captures
    native = "agent_diagnostics:n8n_native_agent_tool_recovery"
    if (
        native in findings[str(healthy["execution_id"])]
        or native in findings[str(recovered["execution_id"])]
    ):
        raise RuntimeError("native detector fired for a healthy or recovered control")
    if native not in findings[str(unhandled["execution_id"])]:
        raise RuntimeError("Pisama did not retain the unhandled native Agent finding")
    return findings


def main() -> None:
    captures: List[Dict[str, Any]] = []
    credential = _anthropic_credential()
    try:
        captures = [
            _run_workflow(
                _workflow(
                    "tool-success",
                    "native-tool-success",
                    credential,
                    fails=False,
                    max_iterations=3,
                )
            ),
            _run_workflow(
                _workflow(
                    "tool-recovery",
                    "native-tool-recovery",
                    credential,
                    fails=True,
                    max_iterations=3,
                )
            ),
            _run_workflow(
                _workflow(
                    "tool-unhandled",
                    "native-tool-unhandled",
                    credential,
                    fails=True,
                    max_iterations=1,
                )
            ),
        ]
        _assert_capture(captures[0], fails=False, recovers=True)
        _assert_capture(captures[1], fails=True, recovers=True)
        _assert_capture(captures[2], fails=True, recovers=False)
        sync = _server_sync()
        findings = _assert_detections(captures)
        print(
            json.dumps(
                {
                    "healthy_tool": _summary(captures[:1]),
                    "recovered_tool_failure": _summary(captures[1:2]),
                    "unhandled_tool_failure": _summary(captures[2:]),
                    "sync": sync,
                    "fired_fingerprints": findings,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        for capture in captures:
            _n8n("DELETE", f"/api/v1/workflows/{capture['workflow_id']}")
        _n8n("DELETE", f"/api/v1/credentials/{credential['id']}")


if __name__ == "__main__":
    main()
