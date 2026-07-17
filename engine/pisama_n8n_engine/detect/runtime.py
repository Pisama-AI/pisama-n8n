"""Evidence-gated runtime detectors for n8n executions.

These detectors intentionally consume only facts n8n recorded for an execution or
its workflow snapshot.  They do not infer an incident from a workflow's appearance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from pisama_n8n_engine.detect.base import (
    TurnAwareDetectionResult,
    TurnAwareDetector,
    TurnAwareSeverity,
    TurnSnapshot,
)
from pisama_n8n_engine.detect.truncation import TRUNCATION_VALUES


_EXPRESSION_MARKERS = (
    "cannot read properties",
    "cannot read property",
    "is not defined",
    "referenceerror",
    "expression",
    "invalid json",
    "json parse",
    "expected a string",
    "expected a number",
    "undefined",
    "null (reading",
)
_PROVIDER_MARKERS = (
    "econnreset",
    "econnrefused",
    "enotfound",
    "service unavailable",
    "internal server error",
    "bad gateway",
    "gateway timeout",
)
_N8N_ABORTED_CONNECTION = "connection was aborted"
_NATIVE_AI_AGENT_TYPE = "@n8n/n8n-nodes-langchain.agent"
_NATIVE_LANGUAGE_MODEL_PREFIX = "@n8n/n8n-nodes-langchain.lm"


def recorded_timeout(turn: TurnSnapshot) -> bool:
    """Recognize n8n's recorded HTTP-timeout shape without guessing from text.

    n8n 1.91 recorded a configured HTTP timeout as ``connection was aborted`` rather
    than the word ``timeout``. Require all three facts, a failed node, an explicit
    request timeout, and elapsed time close to that limit, before classifying it.
    """
    metadata = turn.turn_metadata or {}
    if not metadata.get("has_error"):
        return False
    timeout_ms = metadata.get("configured_timeout_ms")
    execution_time_ms = metadata.get("execution_time_ms")
    try:
        timeout_ms = int(timeout_ms)
        execution_time_ms = int(execution_time_ms)
    except (TypeError, ValueError):
        return False
    message = str(metadata.get("error_message") or turn.content).lower()
    return (
        timeout_ms > 0
        and execution_time_ms >= timeout_ms * 0.75
        and _N8N_ABORTED_CONNECTION in message
    )


def _contains_marker(message: str, markers: Iterable[str]) -> bool:
    return any(marker in message for marker in markers)


def _is_provider_error(status_code: Any, message: str) -> bool:
    return (isinstance(status_code, int) and status_code >= 500) or _contains_marker(
        message, _PROVIDER_MARKERS
    )


def classify_error(turn: TurnSnapshot) -> str:
    """Classify a recorded n8n node error without guessing from healthy output."""
    metadata = turn.turn_metadata or {}
    status_code = metadata.get("http_status")
    message = str(metadata.get("error_message") or turn.content).lower()
    checks = (
        (
            "rate_limit",
            status_code == 429
            or _contains_marker(message, ("too many requests", "rate limit")),
        ),
        (
            "credential",
            status_code in (401, 403)
            or _contains_marker(
                message,
                ("unauthorized", "authentication", "invalid credential", "forbidden"),
            ),
        ),
        ("expression", _contains_marker(message, _EXPRESSION_MARKERS)),
        ("timeout", recorded_timeout(turn)),
        ("provider", _is_provider_error(status_code, message)),
        (
            "timeout",
            _contains_marker(
                message, ("timed out", "timeout", "etimedout", "deadline exceeded")
            ),
        ),
    )
    return next((category for category, matches in checks if matches), "node_error")


def remediation_for(category: str) -> str:
    """A reviewable action for an evidence-backed incident category."""
    actions = {
        "rate_limit": "Add bounded retry with backoff and reduce request concurrency before retrying this provider.",
        "credential": "Reconnect or replace the credential and confirm the account has the required scope.",
        "expression": "Correct the failing expression or Code-node input assumption, then rerun with the observed input shape.",
        "provider": "Check the provider response and endpoint configuration; retry only transient failures with bounded backoff.",
        "timeout": "Set a bounded request timeout and retry policy, then inspect the slow provider or downstream service.",
        "node_error": "Inspect the recorded node error and configuration before applying a workflow change.",
    }
    return actions[category]


def _clear(detector_name: str, explanation: str) -> TurnAwareDetectionResult:
    return TurnAwareDetectionResult(
        detected=False,
        severity=TurnAwareSeverity.NONE,
        confidence=0.0,
        failure_mode=None,
        explanation=explanation,
        detector_name=detector_name,
    )


def _error_turns(turns: Iterable[TurnSnapshot]) -> List[TurnSnapshot]:
    return [turn for turn in turns if (turn.turn_metadata or {}).get("has_error")]


def _retry_enabled_error_turns(turns: Iterable[TurnSnapshot]) -> List[TurnSnapshot]:
    """Return failed nodes for which n8n retained retry-on-fail configuration."""
    return [
        turn
        for turn in _error_turns(turns)
        if (turn.turn_metadata or {}).get("retry_on_fail")
    ]


def _recorded_retry_attempt_count(turns: Iterable[TurnSnapshot]) -> int:
    """Return the largest retained node run count for this retry check."""
    return max(
        int((turn.turn_metadata or {}).get("attempt_count") or 1) for turn in turns
    )


def _retry_outcome_is_ambiguous(
    turns: Iterable[TurnSnapshot], metadata: Optional[Dict[str, Any]]
) -> bool:
    """Whether n8n recorded retry-like facts without a node-budget linkage."""
    execution = metadata or {}
    return _recorded_retry_attempt_count(turns) > 1 or bool(
        execution.get("retry_of") or execution.get("retry_success_id")
    )


def _retry_not_observed_result(
    detector_name: str, detector_version: str, turns: List[TurnSnapshot]
) -> TurnAwareDetectionResult:
    """Report a retry-enabled failure whose retry behavior was not retained."""
    names = ", ".join(dict.fromkeys(turn.participant_id for turn in turns))
    return TurnAwareDetectionResult(
        detected=True,
        severity=TurnAwareSeverity.MODERATE,
        confidence=0.95,
        failure_mode="n8n_retry_not_observed",
        explanation=(
            f"Retry-enabled node(s) failed, but this n8n execution recorded no repeat attempt: {names}. "
            "Verify retry support and settings for this node type before relying on recovery."
        ),
        affected_turns=[turn.turn_number for turn in turns],
        evidence={
            "nodes": [turn.participant_id for turn in turns],
            "recorded_node_runs": _recorded_retry_attempt_count(turns),
            "retry_observed": False,
        },
        suggested_fix="Verify the node's retry behavior with a controlled failure and route unrecoverable errors to an error workflow.",
        detector_name=detector_name,
        detector_version=detector_version,
    )


def _failed_workflow_status(metadata: Dict[str, Any]) -> bool:
    """Whether n8n recorded a workflow status that needs error-route review."""
    return str(metadata.get("workflow_status") or "").lower() in {
        "error",
        "crashed",
        "failed",
    }


def _failed_turn_numbers(failed: List[TurnSnapshot]) -> List[int]:
    return [turn.turn_number for turn in failed]


def _failed_node_names(failed: List[TurnSnapshot]) -> List[str]:
    return [turn.participant_id for turn in failed]


def _error_route_evidence(
    metadata: Dict[str, Any], error_workflow_id: Any, failed: List[TurnSnapshot]
) -> Dict[str, Any]:
    """Return the small, non-payload audit record for an error-route finding."""
    resolution = metadata.get("error_workflow_resolution") or {}
    status = resolution.get("status") if isinstance(resolution, dict) else None
    return {
        "source_execution_id": metadata.get("execution_id"),
        "source_mode": metadata.get("workflow_mode"),
        "error_workflow_id": str(error_workflow_id),
        "resolver_status": status or "unverifiable",
        "failed_nodes": _failed_node_names(failed),
    }


def _error_trigger_count(metadata: Dict[str, Any]) -> Optional[int]:
    """Count a resolved n8n target's Error Trigger nodes, or return unknown."""
    error_workflow = metadata.get("error_workflow_json") or {}
    nodes = error_workflow.get("nodes") if isinstance(error_workflow, dict) else None
    if not isinstance(nodes, list):
        return None
    return sum(
        isinstance(node, dict)
        and str(node.get("type") or "") == "n8n-nodes-base.errorTrigger"
        for node in nodes
    )


def _configured_error_route_result(
    detector_name: str,
    detector_version: str,
    metadata: Dict[str, Any],
    error_workflow_id: Any,
    failed: List[TurnSnapshot],
) -> TurnAwareDetectionResult:
    """Classify a configured route only when the n8n resolver proves its state."""
    evidence = _error_route_evidence(metadata, error_workflow_id, failed)
    status = evidence["resolver_status"]
    if status == "missing":
        return TurnAwareDetectionResult(
            detected=True,
            severity=TurnAwareSeverity.MODERATE,
            confidence=0.95,
            failure_mode="n8n_error_workflow_target_missing",
            explanation=(
                "This execution failed, and n8n's configured error-workflow ID no longer exists. "
                "Route incidents to an existing Error Trigger workflow."
            ),
            affected_turns=_failed_turn_numbers(failed),
            evidence=evidence,
            suggested_fix="Choose an existing reviewed Error Trigger workflow and attach its current ID in this workflow's errorWorkflow setting.",
            detector_name=detector_name,
            detector_version=detector_version,
        )
    if status != "available":
        return _clear(
            detector_name,
            "The configured error workflow could not be read, so its route is not classified.",
        )
    error_trigger_count = _error_trigger_count(metadata)
    if error_trigger_count is None:
        return _clear(
            detector_name,
            "The configured error workflow could not be read, so its route is not classified.",
        )
    if error_trigger_count:
        return _clear(
            detector_name,
            "The failed workflow's configured error route contains an Error Trigger.",
        )
    return TurnAwareDetectionResult(
        detected=True,
        severity=TurnAwareSeverity.MODERATE,
        confidence=0.95,
        failure_mode="n8n_error_workflow_missing_trigger",
        explanation=(
            "This execution failed, and its configured n8n error workflow has no Error Trigger node. "
            "n8n cannot use that workflow as an incident route."
        ),
        affected_turns=_failed_turn_numbers(failed),
        evidence={**evidence, "error_trigger_count": 0},
        suggested_fix="Replace the target with a reviewed Error Trigger workflow, then run a controlled failure to confirm it receives the incident.",
        detector_name=detector_name,
        detector_version=detector_version,
    )


class N8NTruncationDetector(TurnAwareDetector):
    """Detect an LLM output explicitly stopped at its token budget."""

    name = "N8NTruncationDetector"
    version = "1.0"
    supported_failure_modes = ["F6"]

    def detect(
        self,
        turns: List[TurnSnapshot],
        conversation_metadata: Optional[Dict[str, Any]] = None,
    ) -> TurnAwareDetectionResult:
        truncated = [
            turn
            for turn in turns
            if str((turn.turn_metadata or {}).get("finish_reason") or "").lower()
            in TRUNCATION_VALUES
        ]
        if not truncated:
            return _clear(
                self.name, "No recorded AI-node output reached a token limit."
            )
        names = ", ".join(dict.fromkeys(turn.participant_id for turn in truncated))
        return TurnAwareDetectionResult(
            detected=True,
            severity=TurnAwareSeverity.MODERATE,
            confidence=0.95,
            failure_mode="n8n_truncation",
            explanation=(
                f"{len(truncated)} AI node output(s) ended at the provider token limit: {names}. "
                "Raise the output limit or add an explicit continuation step before using the result."
            ),
            affected_turns=[turn.turn_number for turn in truncated],
            evidence={
                "finish_reasons": [
                    {
                        "node": turn.participant_id,
                        "reason": turn.turn_metadata["finish_reason"],
                    }
                    for turn in truncated
                ]
            },
            suggested_fix="Raise the output limit or continue the response in a bounded follow-up call.",
            detector_name=self.name,
            detector_version=self.version,
        )


def _ordered_agent_turns(turns: Iterable[TurnSnapshot]) -> List[TurnSnapshot]:
    """Return only agent facts whose order n8n recorded explicitly."""
    ordered = [
        turn
        for turn in turns
        if (turn.turn_metadata or {}).get("execution_order_tier") == 0
        and isinstance((turn.turn_metadata or {}).get("execution_index"), int)
    ]
    return sorted(ordered, key=lambda turn: turn.turn_metadata["execution_index"])


def _matching_failed_tool_result(
    turns: List[TurnSnapshot], tool_turn: TurnSnapshot
) -> Optional[TurnSnapshot]:
    """Find a later failed result through n8n's observed one-hop tool chain."""
    tool_ids = set((tool_turn.turn_metadata or {}).get("tool_use_ids") or [])
    if not tool_ids:
        return None
    for turn in turns:
        metadata = turn.turn_metadata or {}
        if metadata["execution_index"] <= tool_turn.turn_metadata["execution_index"]:
            continue
        if not _tool_result_is_linked(turns, tool_turn, turn):
            continue
        for result in metadata.get("tool_results") or []:
            if (
                isinstance(result, dict)
                and result.get("tool_use_id") in tool_ids
                and result.get("is_error") is True
            ):
                return turn
    return None


def _tool_result_is_linked(
    turns: List[TurnSnapshot], tool_turn: TurnSnapshot, result_turn: TurnSnapshot
) -> bool:
    """Match direct or one-hop n8n source links, never an inferred graph path.

    Real captures place the HTTP tool failure between Claude's ``tool_use`` output
    and the Code node that converts its recorded error into ``tool_result``. The
    one-hop allowance models that exact n8n shape without treating an arbitrary
    later result as belonging to the tool call.
    """
    sources = set((result_turn.turn_metadata or {}).get("source_nodes") or [])
    if tool_turn.participant_id in sources:
        return True
    tool_index = tool_turn.turn_metadata["execution_index"]
    result_index = result_turn.turn_metadata["execution_index"]
    return any(
        candidate.participant_id in sources
        and tool_turn.participant_id
        in (candidate.turn_metadata.get("source_nodes") or [])
        and tool_index < candidate.turn_metadata["execution_index"] < result_index
        for candidate in turns
    )


def _recovery_response(
    turns: List[TurnSnapshot], result_turn: TurnSnapshot
) -> Optional[TurnSnapshot]:
    """Return a direct Claude response after the failed result, if n8n recorded one."""
    for turn in turns:
        metadata = turn.turn_metadata or {}
        if metadata["execution_index"] <= result_turn.turn_metadata["execution_index"]:
            continue
        if result_turn.participant_id not in (metadata.get("source_nodes") or []):
            continue
        if metadata.get("is_claude_message"):
            return turn
    return None


def _json_validation_error(turn: TurnSnapshot) -> bool:
    """Match the real n8n Code-node JSON.parse error contract, narrowly."""
    metadata = turn.turn_metadata or {}
    if not metadata.get("has_error"):
        return False
    if metadata.get("node_type") != "n8n-nodes-base.code":
        return False
    code = str((metadata.get("parameters") or {}).get("jsCode") or "")
    message = str(metadata.get("error_message") or "").lower()
    return (
        "json.parse" in code.lower()
        and "unexpected token" in message
        and "valid json" in message
    )


def _strongly_ordered(turn: TurnSnapshot) -> bool:
    """Whether n8n retained the execution order required for causal claims."""
    metadata = turn.turn_metadata or {}
    return metadata.get("execution_order_tier") == 0 and isinstance(
        metadata.get("execution_index"), int
    )


def _single_static_node(metadata: Dict[str, Any], key: str) -> Optional[str]:
    """Return one literal workflow-edge peer, otherwise mark it ambiguous."""
    values = metadata.get(key)
    if (
        isinstance(values, list)
        and len(values) == 1
        and isinstance(values[0], str)
        and values[0]
    ):
        return values[0]
    return None


def _targets_only_agent(metadata: Dict[str, Any], key: str, agent: str) -> bool:
    """Require a tool/model node's direct AI edge to be exclusive to one Agent."""
    targets = metadata.get(key)
    return isinstance(targets, list) and len(targets) == 1 and targets[0] == agent


def _native_language_model(turn: TurnSnapshot) -> bool:
    node_type = str((turn.turn_metadata or {}).get("node_type") or "")
    return node_type.startswith(_NATIVE_LANGUAGE_MODEL_PREFIX)


@dataclass(frozen=True)
class _NativeToolFailureContext:
    """The strict native-Agent facts needed for one recovery decision."""

    agent: TurnSnapshot
    tool: TurnSnapshot
    initial_model: TurnSnapshot
    model_turns: List[TurnSnapshot]


def _single_ordered_native_agent(
    turns: List[TurnSnapshot],
) -> Optional[TurnSnapshot]:
    """Return the sole strongly-ordered native Agent run, if unambiguous."""
    native_agents = [
        turn
        for turn in turns
        if (turn.turn_metadata or {}).get("node_type") == _NATIVE_AI_AGENT_TYPE
    ]
    if len(native_agents) != 1:
        return None
    agent = native_agents[0]
    return agent if _strongly_ordered(agent) else None


def _single_native_agent_action(metadata: Dict[str, Any]) -> Optional[tuple[str, str]]:
    """Return one native action's tool name and observation, if recorded."""
    actions = metadata.get("native_agent_actions")
    if not isinstance(actions, list) or len(actions) != 1:
        return None
    action = actions[0]
    if not isinstance(action, dict) or not action.get("has_tool_call_id"):
        return None
    tool_name = action.get("tool")
    observation = action.get("observation")
    if not isinstance(tool_name, str) or not tool_name:
        return None
    if not isinstance(observation, str):
        return None
    return tool_name, observation


def _direct_native_model(metadata: Dict[str, Any], tool_name: str) -> Optional[str]:
    """Return the one direct native model paired with this Agent tool."""
    direct_tool = _single_static_node(metadata, "native_agent_tool_nodes")
    direct_model = _single_static_node(metadata, "native_agent_model_nodes")
    if tool_name != direct_tool or not direct_model:
        return None
    return direct_model


def _named_turns(turns: List[TurnSnapshot], name: str) -> List[TurnSnapshot]:
    """Return every recorded run for one n8n node name."""
    return [turn for turn in turns if turn.participant_id == name]


def _single_named_turn(turns: List[TurnSnapshot], name: str) -> Optional[TurnSnapshot]:
    """Return one recorded node run, rejecting repeated executions as ambiguous."""
    matches = _named_turns(turns, name)
    return matches[0] if len(matches) == 1 else None


def _only_direct_native_models(
    turns: List[TurnSnapshot], model_turns: List[TurnSnapshot]
) -> bool:
    """Reject executions that contain a second, unrelated native language model."""
    return sum(_native_language_model(turn) for turn in turns) == len(model_turns)


def _strongly_ordered_turns(turns: List[TurnSnapshot]) -> bool:
    """Whether every retained runtime turn has n8n's execution index."""
    return all(_strongly_ordered(turn) for turn in turns)


def _native_peer_runs(
    turns: List[TurnSnapshot], tool_name: str, model_name: str
) -> Optional[tuple[TurnSnapshot, List[TurnSnapshot]]]:
    """Return the exclusive native tool and model runs, if their order is strong."""
    tool_turn = _single_named_turn(turns, tool_name)
    model_turns = _named_turns(turns, model_name)
    if tool_turn is None or not model_turns:
        return None
    if not _only_direct_native_models(turns, model_turns):
        return None
    if not _strongly_ordered_turns([tool_turn, *model_turns]):
        return None
    return tool_turn, model_turns


def _exclusive_native_peer_topology(
    tool: TurnSnapshot, model_turns: List[TurnSnapshot], agent_name: str
) -> bool:
    """Require the direct tool and every model run to belong only to this Agent."""
    tool_metadata = tool.turn_metadata or {}
    if not _targets_only_agent(
        tool_metadata, "native_ai_tool_target_agents", agent_name
    ):
        return False
    return all(
        _targets_only_agent(
            turn.turn_metadata or {}, "native_ai_model_target_agents", agent_name
        )
        for turn in model_turns
    )


def _recorded_native_tool_error(tool: TurnSnapshot) -> Optional[str]:
    """Return the non-empty tool error only when n8n recorded a failed run."""
    metadata = tool.turn_metadata or {}
    error = metadata.get("error_message")
    if not metadata.get("has_error") or not isinstance(error, str) or not error:
        return None
    return error


def _single_model_before_tool(
    model_turns: List[TurnSnapshot], tool: TurnSnapshot
) -> Optional[TurnSnapshot]:
    """Return the sole direct model turn before the recorded tool error."""
    tool_index = tool.turn_metadata["execution_index"]
    initial_models = [
        turn
        for turn in model_turns
        if turn.turn_metadata["execution_index"] < tool_index
    ]
    return initial_models[0] if len(initial_models) == 1 else None


def _native_tool_failure_context(
    turns: List[TurnSnapshot],
) -> Optional[_NativeToolFailureContext]:
    """Return the narrow native-Agent failure contract, or ``None`` if ambiguous.

    Native Agent child runs in observed n8n 1.91 telemetry contain no source links.
    A claim is therefore permitted only for one Agent, one action, one direct tool,
    and one direct language model. The agent observation must contain the precise
    error n8n recorded for that tool. Anything more complex is intentionally
    inconclusive until n8n exposes an authoritative runtime correlation ID.
    """
    agent = _single_ordered_native_agent(turns)
    if agent is None:
        return None
    agent_metadata = agent.turn_metadata or {}
    action = _single_native_agent_action(agent_metadata)
    if action is None:
        return None
    tool_name, observation = action
    model_name = _direct_native_model(agent_metadata, tool_name)
    if model_name is None:
        return None
    peers = _native_peer_runs(turns, tool_name, model_name)
    if peers is None:
        return None
    tool, model_turns = peers
    if not _exclusive_native_peer_topology(tool, model_turns, agent.participant_id):
        return None
    error = _recorded_native_tool_error(tool)
    if error is None or error not in observation:
        return None
    initial_model = _single_model_before_tool(model_turns, tool)
    if initial_model is None:
        return None
    return _NativeToolFailureContext(
        agent=agent,
        tool=tool,
        initial_model=initial_model,
        model_turns=model_turns,
    )


def recovered_native_agent_tool_turns(
    turns: List[TurnSnapshot],
) -> List[TurnSnapshot]:
    """Return the one native tool error n8n proved a later model turn handled.

    This is intentionally narrower than ordinary ``continueOnFail`` handling. It
    suppresses the broad error detector only when the same strict native-Agent
    contract proves a later direct model invocation after the tool error.
    """
    context = _native_tool_failure_context(turns)
    if context is None:
        return []
    tool = context.tool
    tool_index = tool.turn_metadata["execution_index"]
    if any(
        turn.turn_metadata["execution_index"] > tool_index
        for turn in context.model_turns
    ):
        return [tool]
    return []


class N8NAgentDiagnosticsDetector(TurnAwareDetector):
    """Detect narrow Claude Messages and native n8n AI Agent failure contracts.

    Claude Messages findings require its observed runtime source links. Native AI Agent
    findings use a separate, stricter one-Agent/one-tool/one-model contract because
    observed native child runs have no source links. Missing or more complex telemetry
    is intentionally inconclusive.
    """

    name = "N8NAgentDiagnosticsDetector"
    version = "1.1"
    supported_failure_modes = [
        "n8n_agent_tool_recovery",
        "n8n_agent_output_validation",
        "n8n_native_agent_tool_recovery",
    ]

    def detect(
        self,
        turns: List[TurnSnapshot],
        conversation_metadata: Optional[Dict[str, Any]] = None,
    ) -> TurnAwareDetectionResult:
        ordered = _ordered_agent_turns(turns)
        validation = self._output_validation(ordered)
        if validation is not None:
            return validation
        recovery = self._unhandled_tool_failure(ordered)
        if recovery is not None:
            return recovery
        native_recovery = self._native_unhandled_tool_failure(turns)
        if native_recovery is not None:
            return native_recovery
        return _clear(
            self.name,
            "No evidence-backed Claude Messages or native AI Agent failure contract was recorded.",
        )

    def _output_validation(
        self, turns: List[TurnSnapshot]
    ) -> Optional[TurnAwareDetectionResult]:
        for turn in turns:
            if not _json_validation_error(turn):
                continue
            sources = set((turn.turn_metadata or {}).get("source_nodes") or [])
            predecessor = next(
                (
                    candidate
                    for candidate in turns
                    if candidate.participant_id in sources
                    and candidate.turn_metadata.get("is_claude_message")
                    and candidate.turn_metadata["execution_index"]
                    < turn.turn_metadata["execution_index"]
                ),
                None,
            )
            if predecessor is None:
                continue
            return TurnAwareDetectionResult(
                detected=True,
                severity=TurnAwareSeverity.MODERATE,
                confidence=0.95,
                failure_mode="n8n_agent_output_validation",
                explanation=(
                    "A Claude Messages response flowed directly into a JSON.parse Code node, "
                    "which n8n recorded as invalid JSON. Add an explicit structured-output "
                    "contract or validation fallback before parsing."
                ),
                affected_turns=[predecessor.turn_number, turn.turn_number],
                evidence={
                    "response_node": predecessor.participant_id,
                    "response_execution_index": predecessor.turn_metadata[
                        "execution_index"
                    ],
                    "validator_node": turn.participant_id,
                    "validator_execution_index": turn.turn_metadata["execution_index"],
                },
                suggested_fix="Request schema-conformant output and route JSON validation failures to a bounded repair or fallback path.",
                detector_name=self.name,
                detector_version=self.version,
            )
        return None

    def _unhandled_tool_failure(
        self, turns: List[TurnSnapshot]
    ) -> Optional[TurnAwareDetectionResult]:
        for tool_turn in turns:
            if not (tool_turn.turn_metadata or {}).get("tool_use_ids"):
                continue
            result_turn = _matching_failed_tool_result(turns, tool_turn)
            if result_turn is None:
                continue
            if _recovery_response(turns, result_turn) is not None:
                continue
            return TurnAwareDetectionResult(
                detected=True,
                severity=TurnAwareSeverity.MODERATE,
                confidence=0.95,
                failure_mode="n8n_agent_tool_recovery",
                explanation=(
                    "n8n recorded a Claude tool call and a matching failed tool result, "
                    "but no source-linked Claude recovery response followed it."
                ),
                affected_turns=[tool_turn.turn_number, result_turn.turn_number],
                evidence={
                    "tool_request_node": tool_turn.participant_id,
                    "tool_request_execution_index": tool_turn.turn_metadata[
                        "execution_index"
                    ],
                    "failed_result_node": result_turn.participant_id,
                    "failed_result_execution_index": result_turn.turn_metadata[
                        "execution_index"
                    ],
                },
                suggested_fix="Pass the recorded failed tool result back to the Claude Messages call and add a bounded fallback for repeated tool failures.",
                detector_name=self.name,
                detector_version=self.version,
            )
        return None

    def _native_unhandled_tool_failure(
        self, turns: List[TurnSnapshot]
    ) -> Optional[TurnAwareDetectionResult]:
        """Report one native tool error only when no later direct model turn exists."""
        context = _native_tool_failure_context(turns)
        if context is None:
            return None
        model_turns = context.model_turns
        if len(model_turns) != 1:
            # The same direct model was invoked after the failed tool. That is the
            # real n8n recovery control, not evidence of an unhandled failure.
            return None
        agent = context.agent
        tool = context.tool
        initial_model = context.initial_model
        return TurnAwareDetectionResult(
            detected=True,
            severity=TurnAwareSeverity.MODERATE,
            confidence=0.90,
            failure_mode="n8n_native_agent_tool_recovery",
            explanation=(
                "n8n recorded a native AI Agent tool error in the Agent observation, "
                "but no later direct language-model turn was retained for recovery."
            ),
            affected_turns=sorted(
                [agent.turn_number, initial_model.turn_number, tool.turn_number]
            ),
            evidence={
                "agent_node": agent.participant_id,
                "agent_execution_index": agent.turn_metadata["execution_index"],
                "tool_node": tool.participant_id,
                "tool_execution_index": tool.turn_metadata["execution_index"],
                "model_node": initial_model.participant_id,
                "model_execution_index": initial_model.turn_metadata["execution_index"],
            },
            suggested_fix=(
                "Route native Agent tool errors through a bounded recovery turn or "
                "explicit fallback, then verify the next real execution."
            ),
            detector_name=self.name,
            detector_version=self.version,
        )


class N8NRetryRecoveryDetector(TurnAwareDetector):
    """Flag a retry-enabled failure when n8n cannot prove its retry outcome.

    Withheld by default (``release_gate = False``). n8n ``1.70`` and ``1.91`` export
    exactly one node run for a retried node, so ``attempt_count`` is always ``1`` and
    the ambiguity gate in ``_retry_outcome_is_ambiguous`` never trips. The detector
    therefore cannot distinguish "retry configured but did not run" from "retry ran and
    n8n collapsed the run record", which made ``n8n_retry_not_observed`` fire at
    MODERATE/0.95 on essentially every retry-enabled failure. Rather than ship that
    false-positive, the whole detector is held behind ``release_gate`` until a real n8n
    telemetry source can prove a retry outcome without confusing it with an ordinary
    single node run. The detector still exists and its logic is retained for when that
    telemetry lands; it simply does not emit ``detected=True`` by default. See
    ``docs/dogfooding.md`` (Withheld detector modes) and
    ``scripts/audit_dogfood_corpus.py``.
    """

    name = "N8NRetryRecoveryDetector"
    version = "1.2"
    supported_failure_modes = ["F14"]
    # Honest withholding: the single-node-run export limitation makes every positive an
    # unverifiable guess, so the detector is gated off. Flip only when real n8n telemetry
    # can prove a retry outcome (then re-validate against dogfood before rollout).
    release_gate = False

    def detect(
        self,
        turns: List[TurnSnapshot],
        conversation_metadata: Optional[Dict[str, Any]] = None,
    ) -> TurnAwareDetectionResult:
        if not self.release_gate:
            return _clear(
                self.name,
                "Retry-recovery detection is withheld: n8n exports one node run for a "
                "retried node, so a retry-enabled failure cannot be distinguished from a "
                "retry that ran. See docs/dogfooding.md.",
            )
        retry_enabled_failures = _retry_enabled_error_turns(turns)
        if not retry_enabled_failures:
            return _clear(
                self.name,
                "No recorded retry-enabled node failure requires a retry-evidence check.",
            )
        if _retry_outcome_is_ambiguous(retry_enabled_failures, conversation_metadata):
            return _clear(
                self.name,
                "n8n recorded repeated runs or a workflow retry without an authoritative link to this node's retry budget; exhausted-retry detection is withheld.",
            )
        return _retry_not_observed_result(
            self.name, self.version, retry_enabled_failures
        )


class N8NErrorWorkflowDetector(TurnAwareDetector):
    """Flag a failed execution with no route or a verified invalid error route."""

    name = "N8NErrorWorkflowDetector"
    version = "1.1"
    supported_failure_modes = ["F14"]

    def detect(
        self,
        turns: List[TurnSnapshot],
        conversation_metadata: Optional[Dict[str, Any]] = None,
    ) -> TurnAwareDetectionResult:
        metadata = conversation_metadata or {}
        if not _failed_workflow_status(metadata):
            return _clear(
                self.name, "No failed execution requires an error-workflow check."
            )
        if not metadata.get("workflow_available"):
            return _clear(
                self.name,
                "The execution did not include workflow configuration for an error-workflow check.",
            )
        workflow = metadata.get("workflow_json") or {}
        settings = workflow.get("settings") or {}
        failed = _error_turns(turns)
        if not failed:
            return _clear(
                self.name, "The execution failed without a node error to route."
            )
        error_workflow_id = settings.get("errorWorkflow")
        if error_workflow_id:
            return _configured_error_route_result(
                self.name,
                self.version,
                metadata,
                error_workflow_id,
                failed,
            )
        return TurnAwareDetectionResult(
            detected=True,
            severity=TurnAwareSeverity.MODERATE,
            confidence=0.95,
            failure_mode="n8n_missing_error_workflow",
            explanation=(
                "This execution failed and its workflow has no configured n8n error workflow. "
                "Create a dedicated Error Trigger workflow for alerting and attach its workflow ID in settings."
            ),
            affected_turns=_failed_turn_numbers(failed),
            evidence={"failed_nodes": _failed_node_names(failed)},
            suggested_fix="Create and review a dedicated Error Trigger workflow, then attach it as this workflow's errorWorkflow setting.",
            detector_name=self.name,
            detector_version=self.version,
        )
