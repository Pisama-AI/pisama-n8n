"""Paid-tier gating + seam tests. The 402 gating runs by default (no mocks, no cloud);
the full cloud→apply→rollback loop is proven by the live harness (paid_e2e), gated here."""

import json
import os
from asyncio import run
from copy import deepcopy

from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("PISAMA_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'fx.db'}")
    monkeypatch.delenv("PISAMA_CLOUD_KEY", raising=False)
    import pisama_n8n_server.app as appmod
    from pisama_n8n_server.storage import Storage

    appmod._storage = Storage()
    return TestClient(appmod.app)


def _seed(client):
    fx = json.load(
        open(
            os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "executions",
                "error",
                "ERROR-01-throw.json",
            )
        )
    )
    client.post("/api/v1/n8n/webhook", headers={"Authorization": "Bearer k"}, json=fx)
    rows = client.get(
        "/api/v1/detections", headers={"Authorization": "Bearer k"}
    ).json()
    return next(
        row["id"] for row in rows if row["detector"] == "error" and row["detected"]
    )


def test_paid_features_gated_without_cloud_key(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    h = {"Authorization": "Bearer k"}
    assert c.get("/api/v1/paid/status", headers=h).json() == {"enabled": False}
    did = _seed(c)
    assert (
        c.post("/api/v1/n8n/fix", headers=h, json={"detection_id": did}).status_code
        == 402
    )
    assert (
        c.post(
            "/api/v1/n8n/apply",
            headers=h,
            json={"workflow_id": "x", "mutated_workflow": {}},
        ).status_code
        == 402
    )


def test_fix_unknown_detection_404(tmp_path, monkeypatch):
    monkeypatch.setenv("PISAMA_CLOUD_KEY", "x")  # past the gate
    c = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("PISAMA_CLOUD_KEY", "x")
    r = c.post(
        "/api/v1/n8n/fix",
        headers={"Authorization": "Bearer k"},
        json={"detection_id": 999999},
    )
    assert r.status_code == 404


def test_apply_rejects_client_supplied_workflow_json(tmp_path, monkeypatch):
    """A browser may apply only a server-owned repair proposal, never arbitrary JSON."""
    c = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("PISAMA_CLOUD_KEY", "x")
    r = c.post(
        "/api/v1/n8n/apply",
        headers={"Authorization": "Bearer k"},
        json={"workflow_id": "x", "mutated_workflow": {"name": "untrusted"}},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "repair_id is required."


def test_repair_proposal_lifecycle_is_persisted_in_real_sqlite(tmp_path, monkeypatch):
    """Captured n8n data produces a durable, single-claim repair audit record."""
    c = _client(tmp_path, monkeypatch)
    detection_id = _seed(c)
    import pisama_n8n_server.app as appmod

    storage = appmod.get_storage()
    context = storage.get_detection_context(detection_id)
    assert context and context["workflow"] and context["workflow_id"]
    repair = storage.create_repair_proposal(
        detection_id=detection_id,
        workflow_id=context["workflow_id"],
        baseline_workflow=context["workflow"],
        suggestion={
            "explanation": "Captured workflow review.",
            "patch_ops": [],
            "mutated_workflow": context["workflow"],
        },
    )
    assert repair["status"] == "proposed"
    claimed = storage.claim_repair_apply(repair["id"])
    assert claimed and claimed["status"] == "applying"
    assert storage.claim_repair_apply(repair["id"]) is None
    applied = storage.mark_repair_applied(
        repair["id"], context["workflow"], context["workflow"]
    )
    assert applied["status"] == "applied"
    # Applying a repair opens a durable, tenant-local verification record. It is
    # evidence gathering, not a claim that the failure is fixed.
    cases = c.get("/api/v1/reliability-cases", headers={"Authorization": "Bearer k"})
    assert cases.status_code == 200, cases.text
    case = cases.json()[0]
    assert case["repair_id"] == repair["id"]
    assert case["status"] == "observing"
    assert case["baseline_execution_count"] == 1
    assert case["baseline_failure_count"] == 1
    assert case["comparison_ready"] is False
    assert case["successful_execution_count"] == 0
    assert case["recurrence_count"] == 0
    # One repair and no post-repair traffic can never be called prevention.
    too_early = c.post(
        f"/api/v1/reliability-cases/{case['id']}/outcome",
        headers={"Authorization": "Bearer k"},
        json={"outcome": "prevented"},
    )
    assert too_early.status_code == 409

    # Re-ingesting an actual historical capture remains valid detector-regression
    # input, but cannot be misclassified as a post-repair recurrence.
    source = json.load(
        open(
            os.path.join(
                os.path.dirname(__file__),
                "fixtures",
                "executions",
                "error",
                "ERROR-01-throw.json",
            )
        )
    )
    recurrence = c.post("/api/v1/n8n/webhook", headers={"Authorization": "Bearer k"}, json=source)
    assert recurrence.status_code == 200, recurrence.text
    observed = c.get(
        f"/api/v1/reliability-cases/{case['id']}", headers={"Authorization": "Bearer k"}
    )
    assert observed.status_code == 200, observed.text
    assert observed.json()["status"] == "observing"
    assert observed.json()["recurrence_count"] == 0

    inconclusive = c.post(
        f"/api/v1/reliability-cases/{case['id']}/outcome",
        headers={"Authorization": "Bearer k"},
        json={"outcome": "inconclusive", "note": "Not enough post-repair traffic."},
    )
    assert inconclusive.status_code == 200, inconclusive.text
    assert inconclusive.json()["status"] == "inconclusive"
    assert inconclusive.json()["outcome"] == "inconclusive"
    assert inconclusive.json()["outcome_note"] == "Not enough post-repair traffic."

    rollback = storage.claim_repair_rollback(repair["id"])
    assert rollback and rollback["status"] == "rolling_back"
    restored = storage.mark_repair_rolled_back(repair["id"])
    assert restored["status"] == "rolled_back"
    rolled_back_case = c.get(
        f"/api/v1/reliability-cases/{case['id']}", headers={"Authorization": "Bearer k"}
    )
    assert rolled_back_case.json()["status"] == "rolled_back"
    assert rolled_back_case.json()["outcome"] == "inconclusive"
    metrics = c.get("/api/v1/reliability/metrics", headers={"Authorization": "Bearer k"})
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["remediation"]["inconclusive"] == 1
    assert metrics.json()["remediation"]["recurrence_reduction"] is None
    assert metrics.json()["time_to_applied_workflow_control"]["sample_size"] == 1
    persisted = storage.get_repair(repair["id"], include_workflows=True)
    assert persisted and persisted["status"] == "rolled_back"
    assert persisted["baseline_workflow"] == context["workflow"]


def test_fix_uses_a_fresh_n8n_workflow_as_its_stale_guard_baseline(
    tmp_path, monkeypatch
):
    """Execution exports contain transient defaults, so they must not become repair baselines."""
    monkeypatch.setenv("PISAMA_CLOUD_KEY", "x")
    c = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("PISAMA_CLOUD_KEY", "x")
    detection_id = _seed(c)

    import pisama_n8n_server.app as appmod
    import pisama_n8n_server.fixes as fixes

    live_workflow = {
        "name": "Canonical live workflow",
        "nodes": [],
        "connections": {},
        "settings": {},
    }

    class FakeClient:
        async def get_workflow(self, _workflow_id):
            return deepcopy(live_workflow)

        async def aclose(self):
            return None

    async def fake_request_fix(_detection, workflow):
        proposed = deepcopy(workflow)
        proposed["settings"]["executionTimeout"] = 30
        return {
            "explanation": "Set a timeout.",
            "patch_ops": [
                {
                    "op": "set",
                    "target": "settings",
                    "key": "executionTimeout",
                    "value": 30,
                }
            ],
            "mutated_workflow": proposed,
        }

    monkeypatch.setattr(appmod, "client_from_env", lambda: FakeClient())
    monkeypatch.setattr(fixes, "request_fix", fake_request_fix)

    response = c.post(
        "/api/v1/n8n/fix",
        headers={"Authorization": "Bearer k"},
        json={"detection_id": detection_id},
    )

    assert response.status_code == 200
    repair = appmod.get_storage().get_repair(
        response.json()["repair_id"], include_workflows=True
    )
    assert repair and repair["baseline_workflow"] == live_workflow


def test_apply_fix_returns_the_storage_contract_field_names():
    from pisama_n8n_server.fixes import apply_fix

    baseline = {"name": "Before", "nodes": [], "connections": {}, "settings": {}}
    proposed = {"name": "After", "nodes": [], "connections": {}, "settings": {}}

    class FakeClient:
        async def get_workflow(self, _workflow_id):
            return baseline

        async def update_workflow(self, _workflow_id, workflow):
            return workflow

    result = run(apply_fix(FakeClient(), "workflow-id", baseline, proposed))

    assert result == {"snapshot": baseline, "applied_workflow": proposed}
