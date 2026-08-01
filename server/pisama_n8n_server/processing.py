"""Shared execution processing for persistent ingestion and pure evaluation."""
from __future__ import annotations

from typing import Any, Dict, Optional

from pisama_n8n_engine import TAXONOMY_VERSION, ExecutionAnalysis, analyze_execution

EVALUATION_SCHEMA_VERSION = "1"


def confidence_tier(confidence: float) -> str:
    """Describe heuristic evidence strength without presenting it as probability."""
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"


def evaluation_response(
    analysis: ExecutionAnalysis,
    *,
    build_revision: str,
    engine_version: str,
) -> Dict[str, Any]:
    """Return the stable, multi-label response consumed by evaluation clients."""
    detections = [
        {**detection.__dict__, "confidence_tier": confidence_tier(detection.confidence)}
        for detection in analysis.report.detections
    ]
    fired_modes = sorted(
        {
            detection.failure_mode
            for detection in analysis.report.fired
            if detection.failure_mode
        }
    )
    return {
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "build_revision": build_revision,
        "engine_version": engine_version,
        "workflow_id": analysis.report.workflow_id,
        "fired_modes": fired_modes,
        "detections": detections,
    }


def process_execution(
    payload: Any,
    storage: Any,
    source_execution_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run both detection lanes on one execution, persist, and return the report dict.

    Accepts every shape executions arrive in from the wild: the plain API export, the
    flatted DB wire format (a JSON array — what a dump of n8n's execution_data column
    contains), and partially-dereferenced variants. Raises ValueError for a payload
    that decodes as none of them.
    """
    analysis = analyze_execution(payload)
    storage.save_report(
        analysis.payload,
        analysis.report,
        source_execution_id=source_execution_id,
    )
    return analysis.report.to_dict()
