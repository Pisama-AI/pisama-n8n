"""Paid-tier gating + seam tests. The 402 gating runs by default (no mocks, no cloud);
the full cloud→apply→rollback loop is proven by the live harness (paid_e2e), gated here."""
import json
import os

from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("PISAMA_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'fx.db'}")
    monkeypatch.delenv("PISAMA_CLOUD_KEY", raising=False)
    import pisama_n8n_server.app as appmod
    from pisama_n8n_server.storage import Storage
    appmod._storage = Storage()
    return TestClient(appmod.app)


def _seed(client):
    fx = json.load(open(os.path.join(
        os.path.dirname(__file__), "fixtures",
        "executions", "error", "ERROR-01-throw.json")))
    client.post("/api/v1/n8n/webhook", headers={"Authorization": "Bearer k"}, json=fx)
    return client.get("/api/v1/detections", headers={"Authorization": "Bearer k"}).json()[0]["id"]


def test_paid_features_gated_without_cloud_key(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    h = {"Authorization": "Bearer k"}
    assert c.get("/api/v1/paid/status", headers=h).json() == {"enabled": False}
    did = _seed(c)
    assert c.post("/api/v1/n8n/fix", headers=h, json={"detection_id": did}).status_code == 402
    assert c.post("/api/v1/n8n/apply", headers=h,
                  json={"workflow_id": "x", "mutated_workflow": {}}).status_code == 402


def test_fix_unknown_detection_404(tmp_path, monkeypatch):
    monkeypatch.setenv("PISAMA_CLOUD_KEY", "x")  # past the gate
    c = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("PISAMA_CLOUD_KEY", "x")
    r = c.post("/api/v1/n8n/fix", headers={"Authorization": "Bearer k"},
               json={"detection_id": 999999})
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
    rollback = storage.claim_repair_rollback(repair["id"])
    assert rollback and rollback["status"] == "rolling_back"
    restored = storage.mark_repair_rolled_back(repair["id"])
    assert restored["status"] == "rolled_back"
    persisted = storage.get_repair(repair["id"], include_workflows=True)
    assert persisted and persisted["status"] == "rolled_back"
    assert persisted["baseline_workflow"] == context["workflow"]
