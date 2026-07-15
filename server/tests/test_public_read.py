"""Public-read mode: GETs open, every POST still key-gated (the hosted-dashboard seam)."""
import json
import os

from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch, public_read: bool):
    monkeypatch.setenv("PISAMA_API_KEY", "secret-key")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'pr.db'}")
    monkeypatch.delenv("PISAMA_CLOUD_KEY", raising=False)
    if public_read:
        monkeypatch.setenv("PISAMA_PUBLIC_READ", "1")
    else:
        monkeypatch.delenv("PISAMA_PUBLIC_READ", raising=False)
    import pisama_n8n_server.app as appmod
    from pisama_n8n_server.storage import Storage
    appmod._storage = Storage()
    return TestClient(appmod.app)


def _seed(client):
    fx = json.load(open(os.path.join(
        os.path.dirname(__file__), "fixtures", "executions", "error", "ERROR-01-throw.json")))
    r = client.post("/api/v1/n8n/webhook",
                    headers={"Authorization": "Bearer secret-key"}, json=fx)
    assert r.status_code == 200


def test_public_read_opens_gets_but_not_posts(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, public_read=True)
    _seed(c)

    # GETs open without any key
    r = c.get("/api/v1/detections")
    assert r.status_code == 200 and len(r.json()) > 0
    assert c.get("/api/v1/paid/status").status_code == 200

    # every POST still requires the key
    assert c.post("/api/v1/n8n/webhook", json={}).status_code == 401
    assert c.post("/api/v1/n8n/sync").status_code == 401
    assert c.post("/api/v1/n8n/fix", json={"detection_id": 1}).status_code == 401
    assert c.post("/api/v1/n8n/apply",
                  json={"workflow_id": "x", "mutated_workflow": {}}).status_code == 401
    assert c.post("/api/v1/n8n/rollback",
                  json={"workflow_id": "x", "snapshot": {}}).status_code == 401

    # SSE auth wiring: covered via the gated test below (an open infinite stream
    # can't be cleanly closed under TestClient; the open path is verified live).


def test_without_public_read_gets_stay_gated(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, public_read=False)
    assert c.get("/api/v1/detections").status_code == 401
    assert c.get("/api/v1/paid/status").status_code == 401
    assert c.get("/api/v1/stream").status_code == 401  # no token, not public → immediate 401
    r = c.get("/api/v1/detections", headers={"Authorization": "Bearer secret-key"})
    assert r.status_code == 200
