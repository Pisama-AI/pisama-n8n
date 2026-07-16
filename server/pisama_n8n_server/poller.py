"""API-polling ingestion channel: pull recent executions from the user's n8n and detect.

The zero-setup channel — no workflow edits, no community node. The server periodically (or
on demand via POST /api/v1/n8n/sync) lists the user's recent executions and runs any it
hasn't seen through the engine, deduping on the upstream n8n execution id.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from pisama_n8n_server.processing import process_execution

logger = logging.getLogger("pisama_n8n_server")


async def _with_workflow_context(execution: Dict[str, Any], client: Any) -> Dict[str, Any]:
    """Attach the workflow n8n omits from execution-list responses when available."""
    workflow_id = execution.get("workflowId")
    if not workflow_id or execution.get("workflow") or execution.get("workflowData"):
        return execution
    try:
        return {**execution, "workflow": await client.get_workflow(str(workflow_id))}
    except Exception as exc:  # Runtime detection can still proceed without it.
        logger.warning("poll: failed to fetch workflow %s: %s", workflow_id, exc)
        return execution


async def poll_once(client: Any, storage: Any, limit: int = 50) -> Dict[str, int]:
    """Fetch recent executions, ingest the new ones, return a summary."""
    executions = await client.list_executions(limit=limit, include_data=True)
    seen = storage.seen_source_ids()

    new = fired = 0
    for ex in executions:
        exid = ex.get("id")
        if exid is None:
            continue
        exid = str(exid)
        if exid in seen:
            continue
        # n8n execution lists omit the workflow definition. Restore the real node
        # context before analysis so runtime findings remain actionable.
        ex = await _with_workflow_context(ex, client)
        try:
            report = process_execution(ex, storage, source_execution_id=exid)
        except Exception as exc:  # one bad execution must not sink the whole poll
            logger.warning("poll: failed to process execution %s: %s", exid, exc)
            continue
        new += 1
        fired += sum(1 for d in report.get("detections", []) if d.get("detected"))

    summary = {"polled": len(executions), "new": new, "fired": fired}
    logger.info("poll_once: %s", summary)
    return summary
