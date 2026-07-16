"""Live e2e for the API-polling ingestion channel — real n8n, no mocks.

Gated on PISAMA_HARNESS_N8N=1 + a reachable n8n at PISAMA_TEST_N8N_URL (default
http://127.0.0.1:5679, the docker-compose.healing-harness.yml instance), because it
provisions a key, creates + runs a real failing workflow, then polls it back. Skipped by
default so the normal test run needs no docker.
"""
import os
import time
import uuid
from asyncio import run
from copy import deepcopy

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PISAMA_HARNESS_N8N") != "1",
    reason="set PISAMA_HARNESS_N8N=1 with a live n8n to run the polling e2e",
)

N8N_URL = os.environ.get("PISAMA_TEST_N8N_URL", "http://127.0.0.1:5679")
OWNER = ("harness@pisama.test", "PisamaHarness123!")


def _provision_key() -> str:
    configured_key = os.environ.get("PISAMA_TEST_N8N_API_KEY")
    if configured_key:
        return configured_key
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


def test_repair_verification_observes_a_real_post_apply_execution(tmp_path, monkeypatch):
    """A disposable n8n workflow fails, is safely changed, then produces real
    post-apply evidence. No replayed fixture or fabricated execution participates."""
    key = _provision_key()
    wid = _run_failing_workflow(key)
    repair_id = None
    storage = None
    try:
        monkeypatch.setenv("PISAMA_N8N_URL", N8N_URL)
        monkeypatch.setenv("PISAMA_N8N_API_KEY", key)
        monkeypatch.setenv("PISAMA_API_KEY", "srv-key")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'verification.db'}")
        import pisama_n8n_server.app as appmod
        from pisama_n8n_server.fixes import apply_fix, rollback
        from pisama_n8n_server.n8n_client import N8nClient
        from pisama_n8n_server.storage import Storage
        from fastapi.testclient import TestClient

        appmod._storage = Storage()
        storage = appmod._storage
        client = TestClient(appmod.app)
        headers = {"Authorization": "Bearer srv-key"}
        first_sync = client.post("/api/v1/n8n/sync", headers=headers)
        assert first_sync.status_code == 200, first_sync.text
        source = next(
            row
            for row in client.get("/api/v1/detections", headers=headers).json()
            if row["detector"] == "error" and row["detected"] and row["workflow_id"] == wid
        )

        async def apply_reviewed_change():
            n8n = N8nClient(N8N_URL, key)
            try:
                baseline = await n8n.get_workflow(wid)
                proposed = deepcopy(baseline)
                boom = next(node for node in proposed["nodes"] if node["name"] == "Boom")
                boom["parameters"]["jsCode"] = "return [{ json: { repaired: true } }];"
                applied = await apply_fix(n8n, wid, baseline, proposed)
                workflow = await n8n.get_workflow(wid)
                return baseline, proposed, applied, workflow
            finally:
                await n8n.aclose()

        async def fetch_workflow():
            n8n = N8nClient(N8N_URL, key)
            try:
                return await n8n.get_workflow(wid)
            finally:
                await n8n.aclose()

        try:
            # The storage proposal is the reviewed record. The actual PUT below
            # still uses the production stale guard, on real n8n state.
            baseline = run(fetch_workflow())
            proposed = deepcopy(baseline)
            boom = next(node for node in proposed["nodes"] if node["name"] == "Boom")
            boom["parameters"]["jsCode"] = "return [{ json: { repaired: true } }];"
            proposal = storage.create_repair_proposal(
                detection_id=source["id"],
                workflow_id=wid,
                baseline_workflow=baseline,
                suggestion={
                    "explanation": "Replace the controlled throw with a successful result.",
                    "patch_ops": [],
                    "mutated_workflow": proposed,
                },
            )
            repair_id = proposal["id"]
            assert storage.claim_repair_apply(repair_id)
            # Construct a fresh client inside the coroutine because httpx clients
            # are bound to the event loop that owns them.
            _baseline, _proposed, applied, workflow = run(apply_reviewed_change())
            assert _baseline == baseline
            assert _proposed == proposed
            storage.mark_repair_applied(repair_id, **applied)

            # The same real webhook now creates a later successful n8n execution.
            webhook = next(node for node in workflow["nodes"] if node["name"] == "Webhook")
            path = webhook["parameters"]["path"]
            response = httpx.post(f"{N8N_URL}/webhook/{path}", json={}, timeout=15)
            assert response.status_code == 200, response.text
            time.sleep(2)
            second_sync = client.post("/api/v1/n8n/sync", headers=headers)
            assert second_sync.status_code == 200, second_sync.text

            case = storage.get_reliability_case_for_detection(source["id"])
            assert case and case["status"] == "observing"
            assert case["successful_execution_count"] >= 1
            assert case["recurrence_count"] == 0
            # One execution is useful exposure evidence, never enough to assert prevention.
            early = client.post(
                f"/api/v1/reliability-cases/{case['id']}/outcome",
                headers=headers,
                json={"outcome": "prevented"},
            )
            assert early.status_code == 409
        finally:
            if repair_id is not None:
                repair = storage.get_repair(repair_id, include_workflows=True)
                if repair and repair["status"] == "applied":
                    assert storage.claim_repair_rollback(repair_id)
                    async def restore_snapshot():
                        n8n = N8nClient(N8N_URL, key)
                        try:
                            return await rollback(
                                n8n,
                                wid,
                                repair["snapshot"],
                                repair["applied_workflow"],
                            )
                        finally:
                            await n8n.aclose()

                    restored = run(restore_snapshot())
                    assert restored
                    storage.mark_repair_rolled_back(repair_id)
    finally:
        h = {"X-N8N-API-KEY": key}
        with httpx.Client(base_url=N8N_URL + "/api/v1", headers=h, timeout=30) as c:
            c.post(f"/workflows/{wid}/deactivate")
            c.delete(f"/workflows/{wid}")
