"""Minimal n8n public-API client for the polling ingestion channel.

The self-host server polls the user's own n8n instance for recent executions and runs
them through the detection engine — no workflow edits required (the zero-setup channel).
Only the read surface is needed here: list executions with their runData.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx


class N8nClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=f"{self.base_url}/api/v1",
            headers={"X-N8N-API-KEY": api_key},
            timeout=timeout,
        )

    async def test_connection(self) -> bool:
        r = await self._client.get("/workflows", params={"limit": 1})
        return r.status_code == 200

    async def list_executions(
        self, limit: int = 50, include_data: bool = True
    ) -> List[Dict[str, Any]]:
        """Most-recent executions first, with full runData by default (the detectors
        need it — without includeData the API omits runData and detection is blind)."""
        params: Dict[str, Any] = {"limit": limit}
        if include_data:
            params["includeData"] = "true"
        r = await self._client.get("/executions", params=params)
        r.raise_for_status()
        return r.json().get("data", [])

    async def aclose(self) -> None:
        await self._client.aclose()


def client_from_env(env: Optional[Dict[str, str]] = None) -> Optional[N8nClient]:
    """Build a client from PISAMA_N8N_URL + PISAMA_N8N_API_KEY, or None if unset."""
    import os

    env = env or dict(os.environ)
    url = env.get("PISAMA_N8N_URL")
    key = env.get("PISAMA_N8N_API_KEY")
    if not url or not key:
        return None
    return N8nClient(url, key)
