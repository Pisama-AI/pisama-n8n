"""Evidence-gated runtime detectors for n8n executions.

These detectors intentionally consume only facts n8n recorded for an execution or
its workflow snapshot.  They do not infer an incident from a workflow's appearance.
"""

from __future__ import annotations

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

class N8NRetryRecoveryDetector(TurnAwareDetector):
    """Flag a retry-enabled failure when n8n cannot prove its retry outcome."""

    name = "N8NRetryRecoveryDetector"
    version = "1.1"
    supported_failure_modes = ["F14"]

    def detect(
        self,
        turns: List[TurnSnapshot],
        conversation_metadata: Optional[Dict[str, Any]] = None,
    ) -> TurnAwareDetectionResult:
        retry_enabled_failures = _retry_enabled_error_turns(turns)
        if not retry_enabled_failures:
            return _clear(
                self.name,
                "No recorded retry-enabled node failure requires a retry-evidence check.",
            )
        if _retry_outcome_is_ambiguous(
            retry_enabled_failures, conversation_metadata
        ):
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
