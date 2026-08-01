"""Thin n8n detection orchestrator — the standalone-engine seam.

Re-implements the aggregation the monorepo's 7k-line enterprise orchestrator does for
the n8n path, in ~100 lines: run each detector via its production entry point
(``detect_workflow`` for the structural/config detectors on the workflow JSON;
``detect`` on the runtime turns for the execution-lane detectors), collect the fires,
dedupe, and return a typed report. No DB, no FastAPI, no Redis — pure and sync.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pisama_n8n_engine.detect.structural import (
    N8NCycleDetector,
    N8NSchemaDetector,
    N8NResourceDetector,
    N8NTimeoutDetector,
    N8NErrorDetector,
    N8NComplexityDetector,
)
from pisama_n8n_engine.detect.runtime import (
    N8NErrorWorkflowDetector,
    N8NRetryRecoveryDetector,
    N8NTruncationDetector,
    N8NAgentDiagnosticsDetector,
)
from pisama_n8n_engine.trace.execution import execution_to_turns_and_metadata
from pisama_n8n_engine.trace.flatted import normalize_execution

TAXONOMY_VERSION = "1"
FAILURE_MODES = frozenset(
    {
        "F3",
        "F6",
        "F11",
        "F12",
        "F13",
        "F14",
        "F15",
        "n8n_agent_output_validation",
        "n8n_agent_tool_recovery",
        "n8n_credential",
        "n8n_data_contract",
        "n8n_error_workflow_missing_trigger",
        "n8n_error_workflow_target_missing",
        "n8n_expression",
        "n8n_missing_error_workflow",
        "n8n_native_agent_tool_recovery",
        "n8n_native_structured_parser_rejection",
        "n8n_node_error",
        "n8n_provider",
        "n8n_rate_limit",
        "n8n_retry_not_observed",
        "n8n_timeout",
        "n8n_truncation",
    }
)

# Detectors whose production semantic is static workflow-structure analysis.
_STRUCTURAL = {
    "cycle": N8NCycleDetector,
    "complexity": N8NComplexityDetector,
}
# Detectors whose production semantic is runtime-observed failure (need execution turns).
_EXECUTION = {
    "schema": N8NSchemaDetector,
    "timeout": N8NTimeoutDetector,
    "error": N8NErrorDetector,
    "resource": N8NResourceDetector,
    "truncation": N8NTruncationDetector,
    "retry_recovery": N8NRetryRecoveryDetector,
    "error_workflow": N8NErrorWorkflowDetector,
    "agent_diagnostics": N8NAgentDiagnosticsDetector,
}


@dataclass
class Detection:
    detector: str
    detected: bool
    confidence: float
    failure_mode: Optional[str]
    explanation: str = ""
    # Keep the detector's own semantic version with the result. A stored failure
    # fingerprint is only useful as evidence when its producing detector contract
    # can be identified later.
    detector_version: Optional[str] = None
    # Small detector-specific facts that support the verdict. The server persists
    # this locally so an operator can audit a finding without relying on prose.
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectionReport:
    workflow_id: Optional[str]
    detections: List[Detection] = field(default_factory=list)

    @property
    def fired(self) -> List[Detection]:
        return [d for d in self.detections if d.detected]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "detections": [d.__dict__ for d in self.detections],
        }


@dataclass
class ExecutionAnalysis:
    """A normalized execution and the pure detector report produced from it."""

    payload: Dict[str, Any]
    report: DetectionReport


def analyze(
    workflow_json: Optional[Dict[str, Any]] = None,
    turns: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    workflow_id: Optional[str] = None,
) -> DetectionReport:
    """Run the n8n detectors and aggregate their verdicts.

    Pass ``workflow_json`` for structural analysis and/or ``turns`` (parsed execution
    runData) for runtime-observed analysis. Each lane runs only when its input is present.
    """
    report = DetectionReport(workflow_id=workflow_id)
    metadata = metadata or {}

    if workflow_json is not None:
        for name, cls in _STRUCTURAL.items():
            detector = cls()
            try:
                r = detector.detect_workflow(workflow_json)
                report.detections.append(_to_detection(name, r, detector.version))
            except Exception as exc:  # a detector error must not sink the whole run
                report.detections.append(
                    Detection(
                        name,
                        False,
                        0.0,
                        None,
                        f"error: {exc}",
                        detector_version=detector.version,
                    )
                )

    if turns is not None:
        for name, cls in _EXECUTION.items():
            detector = cls()
            try:
                r = detector.detect(turns=turns, conversation_metadata=metadata)
                report.detections.append(_to_detection(name, r, detector.version))
            except Exception as exc:
                report.detections.append(
                    Detection(
                        name,
                        False,
                        0.0,
                        None,
                        f"error: {exc}",
                        detector_version=detector.version,
                    )
                )

    return report


def analyze_execution(payload: Any) -> ExecutionAnalysis:
    """Normalize one n8n execution and run every applicable detector lane.

    This is the shared side-effect-free seam for production ingestion, evaluation,
    and offline regression scoring. Persistence belongs to the caller.
    """
    normalized = normalize_execution(payload)
    if normalized is None:
        raise ValueError(
            "Unrecognized execution payload: expected an n8n execution export, a "
            "flatted execution-data array (DB dump), or a workflow JSON."
        )

    workflow_json = normalized.get("workflow") or normalized.get("workflowData")
    if workflow_json is None and (
        "nodes" in normalized or "connections" in normalized
    ):
        workflow_json = normalized

    workflow_id = normalized.get("workflowId")
    if isinstance(workflow_json, dict):
        workflow_id = workflow_id or workflow_json.get("id")

    data = normalized.get("data")
    run_data = (
        data.get("resultData", {}).get("runData") if isinstance(data, dict) else None
    )
    if workflow_json is None and not run_data:
        raise ValueError(
            "Unrecognized execution payload: no workflow definition or runtime "
            "runData was present."
        )

    report = DetectionReport(workflow_id=workflow_id)
    if workflow_json:
        report.detections.extend(
            analyze(workflow_json=workflow_json, workflow_id=workflow_id).detections
        )

    if run_data:
        turns, metadata = execution_to_turns_and_metadata(normalized)
        report.detections.extend(
            analyze(turns=turns, metadata=metadata, workflow_id=workflow_id).detections
        )

    return ExecutionAnalysis(payload=normalized, report=report)


def _to_detection(name: str, r: Any, detector_version: str) -> Detection:
    evidence = getattr(r, "evidence", {}) or {}
    return Detection(
        detector=name,
        detected=bool(getattr(r, "detected", False)),
        confidence=float(getattr(r, "confidence", 0.0) or 0.0),
        failure_mode=getattr(r, "failure_mode", None),
        explanation=getattr(r, "explanation", "") or "",
        detector_version=detector_version,
        evidence=evidence if isinstance(evidence, dict) else {},
    )
