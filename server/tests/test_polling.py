"""Live e2e for the API-polling ingestion channel — real n8n, no mocks.

Gated on PISAMA_HARNESS_N8N=1 + a reachable n8n at PISAMA_TEST_N8N_URL (default
http://127.0.0.1:5679, the docker-compose.healing-harness.yml instance), because it
provisions a key, creates + runs a real failing workflow, then polls it back. Skipped by
default so the normal test run needs no docker.
"""
import os
import time
import uuid

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PISAMA_HARNESS_N8N") != "1",
    reason="set PISAMA_HARNESS_N8N=1 with a live n8n to run the polling e2e",
)

N8N_URL = os.environ.get("PISAMA_TEST_N8N_URL", "http://127.0.0.1:5679")
OWNER = ("harness@pisama.test", "PisamaHarness123!")


def _provision_key() -> str:
    with httpx.Client(base_url=N8N_URL, timeout=30) as c:
        c.post("/rest/owner/setup", json={
            "email": OWNER[0], "firstName": "P", "lastName": "H", "password": OWNER[1]})
        c.post("/rest/login", json={"emailOrLdapLoginId": OWNER[0], "password": OWNER[1]})
        tok = c.cookies.get("n8n-auth")
        h = {"Cookie": f"n8n-auth={tok}"}
        sc = c.get("/rest/api-keys/scopes", headers=h).json().get("data", [])
        scopes = [s for s in sc if s.startswith(("workflow:", "execution:"))]
        r = c.post("/rest/api-keys", json={
            "label": f"poll-test-{int(time.time())}",
            "expiresAt": int(time.time()) + 3600, "scopes": scopes}, headers=h)
        return r.json()["data"]["rawApiKey"]


def _run_failing_workflow(key: str) -> str:
    path = f"polltest-{uuid.uuid4().hex[:8]}"
    wf = {"name": f"poll-{path}", "settings": {}, "nodes": [
        {"id": "w", "name": "Webhook", "type": "n8n-nodes-base.webhook", "typeVersion": 2,
         "position": [0, 0], "parameters": {"path": path, "httpMethod": "POST",
         "responseMode": "lastNode"}, "webhookId": path},
        {"id": "c", "name": "Boom", "type": "n8n-nodes-base.code", "typeVersion": 2,
         "position": [220, 0], "parameters": {"jsCode": "throw new Error('poll test');"}}],
        "connections": {"Webhook": {"main": [[{"node": "Boom", "type": "main", "index": 0}]]}}}
    h = {"X-N8N-API-KEY": key}
    with httpx.Client(base_url=N8N_URL + "/api/v1", headers=h, timeout=30) as c:
        body = c.post("/workflows", json=wf).json()
        wid = (body.get("data", body))["id"]
        c.post(f"/workflows/{wid}/activate")
    httpx.post(f"{N8N_URL}/webhook/{path}", json={}, timeout=15)
    time.sleep(2)
    return wid


def test_poll_ingests_and_dedups(tmp_path, monkeypatch):
    key = _provision_key()
    wid = _run_failing_workflow(key)
    try:
        monkeypatch.setenv("PISAMA_N8N_URL", N8N_URL)
        monkeypatch.setenv("PISAMA_N8N_API_KEY", key)
        monkeypatch.setenv("PISAMA_API_KEY", "srv-key")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'poll.db'}")
        # Rebuild the app's storage against this DB.
        import pisama_n8n_server.app as appmod
        from pisama_n8n_server.storage import Storage
        appmod._storage = Storage()
        from fastapi.testclient import TestClient
        client = TestClient(appmod.app)
        hb = {"Authorization": "Bearer srv-key"}

        r1 = client.post("/api/v1/n8n/sync", headers=hb)
        assert r1.status_code == 200, r1.text
        assert r1.json()["new"] >= 1

        dets = client.get("/api/v1/detections", headers=hb).json()
        assert any(d["detector"] == "error" and d["detected"] for d in dets)

        # Re-poll: nothing new (dedup on the upstream execution id).
        r2 = client.post("/api/v1/n8n/sync", headers=hb)
        assert r2.json()["new"] == 0
    finally:
        h = {"X-N8N-API-KEY": key}
        with httpx.Client(base_url=N8N_URL + "/api/v1", headers=h, timeout=30) as c:
            c.post(f"/workflows/{wid}/deactivate")
            c.delete(f"/workflows/{wid}")
