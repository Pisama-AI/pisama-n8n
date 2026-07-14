"""In-process pub/sub for live detection events (SSE fan-out).

Single-process self-host: a set of per-subscriber asyncio queues. Ingestion handlers
publish after they store; the SSE endpoint drains one queue per connection. No Redis.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Set


class Broadcaster:
    def __init__(self) -> None:
        self._subscribers: Set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def publish(self, event: Dict[str, Any]) -> None:
        payload = json.dumps(event, default=str)
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # A slow client: drop the event for it rather than block everyone.
                pass


# Process-wide singleton.
broadcaster = Broadcaster()


def fired_event(report: Dict[str, Any]) -> Dict[str, Any]:
    """Shape a stored report into a lightweight live event."""
    fired = [d for d in report.get("detections", []) if d.get("detected")]
    return {
        "type": "detections",
        "workflow_id": report.get("workflow_id"),
        "fired": [d.get("detector") for d in fired],
        "count": len(fired),
    }
