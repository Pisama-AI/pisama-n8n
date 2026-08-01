"""Shared execution processing for persistent ingestion and pure evaluation."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

from pisama_n8n_engine import TAXONOMY_VERSION, ExecutionAnalysis, analyze_execution

from pisama_n8n_server.storage import (
    DuplicateEvaluationIngest,
    execution_payload_sha256,
    redact_execution_payload,
)

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


def evaluation_ingest_key(dataset_id: str, case_id: str) -> str:
    """Return a non-reversible stable identity for one dataset case."""
    canonical = json.dumps([dataset_id, case_id], separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def process_evaluation_ingest(
    payload: Any,
    storage: Any,
    dataset_id: str,
    case_id: str,
) -> Dict[str, Any]:
    """Retain one evaluation case exactly once and reject identity drift."""
    analysis = analyze_execution(payload)
    ingest_key = evaluation_ingest_key(dataset_id, case_id)
    safe_payload = redact_execution_payload(analysis.payload)
    raw = json.dumps(safe_payload, sort_keys=True, separators=(",", ":"), default=str)
    payload_sha256 = execution_payload_sha256(raw)
    deduplicated = False
    try:
        storage.save_report(
            analysis.payload,
            analysis.report,
            evaluation_ingest_key=ingest_key,
            evaluation_payload_sha256=payload_sha256,
        )
    except DuplicateEvaluationIngest as exc:
        if exc.existing_payload_sha256 != payload_sha256:
            raise
        deduplicated = True
    result = storage.evaluation_ingest_result(ingest_key)
    if result is None:
        raise RuntimeError("evaluation ingest was not durably retained")
    return {
        "dataset_id": dataset_id,
        "case_id": case_id,
        "ingest_key": ingest_key,
        "deduplicated": deduplicated,
        **result,
    }
