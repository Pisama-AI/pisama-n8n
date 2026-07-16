"""Turn a captured n8n execution into the runtime turns the execution-lane detectors read.

The public n8n `/executions?includeData=true` API (and the community node) return nested
`data.resultData.runData`. This converts that into ``TurnSnapshot``s carrying the real
per-node timing / error / output the timeout/error/resource detectors consume. Ported
verbatim from the calibrated eval harness (proven: timeout node execTime, real error
status, output size all reach the detectors).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from pisama_n8n_engine.detect.base import TurnSnapshot


def _swallowed_error(run: Dict[str, Any], on_error: str) -> Any:
    """Return the error message of a continue-on-fail node that silently failed, else None.

    n8n never records these as ``run['error']``; the failure is only observable by how the
    node routed its output, so this is gated on the node's ``onError`` mode:

    - ``continueErrorOutput`` — the errored items are routed to the SECOND main output
      branch (``data.main[1]``); a non-empty error branch means the node failed.
    - ``continueRegularOutput`` (legacy ``continueOnFail: true``) — the errored item flows
      through the regular output carrying a truthy ``error`` key in its json.
    """
    data = run.get("data") or {}
    main = data.get("main") or []

    if on_error == "continueErrorOutput":
        if len(main) > 1 and main[1]:
            first = main[1][0] if isinstance(main[1], list) and main[1] else None
            j = first.get("json") if isinstance(first, dict) else None
            msg = (j.get("error") or j.get("message")) if isinstance(j, dict) else None
            return msg if isinstance(msg, str) and msg.strip() else "node routed items to its error output"
        return None

    if on_error == "continueRegularOutput":
        for item in (main[0] if main else []) or []:
            j = item.get("json") if isinstance(item, dict) else None
            if isinstance(j, dict):
                err = j.get("error")
                if isinstance(err, str) and err.strip():
                    return err
    return None


def execution_to_turns(execution_data: Dict[str, Any]) -> List[TurnSnapshot]:
    """Build the per-node runtime turns from a captured execution's runData."""
    turns: List[TurnSnapshot] = []

    workflow = execution_data.get("workflow") or execution_data.get("workflowData") or {}
    wf_nodes = workflow.get("nodes", [])
    node_defs = {n.get("name"): n for n in wf_nodes if isinstance(n, dict) and n.get("name")}

    started_at = None
    started_at_str = execution_data.get("startedAt")
    if started_at_str:
        try:
            started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    run_data = execution_data.get("data", {}).get("resultData", {}).get("runData", {})
    seq = 0
    base_time = started_at or datetime.now()

    for node_name, node_runs in run_data.items():
        if not node_runs:
            continue
        ndef = node_defs.get(node_name, {})
        node_type = ndef.get("type", "unknown")
        node_params = ndef.get("parameters", {})

        # n8n stores continue-on-fail config at the NODE level (`onError`), not under
        # `parameters`. Older/exported workflows use `settings.continueOnFail` or a
        # top-level `continueOnFail` bool. Read all three so real polled data — where
        # `onError` is a sibling of `parameters` — is read faithfully.
        node_settings = ndef.get("settings") or {}
        on_error = (ndef.get("onError") or node_params.get("onError") or "")
        continue_on_fail = on_error in ("continueErrorOutput", "continueRegularOutput") or bool(
            node_settings.get("continueOnFail") or ndef.get("continueOnFail")
        )

        for run in node_runs:
            execution_time_ms = run.get("executionTime", 0)
            execution_status = run.get("executionStatus", "unknown")
            error_info = run.get("error")
            output_data = run.get("data", {}).get("main", [[]])[0] if run.get("data") else []

            # A node with continue-on-fail that actually failed leaves NO `run.error` and
            # keeps `executionStatus="success"` — the failure is only visible as the error
            # branch carrying items (continueErrorOutput) or an `error` key inside the
            # regular output item (continueRegularOutput). Surface that swallowed failure
            # so the error detector can see it. Gated on the node's own `onError` config,
            # so a healthy node whose data merely contains a field named "error" is unaffected.
            swallowed = None if error_info else _swallowed_error(run, on_error)

            content_parts = [f"Node: {node_name} (type: {node_type})"]
            if output_data:
                try:
                    content_parts.append(json.dumps(output_data, default=str))
                except (TypeError, ValueError):
                    content_parts.append(str(output_data))
            if error_info:
                msg = error_info.get("message", "") if isinstance(error_info, dict) else str(error_info)
                content_parts.append(f"ERROR: {msg}")
            elif swallowed:
                content_parts.append(f"ERROR (continue-on-fail, swallowed): {swallowed}")

            start_time = run.get("startTime")
            if start_time:
                try:
                    timestamp = datetime.fromtimestamp(start_time / 1000)
                except (ValueError, TypeError, OSError):
                    timestamp = base_time + timedelta(milliseconds=seq * 1000)
            else:
                timestamp = base_time + timedelta(milliseconds=seq * 1000)

            turns.append(TurnSnapshot(
                turn_number=seq,
                participant_type="node",
                participant_id=node_name,
                content="\n".join(content_parts),
                turn_metadata={
                    "node_type": node_type,
                    "timestamp": timestamp.isoformat(),
                    "execution_time_ms": execution_time_ms,
                    "parameters": node_params,
                    "status": execution_status,
                    "has_error": error_info is not None or swallowed is not None,
                    "continue_on_fail": continue_on_fail,
                },
            ))
            seq += 1

    return turns


def execution_to_turns_and_metadata(
    execution_data: Dict[str, Any],
) -> Tuple[List[TurnSnapshot], Dict[str, Any]]:
    """Turns plus the workflow-level metadata the timeout detector reads."""
    turns = execution_to_turns(execution_data)
    metadata = {
        "workflow_id": execution_data.get("workflowId"),
        "workflow_duration_ms": sum(
            t.turn_metadata.get("execution_time_ms", 0) for t in turns
        ),
        "workflow_mode": execution_data.get("mode", "manual"),
        # The error detector distinguishes a HIDDEN failure (workflow marked successful
        # yet a node errored) from a visible failure. Without the real execution status
        # it defaulted to "success" and flagged every visibly-failed workflow as a
        # hidden "success-despite-failure" — a false positive on real error executions.
        "workflow_status": _workflow_status(execution_data),
    }
    return turns, metadata


def _workflow_status(execution_data: Dict[str, Any]) -> str:
    """Resolve the workflow-level status honestly.

    The n8n public executions API returns ``status`` on some versions/paths but leaves
    it ``None`` for others (notably manually-run and polled executions). Fall back to the
    ground truth n8n always records: ``finished`` and a top-level ``resultData.error``. A
    run that did not finish, or that carries a top-level error, is an error; otherwise it
    succeeded. Without this the error detector saw ``status=None`` and could not tell a
    visible failure from a healthy run on real polled data.
    """
    status = execution_data.get("status")
    if status:
        return status
    top_error = ((execution_data.get("data") or {}).get("resultData") or {}).get("error")
    if execution_data.get("finished") is False or top_error:
        return "error"
    return "success"
