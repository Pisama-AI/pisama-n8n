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
from sqlalchemy import create_engine, inspect, text

from pisama_n8n_server.app import app, get_storage
from pisama_n8n_server.storage import Storage, redact_execution_payload

FIXTURES = Path(__file__).parent / "fixtures"


def _load(rel: str) -> dict:
    return json.loads((FIXTURES / rel).read_text())


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient backed by a fresh temp-file SQLite Storage. Auth off by default."""
    monkeypatch.delenv("PISAMA_API_KEY", raising=False)
    monkeypatch.delenv("PISAMA_BUILD_REVISION", raising=False)
    db_path = tmp_path / "test.db"
    storage = Storage(url=f"sqlite:///{db_path}")
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as c:
        c.storage = storage  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()
    storage.close()


def _fired(response_json: dict, detector: str) -> bool:
    return any(
        d["detector"] == detector and d["detected"] for d in response_json["detections"]
    )


def test_execution_persistence_redacts_http_credential_headers():
    payload = {
        "workflowData": {
            "nodes": [
                {
                    "parameters": {
                        "headerParameters": {
                            "parameters": [
                                {"name": "x-api-key", "value": "secret-value"},
                                {"name": "accept", "value": "application/json"},
                            ]
                        }
                    }
                }
            ]
        }
    }
    redacted = redact_execution_payload(payload)
    headers = redacted["workflowData"]["nodes"][0]["parameters"]["headerParameters"][
        "parameters"
    ]
    assert headers[0]["value"] == "[redacted]"
    assert headers[1]["value"] == "application/json"


# 1. Runtime lane: each failure fixture fires its matching detection; healthy fires none.


@pytest.mark.parametrize(
    "rel, detector",
    [
        (
            "executions/data_contract/CLOUD-112117-missing-required-value.json",
            "schema",
        ),
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


def test_real_cloud_data_contract_fixture_recommends_the_input_schema_guardrail(client):
    """Regression for Cloud execution 112117, captured before its workflow was patched."""
    payload = _load("executions/data_contract/CLOUD-112117-missing-required-value.json")
    resp = client.post("/api/v1/n8n/webhook", json=payload)
    assert resp.status_code == 200, resp.text

    schema = next(
        detection
        for detection in resp.json()["detections"]
        if detection["detector"] == "schema"
    )
    assert schema["detected"] is True
    assert schema["failure_mode"] == "n8n_data_contract"
    assert schema["evidence"]["issues"] == [
        {
            "node": "Observed missing field",
            "turn": 1,
            "message": "Cannot read properties of undefined (reading 'value') [line 1]",
        }
    ]
    assert "Pisama input-schema guard" in schema["explanation"]


# 2. Structural lane: a complexity workflow yields a complexity verdict. Runtime
# data-contract analysis deliberately does not run without an execution.


def test_complexity_workflow_yields_structural_detection(client):
    payload = _load("complexity/01-COMPLEXITY-high-node-count.json")
    resp = client.post("/api/v1/n8n/webhook", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    detectors = {d["detector"] for d in body["detections"]}
    assert {"cycle", "complexity"} <= detectors, body
    assert "schema" not in detectors, body
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
    # Every new row retains the detector semantic contract and the image revision
    # that produced it. A local TestClient has no injected image revision.
    timeout = next(row for row in rows if row["detector"] == "timeout")
    assert timeout["detector_version"] == "1.1"
    assert timeout["build_revision"] == "unknown"
    assert isinstance(timeout["evidence"], dict)


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
    assert resp.json() == {"status": "ok", "build_revision": "unknown"}


def test_product_capability_contract_is_public_and_explicit(client):
    resp = client.get("/api/v1/capabilities")
    assert resp.status_code == 200
    manifest = resp.json()
    products = {product["id"]: product for product in manifest["products"]}
    labels = {
        capability["id"]: capability["label"] for capability in manifest["capabilities"]
    }

    assert labels["deterministic_repairs"] == "Deterministic repairs"
    assert labels["model_generated_fixes"] == "Model-generated fixes"
    assert products["n8n_self_hosted"]["category"] == "fair_code"
    assert (
        products["n8n_self_hosted"]["capabilities"]["deterministic_repairs"]
        == "Input guardrails and error-route repairs"
    )
    assert products["n8n_cloud_free"]["allowances"]["n8n_connections"] == 1
    assert products["n8n_pro"]["allowances"]["model_fix_generations_per_month"] == 200


def test_detection_retains_configured_build_revision(client, monkeypatch):
    """A deployment-supplied revision is attached at ingestion, not inferred later."""
    monkeypatch.setenv("PISAMA_BUILD_REVISION", "dogfood-current-source")
    payload = _load("executions/timeout/TIMEOUT-01.json")
    assert client.post("/api/v1/n8n/webhook", json=payload).status_code == 200

    rows = client.get("/api/v1/detections").json()
    assert rows and {row["build_revision"] for row in rows} == {
        "dogfood-current-source"
    }
    assert client.get("/healthz").json()["build_revision"] == "dogfood-current-source"


# 6. Enriched detection rows: workflow name/id + n8n execution id are surfaced.


def test_detections_carry_workflow_context(client):
    payload = _load("executions/timeout/TIMEOUT-01.json")
    assert client.post("/api/v1/n8n/webhook", json=payload).status_code == 200

    rows = client.get("/api/v1/detections").json()
    assert rows, "expected persisted detections"
    row = rows[0]
    # New context fields are present on every row...
    assert {"workflow_id", "workflow_name", "n8n_execution_id"} <= row.keys(), row
    # ...and populated from the payload's workflowData.
    assert row["workflow_name"] == "TIMEOUT-01", row
    assert row["workflow_id"] == "66C4S8I05eHPyJhR", row
    # Webhook push has no upstream n8n execution id (poll-only).
    assert row["n8n_execution_id"] is None, row


# 7. Fetch a single detection by id; unknown id → 404.


def test_get_detection_by_id(client):
    payload = _load("executions/timeout/TIMEOUT-01.json")
    assert client.post("/api/v1/n8n/webhook", json=payload).status_code == 200

    listed = client.get("/api/v1/detections").json()
    det_id = listed[0]["id"]

    one = client.get(f"/api/v1/detections/{det_id}")
    assert one.status_code == 200, one.text
    assert one.json()["id"] == det_id
    assert one.json()["workflow_name"] == "TIMEOUT-01"

    missing = client.get("/api/v1/detections/999999")
    assert missing.status_code == 404, missing.text


# 8. Execution trace: per-node timing/status/errors behind a detection.


def _first_detection_id(client) -> int:
    return client.get("/api/v1/detections").json()[0]["id"]


def test_trace_runtime_surfaces_slow_node(client):
    assert (
        client.post(
            "/api/v1/n8n/webhook", json=_load("executions/timeout/TIMEOUT-01.json")
        ).status_code
        == 200
    )
    trace = client.get(f"/api/v1/detections/{_first_detection_id(client)}/trace").json()

    assert trace["available"] and trace["kind"] == "runtime", trace
    by_name = {n["name"]: n for n in trace["nodes"]}
    assert "Slow Code" in by_name, trace
    # The slow node's real execution time is carried through (~64s).
    assert by_name["Slow Code"]["execution_time_ms"] > 60_000, by_name["Slow Code"]
    assert by_name["Slow Code"]["type"] == "n8n-nodes-base.code", by_name["Slow Code"]


def test_trace_runtime_marks_error_node(client):
    assert (
        client.post(
            "/api/v1/n8n/webhook", json=_load("executions/error/ERROR-01-throw.json")
        ).status_code
        == 200
    )
    trace = client.get(f"/api/v1/detections/{_first_detection_id(client)}/trace").json()

    assert trace["status"] == "error", trace
    assert trace["error"], "expected a top-level error message"
    errored = [n for n in trace["nodes"] if n["status"] == "error"]
    assert errored and errored[0]["error"], errored


def test_trace_static_for_bare_workflow(client):
    assert (
        client.post(
            "/api/v1/n8n/webhook",
            json=_load("complexity/01-COMPLEXITY-high-node-count.json"),
        ).status_code
        == 200
    )
    trace = client.get(f"/api/v1/detections/{_first_detection_id(client)}/trace").json()

    assert trace["available"] and trace["kind"] == "static", trace
    assert trace["node_count"] > 0 and all(n["ran"] is False for n in trace["nodes"]), (
        trace
    )


def test_trace_unknown_id_404(client):
    assert client.get("/api/v1/detections/999999/trace").status_code == 404


# 9. Operator feedback + local operational health are persisted with real execution data.


def test_feedback_and_operations_summary_use_persisted_execution_data(client):
    posted = client.post(
        "/api/v1/n8n/webhook", json=_load("executions/error/ERROR-01-throw.json")
    )
    assert posted.status_code == 200, posted.text
    detection_id = client.get("/api/v1/detections").json()[0]["id"]

    feedback = client.post(
        f"/api/v1/detections/{detection_id}/feedback",
        json={"verdict": "useful"},
    )
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["verdict"] == "useful"

    detail = client.get(f"/api/v1/detections/{detection_id}")
    assert detail.status_code == 200
    assert detail.json()["feedback"]["verdict"] == "useful"

    summary = client.get("/api/v1/operations/summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["executions_analyzed"] == 1
    assert body["detections_fired"] >= 1
    assert body["feedback_by_verdict"] == {"useful": 1}
    diagnosis = body["reliability_metrics"]["diagnosis"]
    # Canonical shape (Loop M2): the reviewed-based rate is kept and labeled, and the
    # explicit denominators (seen, review_coverage) ride alongside it.
    assert diagnosis["accepted"] == 1
    assert diagnosis["rejected"] == 0
    assert diagnosis["reviewed"] == 1
    assert diagnosis["acceptance_rate"] == 1.0
    assert diagnosis["seen"] == 0  # nothing opened the detail view in this test
    assert diagnosis["acceptance_of_seen"] is None
    assert diagnosis["review_coverage"] is not None
    assert "by_detector" in diagnosis
    assert "webhook_ingested" in body["latest_events"]


def test_feedback_rejects_unknown_verdict_and_detection(client):
    assert (
        client.post(
            "/api/v1/detections/999999/feedback", json={"verdict": "useful"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/detections/1/feedback", json={"verdict": "maybe"}
        ).status_code
        == 422
    )


# 10. Flatted DB wire format: a dumped execution_data column POSTs and detects.
#    FLATTED-01-error.json is ERROR-01-throw.json's data column re-encoded in the
#    `flatted` npm wire format (what n8n stores in the DB) — synthetic, no wild data.


def test_flatted_array_execution_detects_and_persists(client):
    payload = _load("executions/flatted/FLATTED-01-error.json")
    assert isinstance(payload, list), "fixture must be the raw flatted ARRAY"

    resp = client.post("/api/v1/n8n/webhook", json=payload)
    assert resp.status_code == 200, resp.text
    assert _fired(resp.json(), "error"), resp.json()

    rows = client.get("/api/v1/detections").json()
    assert any(r["detector"] == "error" and r["detected"] for r in rows), rows


def test_undecodable_list_payload_is_422(client):
    resp = client.post("/api/v1/n8n/webhook", json=[{"file": "notes.json"}, {"x": 1}])
    assert resp.status_code == 422, resp.text
    assert "Unrecognized execution payload" in resp.json()["detail"]


def test_existing_reliability_case_table_receives_outcome_column_on_upgrade(tmp_path):
    """The prior repair-case release had no outcome column. Opening its real
    SQLite file under this release must perform the additive upgrade in place."""
    db_path = tmp_path / "prior-release.db"
    url = f"sqlite:///{db_path}"
    old_engine = create_engine(url)
    with old_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE reliability_cases ("
                "id INTEGER PRIMARY KEY, repair_id INTEGER NOT NULL, "
                "detection_id INTEGER NOT NULL, workflow_id VARCHAR NOT NULL, "
                "detector VARCHAR NOT NULL, failure_mode VARCHAR, status VARCHAR NOT NULL, "
                "successful_execution_count INTEGER NOT NULL, recurrence_count INTEGER NOT NULL, "
                "first_success_execution_id INTEGER, first_recurrence_execution_id INTEGER, "
                "outcome_note TEXT, created_at VARCHAR NOT NULL, updated_at VARCHAR NOT NULL, "
                "outcome_at VARCHAR)"
            )
        )
    old_engine.dispose()

    upgraded = Storage(url=url)
    columns = {
        column["name"]
        for column in inspect(upgraded.engine).get_columns("reliability_cases")
    }
    assert {
        "outcome",
        "baseline_execution_count",
        "baseline_failure_count",
        "post_repair_execution_count",
        "post_repair_failure_count",
    } <= columns


def test_existing_execution_and_detection_tables_receive_provenance_columns(tmp_path):
    """An upgraded self-host database keeps old evidence but labels it unversioned."""
    db_path = tmp_path / "prior-detection-release.db"
    url = f"sqlite:///{db_path}"
    old_engine = create_engine(url)
    with old_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE executions ("
                "id INTEGER PRIMARY KEY, workflow_id VARCHAR, received_at VARCHAR NOT NULL, "
                "raw TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE detections ("
                "id INTEGER PRIMARY KEY, execution_id INTEGER NOT NULL, detector VARCHAR NOT NULL, "
                "detected BOOLEAN NOT NULL, confidence FLOAT NOT NULL, failure_mode VARCHAR, "
                "explanation TEXT)"
            )
        )
    old_engine.dispose()

    upgraded = Storage(url=url)
    execution_columns = {
        column["name"] for column in inspect(upgraded.engine).get_columns("executions")
    }
    detection_columns = {
        column["name"] for column in inspect(upgraded.engine).get_columns("detections")
    }
    assert "build_revision" in execution_columns
    assert "detector_version" in detection_columns
    assert "evidence" in detection_columns
