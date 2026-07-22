"""Tool declarations for the Pisama-for-n8n MCP server.

Kept separate from the runtime so tests can pin the tool surface (names, schemas,
annotations) without constructing a client. The surface is READ + PROPOSE only:
apply/rollback/outcome/verification are operator actions in the dashboard and are
deliberately absent — a propose tool creates a repair-proposal row and never writes
to live n8n.
"""
from __future__ import annotations

from typing import Any, Dict, List

from mcp.types import Tool, ToolAnnotations

_READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)
# Proposes create/update proposal rows server-side (not idempotent: re-proposing
# makes a new row) but never touch the live n8n instance.
_PROPOSE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
)

_APPLY_NOTE = " Applying is done by an operator in the Pisama dashboard, not via MCP."


def _obj(properties: Dict[str, Any], required: List[str] | None = None) -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


_DETECTION_ID = {"type": "integer", "minimum": 1, "description": "Detection id."}
_REPAIR_ID = {"type": "integer", "minimum": 1, "description": "Repair (proposal) id."}


TOOLS: List[Tool] = [
    # -- reads ---------------------------------------------------------------
    Tool(
        name="pisama_n8n_list_detections",
        description=(
            "List failure detections recorded by this Pisama-for-n8n server, newest "
            "first. Each row has id, detector, failure_mode, confidence, workflow "
            "name/id, and ingest time. Use this to find a detection id before "
            "fetching detail, a trace, or proposing a repair."
        ),
        inputSchema=_obj(
            {
                "detector": {
                    "type": "string",
                    "description": "Only detections from this detector (e.g. 'schema', 'error').",
                },
                "failure_mode": {
                    "type": "string",
                    "description": "Only this failure mode (e.g. 'n8n_data_contract').",
                },
                "workflow_id": {
                    "type": "string",
                    "description": "Only detections for this n8n workflow id.",
                },
                "detected_only": {
                    "type": "boolean",
                    "description": "Only rows where the detector fired (default true).",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            }
        ),
        annotations=_READ,
    ),
    Tool(
        name="pisama_n8n_get_detection",
        description=(
            "Full detail for one detection: explanation, evidence, operator feedback, "
            "and any linked reliability case. Use after list_detections to understand "
            "a specific failure."
        ),
        inputSchema=_obj({"detection_id": _DETECTION_ID}, ["detection_id"]),
        annotations=_READ,
    ),
    Tool(
        name="pisama_n8n_get_detection_trace",
        description=(
            "Per-node execution trace behind a detection: which n8n node ran, status, "
            "timing, item counts, and errors. The node list is truncated to max_nodes "
            "(error nodes and the last node are always kept). Use to see where in the "
            "workflow the failure happened."
        ),
        inputSchema=_obj(
            {
                "detection_id": _DETECTION_ID,
                "max_nodes": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            ["detection_id"],
        ),
        annotations=_READ,
    ),
    Tool(
        name="pisama_n8n_operations_summary",
        description=(
            "Operational health of this Pisama server: execution/detection counts, "
            "detections by detector, repair and reliability-case status counts, and "
            "reliability metrics. Use for a status overview before drilling into "
            "detections."
        ),
        inputSchema=_obj({}),
        annotations=_READ,
    ),
    Tool(
        name="pisama_n8n_list_reliability_cases",
        description=(
            "List repair-verification cases, newest first: each tracks whether an "
            "applied repair actually prevented recurrence (statuses include "
            "'observing', 'recurred', 'rolled_back', 'drifted'; concluded cases carry "
            "an outcome). Read-only evidence; outcomes are recorded by operators, not "
            "via MCP."
        ),
        inputSchema=_obj(
            {
                "status": {
                    "type": "string",
                    "description": "Only cases with this status (e.g. 'observing').",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            }
        ),
        annotations=_READ,
    ),
    Tool(
        name="pisama_n8n_list_error_route_targets",
        description=(
            "For an error-route repair proposal, list the n8n instance's workflows as "
            "candidate error-handler targets, each marked eligible (has an Error "
            "Trigger) or not, with the reason and active flag. Call after "
            "propose_error_route, then pass a chosen id to choose_error_route_target."
        ),
        inputSchema=_obj({"repair_id": _REPAIR_ID}, ["repair_id"]),
        annotations=_READ,
    ),
    # -- proposes ------------------------------------------------------------
    Tool(
        name="pisama_n8n_propose_guardrail",
        description=(
            "Propose a deterministic input-schema guardrail for an n8n_data_contract "
            "detection. Creates a repair-proposal row (nothing is written to n8n). "
            "Returns the repair id, the evidence-derived path options (confirmed + "
            "candidates), and the available rejection destinations. Next step: "
            "choose_guardrail_destination." + _APPLY_NOTE
        ),
        inputSchema=_obj(
            {
                "detection_id": _DETECTION_ID,
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 20,
                    "description": (
                        "Required input paths for the guard. Must be a subset of the "
                        "evidence-derived options; the server rejects invented paths."
                    ),
                },
            },
            ["detection_id"],
        ),
        annotations=_PROPOSE,
    ),
    Tool(
        name="pisama_n8n_choose_guardrail_destination",
        description=(
            "Record the rejection destination for a proposed guardrail and build the "
            "guarded workflow server-side. Only valid while the repair is still "
            "'proposed'. Still does not touch live n8n." + _APPLY_NOTE
        ),
        inputSchema=_obj(
            {
                "repair_id": _REPAIR_ID,
                "destination": {
                    "type": "string",
                    "enum": ["error_workflow", "alert", "respond_422"],
                },
                "alert_url": {
                    "type": "string",
                    "description": "Webhook URL; required when destination is 'alert'.",
                },
            },
            ["repair_id", "destination"],
        ),
        annotations=_PROPOSE,
    ),
    Tool(
        name="pisama_n8n_propose_error_route",
        description=(
            "Propose an error-route repair for a broken-error-workflow detection "
            "(missing, un-triggered, or absent error workflow): re-points "
            "settings.errorWorkflow at a target the operator picks. Creates a "
            "proposal row only. Next step: list_error_route_targets, then "
            "choose_error_route_target." + _APPLY_NOTE
        ),
        inputSchema=_obj({"detection_id": _DETECTION_ID}, ["detection_id"]),
        annotations=_PROPOSE,
    ),
    Tool(
        name="pisama_n8n_choose_error_route_target",
        description=(
            "Set the target error workflow for an error-route proposal. The server "
            "verifies against live n8n that the target exists and has an Error "
            "Trigger." + _APPLY_NOTE
        ),
        inputSchema=_obj(
            {
                "repair_id": _REPAIR_ID,
                "target_workflow_id": {
                    "type": "string",
                    "description": "n8n workflow id of the error handler to route to.",
                },
            },
            ["repair_id", "target_workflow_id"],
        ),
        annotations=_PROPOSE,
    ),
]
