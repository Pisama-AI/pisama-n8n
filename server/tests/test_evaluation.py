"""Closed-loop evaluation API contracts over real captured n8n executions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pisama_n8n_engine import score_labeled_executions
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


def test_feedback_review_promotes_real_execution_to_scorer_ready_case(client):
    payload = _load("executions/data_contract/CLOUD-112117-missing-required-value.json")
    webhook = client.post("/api/v1/n8n/webhook", json=payload)
    assert webhook.status_code == 200, webhook.text
    detection = next(
        row
        for row in client.get("/api/v1/detections").json()
        if row["detected"] and row["failure_mode"] == "n8n_data_contract"
    )
    endpoint = f"/api/v1/detections/{detection['id']}/evaluation-case"
    expected = [
        "n8n_data_contract",
        "n8n_expression",
        "n8n_missing_error_workflow",
    ]
    review = {
        "expected_modes": expected,
        "split": "holdout",
        "label_evidence": (
            "n8n recorded the missing required value and the workflow snapshot has "
            "no error workflow."
        ),
    }

    assert client.post(endpoint, json=review).status_code == 409
    feedback = client.post(
        f"/api/v1/detections/{detection['id']}/feedback",
        json={"verdict": "useful", "note": "Reviewed against the n8n error record."},
    )
    assert feedback.status_code == 200, feedback.text

    created = client.post(endpoint, json=review)
    assert created.status_code == 201, created.text
    case = created.json()
    assert case["expected_modes"] == sorted(expected)
    assert case["taxonomy_version"] == "1"
    assert case["source"]["workflow_id"] == "0H6n1fY53bCT6rhX"

    listed = client.get("/api/v1/evaluation-cases").json()
    assert listed == [case]
    assert "payload" not in listed[0]
    exported = client.get("/api/v1/evaluation-cases/export").json()
    assert exported["schema_version"] == "1"
    assert exported["taxonomy_version"] == "1"
    assert exported["cases"][0]["payload"]["id"] == "112117"
    scorer_input = exported["cases"][0]
    score = score_labeled_executions(
        [
            (
                scorer_input["id"],
                scorer_input["payload"],
                set(scorer_input["expected_modes"]),
            )
        ]
    )
    assert score["exact_set_accuracy"] == 1.0
    summary = client.storage.operational_summary()
    assert summary["evaluation_cases_by_split"] == {"holdout": 1}
    assert summary["reliability_metrics"]["durable_controls"]["harness"] == {
        "implemented": True,
        "reviewed_cases": 1,
        "by_split": {"holdout": 1},
        "note": (
            "Reviewed retained executions can be exported into the canonical "
            "multi-label scorer."
        ),
    }
    detail = client.get(f"/api/v1/detections/{detection['id']}").json()
    assert detail["evaluation_case"]["id"] == case["id"]
    assert detail["execution_fired_modes"] == sorted(expected)
    assert client.post(endpoint, json=review).status_code == 409


def test_evaluation_case_rejects_unknown_taxonomy_mode(client):
    response = client.post(
        "/api/v1/detections/999/evaluation-case",
        json={
            "expected_modes": ["made_up_mode"],
            "split": "regression",
            "label_evidence": "reviewed",
        },
    )

    assert response.status_code == 422
    assert "Unknown taxonomy" in response.json()["detail"]
