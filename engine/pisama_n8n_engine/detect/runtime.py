"""Evidence-gated runtime detectors for n8n executions.

These detectors intentionally consume only facts n8n recorded for an execution or
its workflow snapshot.  They do not infer an incident from a workflow's appearance.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

from pisama_n8n_engine.detect.base import (
    TurnAwareDetectionResult,
    TurnAwareDetector,
    TurnAwareSeverity,
    TurnSnapshot,
)
from pisama_n8n_engine.detect.truncation import TRUNCATION_VALUES


_UNSAFE_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
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


class N8NRetryRecoveryDetector(TurnAwareDetector):
    """Flag an observed failure after a node's configured retry budget was used."""

    name = "N8NRetryRecoveryDetector"
    version = "1.0"
    supported_failure_modes = ["F14"]

    def detect(
        self,
        turns: List[TurnSnapshot],
        conversation_metadata: Optional[Dict[str, Any]] = None,
    ) -> TurnAwareDetectionResult:
        exhausted = [
            turn
            for turn in _error_turns(turns)
            if (turn.turn_metadata or {}).get("retry_on_fail")
        ]
        if not exhausted:
            return _clear(
                self.name, "No recorded node failure exhausted a configured retry path."
            )
        names = ", ".join(dict.fromkeys(turn.participant_id for turn in exhausted))
        attempts = max(
            int((turn.turn_metadata or {}).get("attempt_count") or 1)
            for turn in exhausted
        )
        observed_retry = attempts > 1 or bool(
            (conversation_metadata or {}).get("retry_of")
        )
        failure_mode = (
            "n8n_retry_exhausted" if observed_retry else "n8n_retry_not_observed"
        )
        explanation = (
            f"Retry-enabled node(s) still failed after n8n recorded {attempts} attempt(s): {names}. "
            "Review the underlying incident, then set bounded backoff and a recovery or alert path."
            if observed_retry
            else f"Retry-enabled node(s) failed, but this n8n execution recorded no repeat attempt: {names}. "
            "Verify retry support and settings for this node type before relying on recovery."
        )
        return TurnAwareDetectionResult(
            detected=True,
            severity=TurnAwareSeverity.MODERATE,
            confidence=0.95,
            failure_mode=failure_mode,
            explanation=explanation,
            affected_turns=[turn.turn_number for turn in exhausted],
            evidence={
                "nodes": [turn.participant_id for turn in exhausted],
                "attempts": attempts,
                "observed_retry": observed_retry,
            },
            suggested_fix="Use bounded exponential backoff only for transient errors and send exhausted retries to an error workflow.",
            detector_name=self.name,
            detector_version=self.version,
        )


class N8NErrorWorkflowDetector(TurnAwareDetector):
    """Flag a real failed execution that lacks an n8n error-workflow route."""

    name = "N8NErrorWorkflowDetector"
    version = "1.0"
    supported_failure_modes = ["F14"]

    def detect(
        self,
        turns: List[TurnSnapshot],
        conversation_metadata: Optional[Dict[str, Any]] = None,
    ) -> TurnAwareDetectionResult:
        metadata = conversation_metadata or {}
        if str(metadata.get("workflow_status") or "").lower() not in {
            "error",
            "crashed",
            "failed",
        }:
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
        has_error_workflow = bool(settings.get("errorWorkflow"))
        if has_error_workflow:
            return _clear(
                self.name, "The failed workflow has an error-workflow route configured."
            )
        failed = _error_turns(turns)
        if not failed:
            return _clear(
                self.name, "The execution failed without a node error to route."
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
            affected_turns=[turn.turn_number for turn in failed],
            evidence={"failed_nodes": [turn.participant_id for turn in failed]},
            suggested_fix="Create and review a dedicated Error Trigger workflow, then attach it as this workflow's errorWorkflow setting.",
            detector_name=self.name,
            detector_version=self.version,
        )


class N8NIdempotencyDetector(TurnAwareDetector):
    """Detect a repeated unsafe HTTP action without an idempotency key."""

    name = "N8NIdempotencyDetector"
    version = "1.0"
    supported_failure_modes = ["F14"]

    def detect(
        self,
        turns: List[TurnSnapshot],
        conversation_metadata: Optional[Dict[str, Any]] = None,
    ) -> TurnAwareDetectionResult:
        repeated = Counter(turn.participant_id for turn in turns)
        risky = [
            turn
            for turn in turns
            if repeated[turn.participant_id] > 1
            and str((turn.turn_metadata or {}).get("http_method") or "").upper()
            in _UNSAFE_HTTP_METHODS
            and not (turn.turn_metadata or {}).get("has_idempotency_key")
        ]
        if not risky:
            return _clear(
                self.name, "No repeated unsafe HTTP action lacked an idempotency key."
            )
        names = ", ".join(dict.fromkeys(turn.participant_id for turn in risky))
        return TurnAwareDetectionResult(
            detected=True,
            severity=TurnAwareSeverity.SEVERE,
            confidence=0.95,
            failure_mode="n8n_duplicate_side_effect_risk",
            explanation=(
                f"n8n ran unsafe HTTP action(s) more than once without an Idempotency-Key: {names}. "
                "A retry may have repeated an external side effect; add a stable idempotency key before enabling retries."
            ),
            affected_turns=sorted({turn.turn_number for turn in risky}),
            evidence={
                "nodes": list(dict.fromkeys(turn.participant_id for turn in risky))
            },
            suggested_fix="Generate a stable Idempotency-Key from the business event and verify the provider honors it before retrying writes.",
            detector_name=self.name,
            detector_version=self.version,
        )


class N8NAgentDiagnosticsDetector(TurnAwareDetector):
    """Conservative AI-agent diagnostics, active only on observed agent/tool evidence."""

    name = "N8NAgentDiagnosticsDetector"
    version = "0.1"
    supported_failure_modes = ["F6", "F14"]

    def detect(
        self,
        turns: List[TurnSnapshot],
        conversation_metadata: Optional[Dict[str, Any]] = None,
    ) -> TurnAwareDetectionResult:
        agent_turns = [
            turn for turn in turns if (turn.turn_metadata or {}).get("is_ai_node")
        ]
        if not agent_turns:
            return _clear(
                self.name, "No AI-agent telemetry was recorded for this execution."
            )
        tool_failures = [
            turn
            for turn in _error_turns(turns)
            if "tool" in str((turn.turn_metadata or {}).get("node_type") or "").lower()
        ]
        recovered_tools = [
            failed
            for failed in tool_failures
            if any(agent.turn_number > failed.turn_number for agent in agent_turns)
        ]
        if recovered_tools:
            names = ", ".join(
                dict.fromkeys(turn.participant_id for turn in recovered_tools)
            )
            return TurnAwareDetectionResult(
                detected=True,
                severity=TurnAwareSeverity.MODERATE,
                confidence=0.95,
                failure_mode="n8n_agent_tool_recovery",
                explanation=(
                    f"AI-agent execution continued after a recorded tool failure: {names}. "
                    "Review the agent's recovery path and validate that downstream actions did not use the failed tool result."
                ),
                affected_turns=[turn.turn_number for turn in recovered_tools],
                evidence={
                    "tool_nodes": [turn.participant_id for turn in recovered_tools]
                },
                suggested_fix="Route failed tool calls through an explicit recovery and output-validation step.",
                detector_name=self.name,
                detector_version=self.version,
            )
        parser_errors = [
            turn
            for turn in _error_turns(agent_turns)
            if "output"
            in str((turn.turn_metadata or {}).get("error_message") or "").lower()
            and any(
                marker
                in str((turn.turn_metadata or {}).get("error_message") or "").lower()
                for marker in ("parse", "schema", "json")
            )
        ]
        if parser_errors:
            return TurnAwareDetectionResult(
                detected=True,
                severity=TurnAwareSeverity.MODERATE,
                confidence=0.95,
                failure_mode="n8n_agent_output_validation",
                explanation=(
                    "An AI-node output failed n8n's recorded structured-output validation. "
                    "Align the output parser/schema with the observed model response and retain validation before downstream actions."
                ),
                affected_turns=[turn.turn_number for turn in parser_errors],
                evidence={"nodes": [turn.participant_id for turn in parser_errors]},
                suggested_fix="Make the output schema explicit and route parser failures to a bounded recovery path.",
                detector_name=self.name,
                detector_version=self.version,
            )
        return _clear(
            self.name,
            "No observed AI-agent tool or output-validation failure was recorded.",
        )
