"""Paid-tier seam: request fixes from the Pisama cloud, apply them to the user's n8n.

The self-host/paid boundary lives here. Fix GENERATION is the closed, paid IP and runs in the
Pisama cloud (PISAMA_CLOUD_URL) — this module only *calls* it with a cloud key. Fix
APPLICATION is mechanical (PUT a returned workflow JSON) and stays self-host. The user's n8n
credentials never leave their network: the cloud sees the detection + workflow you send it,
and returns a mutated workflow; the server applies it locally.

Gating: without PISAMA_CLOUD_KEY every paid call returns 402 Payment Required.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import httpx

DEFAULT_CLOUD_URL = "https://api.pisama.ai"


class PaidTierNotConfigured(Exception):
    """Raised when a paid feature is used without a PISAMA_CLOUD_KEY (→ HTTP 402)."""


class StaleRepairProposal(Exception):
    """The live n8n workflow changed after Pisama generated or applied a repair."""


class InvalidRepairProposal(Exception):
    """The cloud response cannot safely be applied as a workflow update."""


def _cloud_config() -> tuple[str, str]:
    key = os.environ.get("PISAMA_CLOUD_KEY")
    if not key:
        raise PaidTierNotConfigured(
            "Fix suggestions and auto-fix are a paid feature — set PISAMA_CLOUD_KEY."
        )
    return os.environ.get("PISAMA_CLOUD_URL", DEFAULT_CLOUD_URL).rstrip("/"), key


async def request_fix(
    detection: Dict[str, Any], workflow: Dict[str, Any]
) -> Dict[str, Any]:
    """Ask the cloud to generate a fix for one detection. Returns
    ``{explanation, patch_ops, mutated_workflow}`` — a read-only preview."""
    url, key = _cloud_config()
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(
            f"{url}/v1/n8n/fix",
            headers={"Authorization": f"Bearer {key}"},
            json={"detection": detection, "workflow": workflow},
        )
        r.raise_for_status()
        return r.json()


_MUTABLE_WORKFLOW_KEYS = ("name", "nodes", "connections", "settings")


def workflow_fingerprint(workflow: Dict[str, Any]) -> str:
    """Hash exactly the workflow fields n8n accepts on PUT.

    n8n adds read-only metadata to GET responses. Comparing only mutable fields avoids
    false stale conflicts while still refusing to overwrite a human workflow edit.
    """
    mutable = {key: workflow[key] for key in _MUTABLE_WORKFLOW_KEYS if key in workflow}
    return json.dumps(
        mutable, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


async def prepare_apply(
    client: Any,
    workflow_id: str,
    baseline_workflow: Dict[str, Any],
    mutated_workflow: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate a proposal against the live workflow and return the restore snapshot.

    Performs NO mutation: every failure path here (invalid or stale proposal, or an n8n
    read error) raises before anything is written, so the live workflow is untouched.
    """
    if workflow_fingerprint(baseline_workflow) == workflow_fingerprint(
        mutated_workflow
    ):
        raise InvalidRepairProposal("Fix proposal does not change the n8n workflow.")
    snapshot = await client.get_workflow(workflow_id)
    if workflow_fingerprint(snapshot) != workflow_fingerprint(baseline_workflow):
        raise StaleRepairProposal(
            "The n8n workflow changed after this fix was generated. Review and generate a new fix."
        )
    return snapshot


async def commit_apply(
    client: Any, workflow_id: str, mutated_workflow: Dict[str, Any]
) -> Dict[str, Any]:
    """Write the mutated workflow to the live n8n instance — the point of no return.

    The caller MUST have durably persisted the restore snapshot (from ``prepare_apply``)
    before invoking this, so an interrupted apply stays rollback-eligible.
    """
    return await client.update_workflow(workflow_id, mutated_workflow)


async def apply_fix(
    client: Any,
    workflow_id: str,
    baseline_workflow: Dict[str, Any],
    mutated_workflow: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate then apply in one step. Prefer ``prepare_apply`` + ``commit_apply`` when
    you must persist the restore point BEFORE mutating the live workflow."""
    snapshot = await prepare_apply(
        client, workflow_id, baseline_workflow, mutated_workflow
    )
    applied = await commit_apply(client, workflow_id, mutated_workflow)
    return {"snapshot": snapshot, "applied_workflow": applied}


async def rollback(
    client: Any,
    workflow_id: str,
    snapshot: Dict[str, Any],
    applied_workflow: Dict[str, Any],
) -> Dict[str, Any]:
    """Restore a snapshot only if no one edited the workflow after Pisama applied it."""
    current = await client.get_workflow(workflow_id)
    if workflow_fingerprint(current) != workflow_fingerprint(applied_workflow):
        raise StaleRepairProposal(
            "The n8n workflow changed after Pisama applied this fix. Rollback would overwrite that edit."
        )
    return await client.update_workflow(workflow_id, snapshot)


def is_paid_configured() -> bool:
    return bool(os.environ.get("PISAMA_CLOUD_KEY"))
