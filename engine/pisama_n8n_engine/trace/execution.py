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

        for run in node_runs:
            execution_time_ms = run.get("executionTime", 0)
            execution_status = run.get("executionStatus", "unknown")
            error_info = run.get("error")
            output_data = run.get("data", {}).get("main", [[]])[0] if run.get("data") else []

            content_parts = [f"Node: {node_name} (type: {node_type})"]
            if output_data:
                try:
                    content_parts.append(json.dumps(output_data, default=str))
                except (TypeError, ValueError):
                    content_parts.append(str(output_data))
            if error_info:
                msg = error_info.get("message", "") if isinstance(error_info, dict) else str(error_info)
                content_parts.append(f"ERROR: {msg}")

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
                    "has_error": error_info is not None,
                    "continue_on_fail": node_params.get("onError") == "continueErrorOutput",
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
    }
    return turns, metadata
