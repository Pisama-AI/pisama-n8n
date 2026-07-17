#!/usr/bin/env python3
"""Capture real native n8n AI Agent tool telemetry for the dogfood corpus.

This internal harness creates three short-lived workflows in a disposable n8n lane:
one successful native tool call, one tool error followed by a native model recovery,
and one tool error with no later model recovery. It uses n8n's native AI Agent,
Anthropic Chat Model, and Code Tool nodes, then polls the configured Pisama server.

No model response, tool input, credential, or raw execution is printed. Workflows are
retired inactive and the temporary Anthropic credential is deleted after collection, so
n8n execution records and the Pisama corpus remain as the real regression evidence.

Required environment variables: PISAMA_N8N_API_KEY, PISAMA_API_KEY, and either
ANTHROPIC_API_KEY or a reusable PISAMA_NATIVE_ANTHROPIC_CREDENTIAL_ID. The reusable
credential must be an n8n Anthropic credential; its optional display name is set with
PISAMA_NATIVE_ANTHROPIC_CREDENTIAL_NAME. Optional: PISAMA_N8N_URL (default
localhost:5681), PISAMA_SERVER_URL (default localhost:8411).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence

from capture_claude_agent_evidence import (
    SERVER_URL,
    _retire_captures,
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
_NATIVE_OUTPUT_PARSER = "@n8n/n8n-nodes-langchain.outputParserStructured"
_STRUCTURED_PARSER_ERROR = "Model output doesn't fit required format"


def _anthropic_credential() -> Dict[str, str]:
    """Create an ephemeral native Anthropic credential without serializing its key."""
    reusable_id = os.getenv("PISAMA_NATIVE_ANTHROPIC_CREDENTIAL_ID", "").strip()
    if reusable_id:
        return {
            "id": reusable_id,
            "name": os.getenv(
                "PISAMA_NATIVE_ANTHROPIC_CREDENTIAL_NAME", "Anthropic account"
            ),
        }
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


def _delete_ephemeral_credential(credential: Dict[str, str]) -> None:
    """Do not delete the shared credential used by the restricted Cloud key."""
    if os.getenv("PISAMA_NATIVE_ANTHROPIC_CREDENTIAL_ID", "").strip():
        return
    _n8n("DELETE", f"/api/v1/credentials/{credential['id']}")


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


def _named_tool(
    name: str, description: str, code: str, position: List[int]
) -> Dict[str, Any]:
    """Build one native Code Tool without copying its runtime inputs into output."""
    return {
        "parameters": {
            "name": name,
            "description": description,
            "jsCode": code,
            "language": "javaScript",
            "specifyInputSchema": False,
        },
        "id": name,
        "name": name,
        "type": _NATIVE_TOOL,
        "typeVersion": 1.2,
        "position": position,
    }


def _extended_agent(
    name: str,
    prompt: str,
    *,
    max_iterations: int,
    has_output_parser: bool,
) -> Dict[str, Any]:
    """Build a native Tools Agent for an explicitly bounded evidence experiment."""
    return {
        "parameters": {
            "agent": "toolsAgent",
            "promptType": "define",
            "text": prompt,
            "hasOutputParser": has_output_parser,
            "options": {
                "maxIterations": max_iterations,
                "returnIntermediateSteps": True,
                "systemMessage": (
                    "You are a deterministic native n8n dogfood agent. Follow the "
                    "tool instructions exactly and keep the final answer short."
                ),
            },
        },
        "id": name,
        "name": name,
        "type": _NATIVE_AGENT,
        "typeVersion": 1.9,
        "position": [240, 0],
    }


def _structured_output_parser(schema: str) -> Dict[str, Any]:
    """Build n8n's parser v1 so its real runtime contract is explicit."""
    return {
        "parameters": {"jsonSchema": schema},
        "id": "structured-parser",
        "name": "Native Structured Output Parser",
        "type": _NATIVE_OUTPUT_PARSER,
        "typeVersion": 1,
        "position": [240, 360],
    }


def _native_edge(target: str, edge_type: str) -> Dict[str, Any]:
    """Return one direct n8n AI edge to an Agent node."""
    return {"node": target, "type": edge_type, "index": 0}


def _extended_connections(
    agent: str, tools: List[str], *, has_output_parser: bool
) -> Dict[str, Any]:
    """Connect exactly one model, named tools, and optionally one output parser."""
    connections: Dict[str, Any] = {
        "Native agent webhook": {
            "main": [[{"node": agent, "type": "main", "index": 0}]]
        },
        "Native Anthropic Chat Model": {
            "ai_languageModel": [[_native_edge(agent, "ai_languageModel")]]
        },
    }
    for tool in tools:
        connections[tool] = {"ai_tool": [[_native_edge(agent, "ai_tool")]]}
    if has_output_parser:
        connections["Native Structured Output Parser"] = {
            "ai_outputParser": [[_native_edge(agent, "ai_outputParser")]]
        }
    return connections


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


def _structured_workflow(
    name: str, credential: Dict[str, str], schema: str
) -> Dict[str, Any]:
    """Create one native output-parser control or rejection experiment.

    The parser receives an explicit JSON schema through n8n's native Agent topology.
    A valid but unsatisfiable schema is deliberately used only for the rejection
    captures. It exercises n8n's real parser error path without pretending that a
    particular model response is malformed.
    """
    path = f"pisama-native-structured-{name}-{int(time.time() * 1000)}"
    agent_name = "Native structured AI Agent"
    tool_name = "structured_control_tool"
    tool = _named_tool(
        tool_name,
        "A harmless native tool. Do not call it for the structured-output test.",
        "return 'native structured control';",
        [240, 540],
    )
    prompt = (
        "Return a JSON object with one answer field containing a short status. "
        "Do not call the structured_control_tool."
    )
    return {
        "name": f"Pisama temporary native structured parser {name}",
        "nodes": [
            _webhook(path),
            _extended_agent(
                agent_name,
                prompt,
                max_iterations=2,
                has_output_parser=True,
            ),
            _model(credential),
            tool,
            _structured_output_parser(schema),
        ],
        "connections": _extended_connections(
            agent_name, [tool_name], has_output_parser=True
        ),
        "settings": {},
        "_path": path,
    }


def _multi_tool_workflow(
    name: str,
    credential: Dict[str, str],
    *,
    primary_fails: bool,
    max_iterations: int,
) -> Dict[str, Any]:
    """Create a real native two-tool control or bounded recovery execution."""
    path = f"pisama-native-multi-tool-{name}-{int(time.time() * 1000)}"
    agent_name = "Native multi-tool AI Agent"
    primary_name = "primary_lookup"
    backup_name = "backup_lookup"
    primary_code = (
        "throw new Error('Pisama native controlled primary tool failure');"
        if primary_fails
        else "return 'native primary lookup completed';"
    )
    tools = [
        _named_tool(
            primary_name,
            "Looks up a native dogfood status. Use it first.",
            primary_code,
            [160, 360],
        ),
        _named_tool(
            backup_name,
            "Returns the backup native dogfood status after a primary error.",
            "return 'native backup lookup completed';",
            [360, 360],
        ),
    ]
    prompt = (
        "Use the primary_lookup tool exactly once with query "
        f"native-multi-tool-{name}. Do not answer before using it. If "
        "primary_lookup reports an error, use backup_lookup exactly once with the "
        "same query. After a successful lookup, give one short final answer. Do not "
        "repeat either tool or call another tool."
    )
    return {
        "name": f"Pisama temporary native multi-tool {name}",
        "nodes": [
            _webhook(path),
            _extended_agent(
                agent_name,
                prompt,
                max_iterations=max_iterations,
                has_output_parser=False,
            ),
            _model(credential),
            *tools,
        ],
        "connections": _extended_connections(
            agent_name, [primary_name, backup_name], has_output_parser=False
        ),
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


def _capture_extended_workflows(
    credential: Dict[str, str], labels: Optional[Sequence[str]] = None
) -> Dict[str, Dict[str, Any]]:
    """Run fresh native parser and two-tool evidence experiments.

    This is deliberately a capture harness, not a detector claim. The first output
    records the exact n8n execution topology and statuses safely; detector rules are
    allowed to change only after those real executions have been inspected.
    """
    satisfiable_schema = json.dumps(
        {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
        separators=(",", ":"),
    )
    unsatisfiable_schema = '{"not":{}}'
    builders = (
        (
            "structured_control",
            lambda: _structured_workflow("control", credential, satisfiable_schema),
        ),
        (
            "structured_rejection_one",
            lambda: _structured_workflow(
                "rejection-one", credential, unsatisfiable_schema
            ),
        ),
        (
            "structured_rejection_two",
            lambda: _structured_workflow(
                "rejection-two", credential, unsatisfiable_schema
            ),
        ),
        (
            "multi_tool_healthy",
            lambda: _multi_tool_workflow(
                "healthy", credential, primary_fails=False, max_iterations=4
            ),
        ),
        (
            "multi_tool_recovery",
            lambda: _multi_tool_workflow(
                "recovery", credential, primary_fails=True, max_iterations=4
            ),
        ),
        (
            "multi_tool_unhandled",
            lambda: _multi_tool_workflow(
                "unhandled", credential, primary_fails=True, max_iterations=1
            ),
        ),
    )
    requested = set(labels or ())
    if requested:
        builders = tuple(
            (label, build_workflow)
            for label, build_workflow in builders
            if label in requested
        )
        if len(builders) != len(requested):
            raise RuntimeError("unknown native extended evidence label")
    captures: Dict[str, Dict[str, Any]] = {}
    try:
        for label, build_workflow in builders:
            captures[label] = _run_workflow(build_workflow())
        return captures
    except Exception:
        _retire_captures(captures.values())
        raise


def _safe_run_summary(run: Dict[str, Any]) -> Dict[str, Any]:
    """Keep execution-shape facts while excluding model and tool payloads."""
    index = run.get("executionIndex")
    return {
        "execution_index": index if isinstance(index, int) else None,
        "status": run.get("executionStatus"),
        "has_error": bool(run.get("error")),
    }


def _safe_capture_shape(capture: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize real node topology and order without serializing trace content."""
    node_runs = {
        name: [_safe_run_summary(run) for run in runs if isinstance(run, dict)]
        for name, runs in capture["run_data"].items()
        if isinstance(name, str) and isinstance(runs, list)
    }
    agent_name = next(
        (
            name
            for name in ("Native structured AI Agent", "Native multi-tool AI Agent")
            if name in node_runs
        ),
        None,
    )
    action_tools: List[str] = []
    if agent_name:
        for run in _runs(capture, agent_name):
            for step in _agent_intermediate_steps(run):
                action = step.get("action") if isinstance(step, dict) else None
                tool = action.get("tool") if isinstance(action, dict) else None
                if isinstance(tool, str):
                    action_tools.append(tool)
    parser_runs = _runs(capture, "Native Structured Output Parser")
    parser_error_matches_expected = any(
        isinstance(run.get("error"), dict)
        and run["error"].get("message") == _STRUCTURED_PARSER_ERROR
        for run in parser_runs
    )
    return {
        "execution_id": str(capture["execution_id"]),
        "workflow_status": capture.get("status"),
        "finished": capture.get("finished"),
        "node_runs": node_runs,
        "agent_action_tools": action_tools,
        "parser_error_matches_expected": parser_error_matches_expected,
    }


def _assert_extended_retention(captures: Dict[str, Dict[str, Any]]) -> None:
    """Require n8n to retain the real node runs before interpreting them."""
    for label, capture in captures.items():
        if not capture.get("stopped_at"):
            raise RuntimeError(f"native extended capture did not stop: {label}")
        run_data = capture.get("run_data")
        if not isinstance(run_data, dict) or not run_data:
            raise RuntimeError(f"native extended capture has no run data: {label}")
        required = (
            "Native structured AI Agent"
            if label.startswith("structured_")
            else "Native multi-tool AI Agent"
        )
        if not _runs(capture, required):
            raise RuntimeError(
                f"native extended capture omitted the Agent run: {label}"
            )


def capture_extended_evidence(labels: Optional[Sequence[str]] = None) -> None:
    """Capture native structured-parser and two-tool paths from fresh n8n executions."""
    captures: Dict[str, Dict[str, Any]] = {}
    credential = _anthropic_credential()
    try:
        captures = _capture_extended_workflows(credential, labels)
        _assert_extended_retention(captures)
        sync = _server_sync()
        findings = _fired_by_execution(captures.values())
        print(
            json.dumps(
                {
                    "captures": {
                        label: _safe_capture_shape(capture)
                        for label, capture in captures.items()
                    },
                    "sync": sync,
                    "fired_fingerprints": findings,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        _retire_captures(captures.values())
        _delete_ephemeral_credential(credential)


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
        _retire_captures(captures)
        _delete_ephemeral_credential(credential)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--extended",
        action="store_true",
        help="Capture real native structured-parser and multi-tool evidence.",
    )
    mode.add_argument(
        "--multi-tool-only",
        action="store_true",
        help="Capture real native two-tool controls and recovery evidence only.",
    )
    args = parser.parse_args()
    if args.extended:
        capture_extended_evidence()
    elif args.multi_tool_only:
        capture_extended_evidence(
            ["multi_tool_healthy", "multi_tool_recovery", "multi_tool_unhandled"]
        )
    else:
        main()
