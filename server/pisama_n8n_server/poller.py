"""API-polling ingestion channel: pull recent executions from the user's n8n and detect.

The zero-setup channel — no workflow edits, no community node. The server periodically (or
on demand via POST /api/v1/n8n/sync) lists the user's recent executions and runs any it
hasn't seen through the engine, deduping on the upstream n8n execution id.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

import httpx

from pisama_n8n_server.processing import process_execution
from pisama_n8n_server.storage import DuplicateSourceExecution

logger = logging.getLogger("pisama_n8n_server")


async def _with_workflow_context(
    execution: Dict[str, Any], client: Any
) -> Dict[str, Any]:
    """Attach the workflow n8n omits from execution-list responses when available."""
    workflow_id = execution.get("workflowId")
    if not workflow_id or execution.get("workflow") or execution.get("workflowData"):
        return execution
    try:
        return {**execution, "workflow": await client.get_workflow(str(workflow_id))}
    except Exception as exc:  # Runtime detection can still proceed without it.
        logger.warning("poll: failed to fetch workflow %s: %s", workflow_id, exc)
        return execution


def _error_workflow_id(execution: Dict[str, Any]) -> str | None:
    """Return an explicitly configured n8n error-workflow id, if present."""
    workflow = execution.get("workflow") or execution.get("workflowData") or {}
    settings = workflow.get("settings") if isinstance(workflow, dict) else None
    value = settings.get("errorWorkflow") if isinstance(settings, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _failed_execution(execution: Dict[str, Any]) -> bool:
    """Only resolve an error route when n8n recorded an actual failed execution."""
    status = str(execution.get("status") or "").lower()
    result_data = (execution.get("data") or {}).get("resultData") or {}
    return (
        status in {"error", "crashed", "failed"}
        or execution.get("finished") is False
        or bool(result_data.get("error"))
    )


async def _with_error_workflow_context(
    execution: Dict[str, Any], client: Any
) -> Dict[str, Any]:
    """Attach a configured error workflow only when its source execution failed.

    A configured workflow id alone is not proof that n8n can route incidents there.
    The runtime detector validates the fetched target's Error Trigger node. A 404 is
    conclusive evidence that the configured route is broken. Other lookup failures
    remain explicitly unverifiable rather than being guessed at.
    """
    error_workflow_id = _error_workflow_id(execution)
    if not error_workflow_id or not _failed_execution(execution):
        return execution
    try:
        error_workflow = await client.get_workflow(error_workflow_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {
                **execution,
                "pisama_error_workflow_resolution": {
                    "id": error_workflow_id,
                    "status": "missing",
                },
            }
        logger.warning(
            "poll: failed to fetch error workflow %s: HTTP %s",
            error_workflow_id,
            exc.response.status_code,
        )
        return {
            **execution,
            "pisama_error_workflow_resolution": {
                "id": error_workflow_id,
                "status": "unverifiable",
            },
        }
    except Exception as exc:  # Keep the source failure analyzable without a guess.
        logger.warning(
            "poll: failed to fetch error workflow %s: %s", error_workflow_id, exc
        )
        return {
            **execution,
            "pisama_error_workflow_resolution": {
                "id": error_workflow_id,
                "status": "unverifiable",
            },
        }
    return {
        **execution,
        "pisama_error_workflow": error_workflow,
        "pisama_error_workflow_resolution": {
            "id": error_workflow_id,
            "status": "available",
        },
    }


async def poll_once(client: Any, storage: Any, limit: int = 50) -> Dict[str, int]:
    """Fetch recent executions, ingest the new ones, return a summary.

    ``PISAMA_N8N_PROJECT_ID`` makes polling project-scoped. In that mode Pisama first
    resolves only that project's workflow IDs, then asks n8n for executions per
    workflow. This is important for Cloud dogfooding because API-key scopes do not
    themselves constrain the key to a project.
    """
    project_id = os.environ.get("PISAMA_N8N_PROJECT_ID")
    if project_id:
        workflows = await client.list_workflows(project_id=project_id)
        workflow_ids = [
            str(workflow["id"]) for workflow in workflows if workflow.get("id")
        ]
        executions = []
        for workflow_id in workflow_ids:
            executions.extend(
                await client.list_executions(
                    limit=limit, include_data=True, workflow_id=workflow_id
                )
            )
    else:
        executions = await client.list_executions(limit=limit, include_data=True)
    if executions and len(executions) >= limit:
        # n8n returns newest-first with no cursor here: a full window means older
        # executions may have rolled past between polls and were never seen.
        logger.warning(
            "poll: fetched a full window of %d executions — a high-volume instance "
            "can outrun the polling window and miss executions. Use the "
            "n8n-nodes-pisama push channel for instances this busy.",
            limit,
        )
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
        ex = await _with_error_workflow_context(ex, client)
        try:
            report = process_execution(ex, storage, source_execution_id=exid)
        except DuplicateSourceExecution:
            # Lost a race with a concurrent poll/sync over the same execution; the
            # winner stored it. Correct outcome, not a failure — and not "new".
            continue
        except Exception as exc:  # one bad execution must not sink the whole poll
            logger.warning("poll: failed to process execution %s: %s", exid, exc)
            continue
        new += 1
        fired += sum(1 for d in report.get("detections", []) if d.get("detected"))

    drifted = await _sweep_guard_drift(client, storage)
    summary = {"polled": len(executions), "new": new, "fired": fired, "drifted": drifted}
    logger.info("poll_once: %s", summary)
    return summary


async def _sweep_guard_drift(client: Any, storage: Any) -> int:
    """Assert every applied guard is still present AND still wired in the live workflow.

    Without this, the apply-time checks are the ONLY drift detection there is — and they
    run only when an operator clicks something. A guard deleted or bypassed in the n8n
    editor would otherwise keep reading as "applied / prevented" indefinitely.

    Read-only against n8n (``get_workflow`` and nothing else) and wholly non-fatal: a
    drift sweep must never break ingestion.
    """
    from pisama_n8n_engine.guardrails import assert_guard_still_wired

    drifted = 0
    try:
        repairs = storage.list_applied_guardrail_repairs()
    except Exception as exc:
        logger.warning("poll: could not list applied guards: %s", exc)
        return 0

    memo: Dict[str, Any] = {}
    for repair in repairs:
        workflow_id = str(repair.get("workflow_id") or "")
        guard_config = repair.get("guard_config") or {}
        if not workflow_id or not guard_config:
            continue
        try:
            if workflow_id not in memo:
                memo[workflow_id] = await client.get_workflow(workflow_id)
            live = memo[workflow_id]
            if not isinstance(live, dict):
                continue  # unreadable this cycle; absence of proof is not drift
            drifts = assert_guard_still_wired(live, guard_config)
        except Exception as exc:
            # An unreachable n8n is not evidence that a guard was removed.
            logger.warning(
                "poll: guard drift check failed for workflow %s: %s", workflow_id, exc
            )
            continue
        if not drifts:
            continue
        # Report the most severe single finding: a bypass means input can reach the
        # consumer unguarded, which is worse than a broken rejection path.
        order = ["guard_bypassed", "guard_deleted", "guard_detached", "rejection_path_broken"]
        drifts.sort(key=lambda d: order.index(d["kind"]) if d["kind"] in order else len(order))
        worst = drifts[0]
        if storage.record_guard_drift(repair["id"], worst["kind"], worst["detail"]) is None:
            continue  # no case, or already recorded with this kind
        drifted += 1
        logger.warning(
            "poll: guard drift %s on workflow %s: %s",
            worst["kind"],
            workflow_id,
            worst["detail"],
        )
    return drifted
