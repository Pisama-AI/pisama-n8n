"""Broadcaster + background-poller wiring tests (real asyncio, no mocks)."""
import asyncio

import pytest

from pisama_n8n_server.events import Broadcaster, fired_event


@pytest.mark.asyncio
async def test_broadcaster_fans_out_to_subscribers():
    b = Broadcaster()
    q1 = b.subscribe()
    q2 = b.subscribe()
    await b.publish({"type": "detections", "count": 1})
    e1 = await asyncio.wait_for(q1.get(), timeout=1)
    e2 = await asyncio.wait_for(q2.get(), timeout=1)
    assert '"count": 1' in e1 and '"count": 1' in e2
    b.unsubscribe(q1)
    await b.publish({"type": "detections", "count": 2})
    assert q2.get_nowait()  # still subscribed
    assert q1.empty()       # unsubscribed → no new events


def test_fired_event_summarizes_only_fired():
    report = {
        "workflow_id": "wf1",
        "detections": [
            {"detector": "error", "detected": True},
            {"detector": "cycle", "detected": False},
        ],
    }
    ev = fired_event(report)
    assert ev == {"type": "detections", "workflow_id": "wf1", "fired": ["error"], "count": 1}


def test_background_poller_arms_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("PISAMA_N8N_URL", "http://127.0.0.1:5679")
    monkeypatch.setenv("PISAMA_N8N_API_KEY", "dummy")
    monkeypatch.setenv("PISAMA_POLL_INTERVAL", "30")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'bg.db'}")
    import pisama_n8n_server.app as appmod
    from fastapi.testclient import TestClient

    with TestClient(appmod.app):  # triggers startup
        assert appmod._poll_task is not None
    assert appmod._poll_task.cancelled()  # cancelled on shutdown
