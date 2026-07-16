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
        c.post(
            "/rest/owner/setup",
            json={
                "email": OWNER[0],
                "firstName": "P",
                "lastName": "H",
                "password": OWNER[1],
            },
        )
        c.post(
            "/rest/login", json={"emailOrLdapLoginId": OWNER[0], "password": OWNER[1]}
        )
        tok = c.cookies.get("n8n-auth")
        h = {"Cookie": f"n8n-auth={tok}"}
        sc = c.get("/rest/api-keys/scopes", headers=h).json().get("data", [])
        scopes = [s for s in sc if s.startswith(("workflow:", "execution:"))]
        r = c.post(
            "/rest/api-keys",
            json={
                "label": f"poll-test-{int(time.time())}",
                "expiresAt": int(time.time()) + 3600,
                "scopes": scopes,
            },
            headers=h,
        )
        return r.json()["data"]["rawApiKey"]


def _create_active_webhook_workflow(key: str, path: str, name: str, node: dict) -> str:
    """Create one disposable real n8n workflow and return its API id."""
    wf = {
        "name": name,
        "settings": {},
        "nodes": [
            {
                "id": "w",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [0, 0],
                "parameters": {
                    "path": path,
                    "httpMethod": "POST",
                    "responseMode": "lastNode",
                },
                "webhookId": path,
            },
            node,
        ],
        "connections": {
            "Webhook": {"main": [[{"node": node["name"], "type": "main", "index": 0}]]}
        },
    }
    h = {"X-N8N-API-KEY": key}
    with httpx.Client(base_url=N8N_URL + "/api/v1", headers=h, timeout=30) as c:
        body = c.post("/workflows", json=wf).json()
        wid = (body.get("data", body))["id"]
        c.post(f"/workflows/{wid}/activate")
    return wid


def _trigger_webhook(path: str) -> httpx.Response:
    return httpx.post(f"{N8N_URL}/webhook/{path}", json={}, timeout=15)


def _run_failing_workflow(key: str) -> str:
    path = f"polltest-{uuid.uuid4().hex[:8]}"
    wid = _create_active_webhook_workflow(
        key,
        path,
        f"poll-{path}",
        {
            "id": "c",
            "name": "Boom",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [220, 0],
            "parameters": {"jsCode": "throw new Error('poll test');"},
        },
    )
    _trigger_webhook(path)
    time.sleep(2)
    return wid


def _run_timeout_workflow(key: str) -> str:
    """Run an actual delayed external request through n8n's configured timeout."""
    path = f"timeout-{uuid.uuid4().hex[:8]}"
    wid = _create_active_webhook_workflow(
        key,
        path,
        f"poll-{path}",
        {
            "id": "slow-request",
            "name": "Delayed provider",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [220, 0],
            "parameters": {
                "method": "GET",
                "url": "https://httpbin.org/delay/5",
                "options": {"timeout": 500},
            },
        },
    )
    response = _trigger_webhook(path)
    assert response.status_code == 500, response.text
    time.sleep(2)
    return wid


def _polling_client(tmp_path, monkeypatch, key: str, database_name: str):
    """Create a real temporary SQLite Pisama server against the live n8n harness."""
    monkeypatch.setenv("PISAMA_N8N_URL", N8N_URL)
    monkeypatch.setenv("PISAMA_N8N_API_KEY", key)
    monkeypatch.setenv("PISAMA_API_KEY", "srv-key")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / database_name}")
    import pisama_n8n_server.app as appmod
    from pisama_n8n_server.storage import Storage
    from fastapi.testclient import TestClient

    appmod._storage = Storage()
    return TestClient(appmod.app), {"Authorization": "Bearer srv-key"}, appmod._storage


def test_poll_ingests_and_dedups(tmp_path, monkeypatch):
    key = _provision_key()
    wid = _run_failing_workflow(key)
    try:
        client, hb, _ = _polling_client(tmp_path, monkeypatch, key, "poll.db")

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


def test_poll_classifies_a_real_n8n_request_timeout(tmp_path, monkeypatch):
    """A configured n8n HTTP timeout may be recorded as a connection abort.

    This regression uses a real delayed external response and the n8n execution API,
    never a constructed trace. It protects the exact behavior captured in dogfood.
    """
    key = _provision_key()
    wid = _run_timeout_workflow(key)
    try:
        client, headers, _ = _polling_client(tmp_path, monkeypatch, key, "timeout.db")
        sync = client.post("/api/v1/n8n/sync", headers=headers)
        assert sync.status_code == 200, sync.text
        detections = client.get("/api/v1/detections", headers=headers).json()
        fired = {
            (row["detector"], row["failure_mode"])
            for row in detections
            if row["workflow_id"] == wid and row["detected"]
        }
        assert {("timeout", "F13"), ("error", "n8n_timeout")} <= fired
    finally:
        h = {"X-N8N-API-KEY": key}
        with httpx.Client(base_url=N8N_URL + "/api/v1", headers=h, timeout=30) as c:
            c.post(f"/workflows/{wid}/deactivate")
            c.delete(f"/workflows/{wid}")


def test_repair_verification_observes_a_real_post_apply_execution(
    tmp_path, monkeypatch
):
    """A disposable n8n workflow fails, is safely changed, then produces real
    post-apply evidence. No replayed fixture or fabricated execution participates."""
    key = _provision_key()
    wid = _run_failing_workflow(key)
    repair_ids = []
    storage = None
    try:
        monkeypatch.setenv("PISAMA_COMPARISON_MIN_EXECUTIONS", "1")
        from pisama_n8n_server.fixes import apply_fix, rollback
        from pisama_n8n_server.n8n_client import N8nClient

        client, headers, storage = _polling_client(
            tmp_path, monkeypatch, key, "verification.db"
        )
        first_sync = client.post("/api/v1/n8n/sync", headers=headers)
        assert first_sync.status_code == 200, first_sync.text
        source = next(
            row
            for row in client.get("/api/v1/detections", headers=headers).json()
            if row["detector"] == "error"
            and row["detected"]
            and row["workflow_id"] == wid
        )

        async def apply_reviewed_change(baseline, proposed):
            n8n = N8nClient(N8N_URL, key)
            try:
                applied = await apply_fix(n8n, wid, baseline, proposed)
                workflow = await n8n.get_workflow(wid)
                return applied, workflow
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
            repair_ids.append(proposal["id"])
            assert storage.claim_repair_apply(repair_ids[-1])
            # Construct a fresh client inside the coroutine because httpx clients
            # are bound to the event loop that owns them.
            applied, workflow = run(apply_reviewed_change(baseline, proposed))
            storage.mark_repair_applied(repair_ids[-1], **applied)

            # A second real workflow control can be applied to the same source
            # detection. Its later execution must update both open cases.
            second_baseline = workflow
            second_proposed = deepcopy(second_baseline)
            boom = next(
                node for node in second_proposed["nodes"] if node["name"] == "Boom"
            )
            boom["parameters"]["jsCode"] = (
                "return [{ json: { repaired: true, revision: 2 } }];"
            )
            second_proposal = storage.create_repair_proposal(
                detection_id=source["id"],
                workflow_id=wid,
                baseline_workflow=second_baseline,
                suggestion={
                    "explanation": "Add a durable revision marker to the repaired control.",
                    "patch_ops": [],
                    "mutated_workflow": second_proposed,
                },
            )
            repair_ids.append(second_proposal["id"])
            assert storage.claim_repair_apply(repair_ids[-1])
            second_applied, workflow = run(
                apply_reviewed_change(second_baseline, second_proposed)
            )
            storage.mark_repair_applied(repair_ids[-1], **second_applied)

            # The same real webhook now creates a later successful n8n execution.
            webhook = next(
                node for node in workflow["nodes"] if node["name"] == "Webhook"
            )
            path = webhook["parameters"]["path"]
            response = httpx.post(f"{N8N_URL}/webhook/{path}", json={}, timeout=15)
            assert response.status_code == 200, response.text
            time.sleep(2)
            second_sync = client.post("/api/v1/n8n/sync", headers=headers)
            assert second_sync.status_code == 200, second_sync.text

            cases = {
                case["repair_id"]: case
                for case in storage.list_reliability_cases()
                if case["repair_id"] in repair_ids
            }
            assert set(cases) == set(repair_ids)
            assert all(case["status"] == "observing" for case in cases.values())
            assert all(
                case["successful_execution_count"] >= 1 for case in cases.values()
            )
            assert all(case["recurrence_count"] == 0 for case in cases.values())
            assert all(case["comparison_ready"] for case in cases.values())
            assert all(case["recurrence_reduction"] == 1.0 for case in cases.values())
            metrics = client.get("/api/v1/reliability/metrics", headers=headers)
            assert metrics.status_code == 200, metrics.text
            assert metrics.json()["remediation"]["recurrence_reduction"] == 1.0
            # One execution is useful exposure evidence, never enough to assert prevention.
            early = client.post(
                f"/api/v1/reliability-cases/{cases[repair_ids[-1]]['id']}/outcome",
                headers=headers,
                json={"outcome": "prevented"},
            )
            assert early.status_code == 409
        finally:
            for repair_id in reversed(repair_ids):
                repair = storage.get_repair(repair_id, include_workflows=True)
                if repair and repair["status"] == "applied":
                    assert storage.claim_repair_rollback(repair_id)

                    async def restore_snapshot(repair_to_restore):
                        n8n = N8nClient(N8N_URL, key)
                        try:
                            return await rollback(
                                n8n,
                                wid,
                                repair_to_restore["snapshot"],
                                repair_to_restore["applied_workflow"],
                            )
                        finally:
                            await n8n.aclose()

                    restored = run(restore_snapshot(repair))
                    assert restored
                    storage.mark_repair_rolled_back(repair_id)
    finally:
        h = {"X-N8N-API-KEY": key}
        with httpx.Client(base_url=N8N_URL + "/api/v1", headers=h, timeout=30) as c:
            c.post(f"/workflows/{wid}/deactivate")
            c.delete(f"/workflows/{wid}")
