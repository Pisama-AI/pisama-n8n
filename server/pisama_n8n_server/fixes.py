"""Paid-tier seam: request fixes from the Pisama cloud, apply them to the user's n8n.

The OSS/paid boundary lives here. Fix GENERATION is the closed, paid IP and runs in the
Pisama cloud (PISAMA_CLOUD_URL) — this module only *calls* it with a cloud key. Fix
APPLICATION is mechanical (PUT a returned workflow JSON) and stays OSS. The user's n8n
credentials never leave their network: the cloud sees the detection + workflow you send it,
and returns a mutated workflow; the server applies it locally.

Gating: without PISAMA_CLOUD_KEY every paid call returns 402 Payment Required.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

DEFAULT_CLOUD_URL = "https://api.pisama.ai"


class PaidTierNotConfigured(Exception):
    """Raised when a paid feature is used without a PISAMA_CLOUD_KEY (→ HTTP 402)."""


def _cloud_config() -> tuple[str, str]:
    key = os.environ.get("PISAMA_CLOUD_KEY")
    if not key:
        raise PaidTierNotConfigured(
            "Fix suggestions and auto-fix are a paid feature — set PISAMA_CLOUD_KEY."
        )
    return os.environ.get("PISAMA_CLOUD_URL", DEFAULT_CLOUD_URL).rstrip("/"), key


async def request_fix(detection: Dict[str, Any], workflow: Dict[str, Any]) -> Dict[str, Any]:
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


async def apply_fix(
    client: Any,
    workflow_id: str,
    mutated_workflow: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply a cloud-returned mutated workflow to the live n8n, snapshotting first so the
    caller can roll back. Mechanical (OSS) — the intelligence was the mutation, done in the
    cloud. Returns ``{snapshot, applied}``."""
    snapshot = await client.get_workflow(workflow_id)
    applied = await client.update_workflow(workflow_id, mutated_workflow)
    return {"snapshot": snapshot, "applied": applied}


async def rollback(client: Any, workflow_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Restore a previously-captured workflow snapshot."""
    return await client.update_workflow(workflow_id, snapshot)


def is_paid_configured() -> bool:
    return bool(os.environ.get("PISAMA_CLOUD_KEY"))
