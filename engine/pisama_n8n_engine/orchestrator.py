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
    N8NAgentDiagnosticsDetector,
    N8NErrorWorkflowDetector,
    N8NIdempotencyDetector,
    N8NRetryRecoveryDetector,
    N8NTruncationDetector,
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
    "idempotency": N8NIdempotencyDetector,
    "agent_diagnostics": N8NAgentDiagnosticsDetector,
}


@dataclass
class Detection:
    detector: str
    detected: bool
    confidence: float
    failure_mode: Optional[str]
    explanation: str = ""


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
            try:
                r = cls().detect_workflow(workflow_json)
                report.detections.append(_to_detection(name, r))
            except Exception as exc:  # a detector error must not sink the whole run
                report.detections.append(Detection(name, False, 0.0, None, f"error: {exc}"))

    if turns is not None:
        for name, cls in _EXECUTION.items():
            try:
                r = cls().detect(turns=turns, conversation_metadata=metadata)
                report.detections.append(_to_detection(name, r))
            except Exception as exc:
                report.detections.append(Detection(name, False, 0.0, None, f"error: {exc}"))

    return report


def _to_detection(name: str, r: Any) -> Detection:
    return Detection(
        detector=name,
        detected=bool(getattr(r, "detected", False)),
        confidence=float(getattr(r, "confidence", 0.0) or 0.0),
        failure_mode=getattr(r, "failure_mode", None),
        explanation=getattr(r, "explanation", "") or "",
    )
