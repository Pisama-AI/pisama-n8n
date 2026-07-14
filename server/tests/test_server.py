"""No-mocks e2e tests for the pisama-n8n self-host server.

Real engine, real SQLite (temp file per test), FastAPI TestClient. The fixtures
are the REAL captured executions / complexity workflows committed in the monorepo
worktree — read by absolute path, never copied here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pisama_n8n_server.app import app, get_storage
from pisama_n8n_server.storage import Storage

FIXTURES = Path(__file__).parent / "fixtures"


def _load(rel: str) -> dict:
    return json.loads((FIXTURES / rel).read_text())


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient backed by a fresh temp-file SQLite Storage. Auth off by default."""
    monkeypatch.delenv("PISAMA_API_KEY", raising=False)
    db_path = tmp_path / "test.db"
    storage = Storage(url=f"sqlite:///{db_path}")
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as c:
        c.storage = storage  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


def _fired(response_json: dict, detector: str) -> bool:
    return any(
        d["detector"] == detector and d["detected"]
        for d in response_json["detections"]
    )


# 1. Runtime lane: each failure fixture fires its matching detection; healthy fires none.

@pytest.mark.parametrize(
    "rel, detector",
    [
        ("executions/timeout/TIMEOUT-01.json", "timeout"),
        ("executions/error/ERROR-01-throw.json", "error"),
        ("executions/resource/RESOURCE-01-100x500.json", "resource"),
    ],
)
def test_runtime_fixture_fires_matching_detection(client, rel, detector):
    payload = _load(rel)
    resp = client.post("/api/v1/n8n/webhook", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert _fired(body, detector), f"expected {detector} to fire for {rel}: {body}"


def test_healthy_fixture_fires_no_failure_detection(client):
    payload = _load("executions/healthy/HEALTHY-01.json")
    resp = client.post("/api/v1/n8n/webhook", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for detector in ("timeout", "error", "resource"):
        assert not _fired(body, detector), f"{detector} unexpectedly fired: {body}"


# 2. Structural lane: a complexity workflow yields schema/complexity detections.

def test_complexity_workflow_yields_structural_detections(client):
    payload = _load("complexity/01-COMPLEXITY-high-node-count.json")
    resp = client.post("/api/v1/n8n/webhook", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    detectors = {d["detector"] for d in body["detections"]}
    assert {"schema", "complexity"} <= detectors, body
    assert _fired(body, "complexity"), body


# 3. Persistence: stored detections are readable back, not just echoed.

def test_detections_are_persisted_and_listable(client):
    payload = _load("executions/timeout/TIMEOUT-01.json")
    post = client.post("/api/v1/n8n/webhook", json=payload)
    assert post.status_code == 200, post.text

    listed = client.get("/api/v1/detections")
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert rows, "expected persisted detections"
    assert any(r["detector"] == "timeout" and r["detected"] for r in rows), rows
    # Persisted, not echoed: rows carry a DB id + execution_id FK.
    assert all("id" in r and "execution_id" in r for r in rows), rows


# 4. Auth: with PISAMA_API_KEY set, missing bearer → 401; correct bearer → 200.

def test_auth_required_when_key_set(client, monkeypatch):
    monkeypatch.setenv("PISAMA_API_KEY", "s3cret")
    payload = _load("executions/healthy/HEALTHY-01.json")

    unauth = client.post("/api/v1/n8n/webhook", json=payload)
    assert unauth.status_code == 401, unauth.text

    auth = client.post(
        "/api/v1/n8n/webhook",
        json=payload,
        headers={"Authorization": "Bearer s3cret"},
    )
    assert auth.status_code == 200, auth.text


# 5. Health.

def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
