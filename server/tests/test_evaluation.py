"""Closed-loop evaluation API contracts over real captured n8n executions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pisama_n8n_server.app import app, get_storage
from pisama_n8n_server.events import broadcaster
from pisama_n8n_server.storage import Storage

FIXTURES = Path(__file__).parent / "fixtures"


def _load(rel: str):
    return json.loads((FIXTURES / rel).read_text())


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("PISAMA_API_KEY", raising=False)
    monkeypatch.setenv("PISAMA_BUILD_REVISION", "closed-loop-test")
    storage = Storage(url=f"sqlite:///{tmp_path / 'evaluation.db'}")
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as test_client:
        test_client.storage = storage  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()
    storage.close()


def test_evaluate_returns_versioned_multi_label_result_without_side_effects(client):
    payload = _load("executions/data_contract/CLOUD-112117-missing-required-value.json")
    event_queue = broadcaster.subscribe()
    before = client.storage.operational_summary()

    response = client.post("/api/v1/n8n/evaluate", json=payload)

    broadcaster.unsubscribe(event_queue)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evaluation_schema_version"] == "1"
    assert body["taxonomy_version"] == "1"
    assert body["build_revision"] == "closed-loop-test"
    assert body["workflow_id"] == "0H6n1fY53bCT6rhX"
    assert set(body["fired_modes"]) >= {"n8n_expression", "n8n_data_contract"}
    assert all(
        detection["confidence_tier"] in {"high", "medium", "low"}
        for detection in body["detections"]
    )
    assert client.storage.operational_summary() == before
    assert event_queue.empty()


def test_evaluate_and_webhook_share_identical_detector_results(client):
    payload = _load("executions/error/ERROR-01-throw.json")

    evaluated = client.post("/api/v1/n8n/evaluate", json=payload)
    ingested = client.post("/api/v1/n8n/webhook", json=payload)

    assert evaluated.status_code == 200, evaluated.text
    assert ingested.status_code == 200, ingested.text
    evaluation_detections = [
        {key: value for key, value in detection.items() if key != "confidence_tier"}
        for detection in evaluated.json()["detections"]
    ]
    assert evaluation_detections == ingested.json()["detections"]
    assert client.storage.operational_summary()["executions_analyzed"] == 1


def test_evaluate_rejects_an_unknown_payload_without_persistence(client):
    response = client.post("/api/v1/n8n/evaluate", json={"message": "not an execution"})

    assert response.status_code == 422
    assert client.storage.operational_summary()["executions_analyzed"] == 0
