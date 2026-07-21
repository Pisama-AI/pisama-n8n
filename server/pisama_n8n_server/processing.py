"""Shared execution → detection processing, used by BOTH ingestion paths (the webhook
push and the API poller) so they detect identically."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from pisama_n8n_engine.orchestrator import DetectionReport, analyze
from pisama_n8n_engine.trace.execution import execution_to_turns_and_metadata
from pisama_n8n_engine.trace.flatted import normalize_execution


def extract_workflow_and_runtime(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Pull the workflow JSON and whether runData is present from an execution payload.

    A full execution carries the workflow under ``workflow``/``workflowData`` plus
    ``data.resultData.runData``. A bare workflow POST IS the workflow (``nodes``/
    ``connections``).
    """
    workflow_json = payload.get("workflow") or payload.get("workflowData")
    if workflow_json is None and ("nodes" in payload or "connections" in payload):
        workflow_json = payload
    data = payload.get("data")
    run_data = (
        data.get("resultData", {}).get("runData") if isinstance(data, dict) else None
    )
    return workflow_json, bool(run_data)


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
    normalized = normalize_execution(payload)
    if normalized is None:
        raise ValueError(
            "Unrecognized execution payload: expected an n8n execution export, a "
            "flatted execution-data array (DB dump), or a workflow JSON."
        )
    payload = normalized
    workflow_json, has_runtime = extract_workflow_and_runtime(payload)

    workflow_id = payload.get("workflowId")
    if workflow_json and isinstance(workflow_json, dict):
        workflow_id = workflow_id or workflow_json.get("id")

    report = DetectionReport(workflow_id=workflow_id)
    if workflow_json:
        report.detections.extend(
            analyze(workflow_json=workflow_json, workflow_id=workflow_id).detections
        )
    if has_runtime:
        turns, metadata = execution_to_turns_and_metadata(payload)
        report.detections.extend(
            analyze(turns=turns, metadata=metadata, workflow_id=workflow_id).detections
        )

    storage.save_report(payload, report, source_execution_id=source_execution_id)
    return report.to_dict()
