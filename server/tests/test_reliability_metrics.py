"""Honest outcome metrics on the self-host server (Loop M2).

The old _durable_control_metrics hardcoded "share": None and counted anything ever
applied — including rolled-back repairs, drifted guards, and AI model patches. The
old diagnosis rate divided by a self-selected sample. These tests pin the corrected
canonical shape shared with the SaaS server:

  - seen-tracking: first-wins idempotent, fired-only counting, sound denominator;
  - durable controls: one fixture per cell of the strict classification, INCLUDING
    the SQL NULL-trap regression (an applied repair with NO reliability case must
    count as not-drifted) and a legacy guard_config without a kind key;
  - time_to_verified_control: prevented cases only; a prevented-then-rolled-back
    case still counts (the verification happened);
  - the frozen key-set contract mirroring the SaaS test, because there is no shared
    package and shape drift must fail here, not in the shared dashboard.

No mocks: real engine, real SQLite, real TestClient.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

FIXTURES = Path(__file__).parent / "fixtures"
H = {"Authorization": "Bearer k"}


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("PISAMA_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'metrics.db'}")
    import pisama_n8n_server.app as appmod
    from pisama_n8n_server.storage import Storage

    appmod._storage = Storage()
    return appmod, TestClient(appmod.app)


def _ingest_error_fixture(c) -> int:
    fx = json.loads((FIXTURES / "executions/error/ERROR-01-throw.json").read_text())
    r = c.post("/api/v1/n8n/webhook", headers=H, json=fx)
    assert r.status_code == 200, r.text
    rows = c.get("/api/v1/detections", headers=H).json()
    return next(r["id"] for r in rows if r["detected"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_repair(storage, *, guard_config, applied, rolled_back=False,
                 case_status=None, workflow_id="wf-metrics"):
    """Insert one repair row (+ optional case) directly — each test cell needs exact
    lifecycle states that would take an entire stand-in-n8n flow each to reach."""
    from pisama_n8n_server.storage import (
        DetectionRow,
        Execution,
        ReliabilityCase,
        RepairAttempt,
    )

    now = _now()
    with storage._Session() as session:
        execution = Execution(
            workflow_id=workflow_id,
            received_at=now,
            raw="{}",
        )
        session.add(execution)
        session.flush()
        detection = DetectionRow(
            execution_id=execution.id,
            detector="schema",
            detected=True,
            confidence=0.95,
            failure_mode="n8n_data_contract",
        )
        session.add(detection)
        session.flush()
        repair = RepairAttempt(
            detection_id=detection.id,
            workflow_id=workflow_id,
            status="applied" if applied else "proposed",
            explanation="seeded",
            baseline_workflow="{}",
            proposed_workflow="{}",
            guard_config=json.dumps(guard_config) if guard_config else None,
            created_at=now,
            applied_at=now if applied else None,
            rolled_back_at=now if rolled_back else None,
        )
        session.add(repair)
        session.flush()
        if case_status is not None:
            session.add(
                ReliabilityCase(
                    repair_id=repair.id,
                    detection_id=detection.id,
                    workflow_id=workflow_id,
                    detector="schema",
                    failure_mode="n8n_data_contract",
                    status=case_status,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.commit()
        return repair.id


# ── seen tracking ────────────────────────────────────────────────────────────

def test_seen_is_first_wins_idempotent_and_in_payload(tmp_path, monkeypatch):
    _appmod, c = _client(tmp_path, monkeypatch)
    det = _ingest_error_fixture(c)

    first = c.post(f"/api/v1/detections/{det}/seen", headers=H)
    assert first.status_code == 200, first.text
    stamp = first.json()["seen_at"]
    assert stamp
    second = c.post(f"/api/v1/detections/{det}/seen", headers=H)
    assert second.json()["seen_at"] == stamp

    listed = c.get("/api/v1/detections", headers=H).json()
    assert next(r for r in listed if r["id"] == det)["seen_at"] == stamp

    assert c.post("/api/v1/detections/999999/seen", headers=H).status_code == 404


def test_diagnosis_denominators_and_by_detector(tmp_path, monkeypatch):
    _appmod, c = _client(tmp_path, monkeypatch)
    _ingest_error_fixture(c)
    rows = [r for r in c.get("/api/v1/detections", headers=H).json() if r["detected"]]
    detectors = {r["detector"] for r in rows}
    assert len(rows) >= 2, "error fixture should fire at least two detectors"

    # Open ONE detection's detail; leave the rest unseen. Accept it as useful.
    target = rows[0]
    c.post(f"/api/v1/detections/{target['id']}/seen", headers=H)
    c.post(
        f"/api/v1/detections/{target['id']}/feedback",
        headers=H,
        json={"verdict": "useful"},
    )
    # Reject another detector's finding WITHOUT opening it (self-selected sample).
    other = next(r for r in rows if r["detector"] != target["detector"])
    c.post(
        f"/api/v1/detections/{other['id']}/feedback",
        headers=H,
        json={"verdict": "not_useful"},
    )

    diagnosis = c.get("/api/v1/operations/summary", headers=H).json()[
        "reliability_metrics"
    ]["diagnosis"]
    assert diagnosis["accepted"] == 1
    assert diagnosis["rejected"] == 1
    assert diagnosis["reviewed"] == 2
    assert diagnosis["acceptance_rate"] == 0.5
    assert diagnosis["seen"] == 1
    assert diagnosis["acceptance_of_seen"] == 1.0  # accepted / seen
    assert diagnosis["review_coverage"] == round(2 / len(rows), 4)
    per = diagnosis["by_detector"]
    assert set(per) == detectors
    assert per[target["detector"]]["accepted"] == 1
    assert per[target["detector"]]["seen"] == 1
    assert per[other["detector"]]["rejected"] == 1
    assert per[other["detector"]]["seen"] == 0


# ── durable controls: one fixture per classification cell ────────────────────

def test_durable_share_strict_by_kind(tmp_path, monkeypatch):
    appmod, c = _client(tmp_path, monkeypatch)
    storage = appmod.get_storage()
    guard = {"kind": "input_schema", "paths": ["value"]}
    route = {"kind": "error_route", "target_workflow_id": "t"}
    legacy = {"paths": ["value"]}  # pre-error-route rows have no kind key

    _seed_repair(storage, guard_config=guard, applied=True)                      # durable guard
    _seed_repair(storage, guard_config=guard, applied=True, case_status="drifted")  # drifted
    _seed_repair(storage, guard_config=guard, applied=True, rolled_back=True)    # rolled back
    _seed_repair(storage, guard_config=legacy, applied=True)                     # legacy → input_schema, durable
    _seed_repair(storage, guard_config=route, applied=True)                      # durable error-route
    _seed_repair(storage, guard_config=None, applied=True)                       # model patch, standing
    _seed_repair(storage, guard_config=None, applied=True, rolled_back=True)     # model patch, rolled back
    _seed_repair(storage, guard_config=guard, applied=False)                     # proposed, never applied

    durable = c.get("/api/v1/operations/summary", headers=H).json()[
        "reliability_metrics"
    ]["durable_controls"]

    schema = durable["by_kind"]["input_schema"]
    # 5 input_schema proposed (3 kind-carrying applied + legacy + never-applied);
    # durable = the standing guard + the legacy one. The NULL-trap regression lives
    # here: the two durable rows have NO reliability case, so a SQL-side
    # status != 'drifted' filter would have silently dropped them.
    assert schema == {
        "proposed": 5, "applied": 4, "durable": 2,
        "share": round(2 / 5, 4),
    }
    assert durable["by_kind"]["error_route"]["durable"] == 1
    patch = durable["by_kind"]["workflow_patch"]
    assert patch["proposed"] == 2 and patch["applied"] == 2 and patch["durable"] == 1
    assert "not rolled back" in patch["note"]

    assert durable["proposed"] == 8
    assert durable["applied"] == 7
    assert durable["durable"] == 4
    assert durable["share"] == round(4 / 8, 4)
    assert durable["applied_workflow_controls"] == 7  # old-dashboard compatibility
    assert durable["harness"]["implemented"] is False


# ── time to verified control ─────────────────────────────────────────────────

def test_time_to_verified_counts_prevented_even_after_rollback(tmp_path, monkeypatch):
    appmod, c = _client(tmp_path, monkeypatch)
    storage = appmod.get_storage()
    from pisama_n8n_server.storage import ReliabilityCase

    rid = _seed_repair(
        storage,
        guard_config={"kind": "input_schema"},
        applied=True,
        case_status="observing",
    )
    later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    with storage._Session() as session:
        case = session.execute(
            select(ReliabilityCase).where(ReliabilityCase.repair_id == rid)
        ).scalar_one()
        # prevented then rolled back: outcome survives by design, so the verified
        # duration still counts — the verification DID happen.
        case.outcome = "prevented"
        case.outcome_at = later
        case.status = "rolled_back"
        session.commit()

    verified = c.get("/api/v1/operations/summary", headers=H).json()[
        "reliability_metrics"
    ]["time_to_verified_control"]
    assert verified["sample_size"] == 1
    assert verified["median_seconds"] is not None
    assert 7000 <= verified["median_seconds"] <= 7400  # ~2h


# ── the frozen key-set contract (mirrors the SaaS test) ──────────────────────

def test_summary_frozen_key_set(tmp_path, monkeypatch):
    _appmod, c = _client(tmp_path, monkeypatch)
    summary = c.get("/api/v1/operations/summary", headers=H).json()

    metrics = summary["reliability_metrics"]
    assert set(metrics) == {
        "diagnosis",
        "remediation",
        "time_to_applied_workflow_control",
        "time_to_verified_control",
        "durable_controls",
    }
    assert set(metrics["diagnosis"]) == {
        "accepted", "rejected", "reviewed", "acceptance_rate",
        "seen", "acceptance_of_seen", "review_coverage", "by_detector",
    }
    assert set(metrics["remediation"]) == {
        "prevented", "recurred", "inconclusive", "verified_outcomes",
        "verified_remediation_rate", "comparison_cases", "baseline_failure_rate",
        "post_repair_failure_rate", "recurrence_reduction",
        "recurrence_reduction_note",
    }
    assert set(metrics["time_to_applied_workflow_control"]) == {
        "sample_size", "median_seconds", "p90_seconds",
    }
    assert set(metrics["time_to_verified_control"]) == {
        "sample_size", "median_seconds", "p90_seconds",
    }
    durable = metrics["durable_controls"]
    assert set(durable) == {
        "applied_workflow_controls", "proposed", "applied", "durable",
        "share", "share_note", "by_kind", "harness",
    }
    assert set(durable["by_kind"]) == {
        "input_schema", "error_route", "workflow_patch",
    }
    assert durable["harness"]["implemented"] is False


# ── upgrade path: an existing DB gains seen_at at boot ───────────────────────

def test_existing_detections_table_gains_seen_at_on_upgrade(tmp_path, monkeypatch):
    """A production SQLite volume predates seen_at. Opening it under this release
    must ALTER the column in place — the e2e run used a fresh DB (create_all path)
    and never exercised this, so it gets pinned here."""
    from sqlalchemy import create_engine, text

    db_path = tmp_path / "prior-release.db"
    url = f"sqlite:///{db_path}"
    old_engine = create_engine(url)
    with old_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE detections ("
                "id INTEGER PRIMARY KEY, execution_id INTEGER NOT NULL, "
                "detector VARCHAR NOT NULL, detected BOOLEAN NOT NULL, "
                "confidence FLOAT NOT NULL, failure_mode VARCHAR, "
                "explanation VARCHAR, detector_version VARCHAR, "
                "evidence TEXT NOT NULL DEFAULT '{}')"
            )
        )
        # The list endpoint joins executions, so a faithful old DB needs one.
        connection.execute(
            text(
                "CREATE TABLE executions ("
                "id INTEGER PRIMARY KEY, workflow_id VARCHAR, "
                "received_at VARCHAR NOT NULL, raw TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO executions (id, workflow_id, received_at, raw)"
                " VALUES (1, 'wf-old', '2026-07-01T00:00:00+00:00', '{}')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO detections (execution_id, detector, detected, confidence)"
                " VALUES (1, 'schema', 1, 0.95)"
            )
        )
    old_engine.dispose()

    monkeypatch.setenv("PISAMA_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", url)
    import pisama_n8n_server.app as appmod
    from pisama_n8n_server.storage import Storage

    appmod._storage = Storage()
    c = TestClient(appmod.app)

    # The pre-existing row survives, reads seen_at None, and accepts a seen ping.
    rows = c.get("/api/v1/detections", headers=H).json()
    assert rows and rows[0]["seen_at"] is None
    r = c.post(f"/api/v1/detections/{rows[0]['id']}/seen", headers=H)
    assert r.status_code == 200 and r.json()["seen_at"]


# ── the comparison formula surfaces a real number ────────────────────────────

def test_recurrence_reduction_surfaces_non_null(tmp_path, monkeypatch):
    """No prior test ever observed recurrence_reduction non-null through the
    summary. Counters here are seeded (the observe path is covered elsewhere);
    what this pins is the pooled formula + gate surfacing a real number."""
    appmod, c = _client(tmp_path, monkeypatch)
    storage = appmod.get_storage()
    from pisama_n8n_server.storage import ReliabilityCase

    rid = _seed_repair(
        storage,
        guard_config={"kind": "input_schema"},
        applied=True,
        case_status="observing",
    )
    with storage._Session() as session:
        case = session.execute(
            select(ReliabilityCase).where(ReliabilityCase.repair_id == rid)
        ).scalar_one()
        case.baseline_execution_count = 10
        case.baseline_failure_count = 5
        case.post_repair_execution_count = 10
        case.post_repair_failure_count = 1
        session.commit()

    remediation = c.get("/api/v1/operations/summary", headers=H).json()[
        "reliability_metrics"
    ]["remediation"]
    assert remediation["comparison_cases"] == 1
    assert remediation["baseline_failure_rate"] == 0.5
    assert remediation["post_repair_failure_rate"] == 0.1
    assert remediation["recurrence_reduction"] == 0.8  # 1 - (0.1 / 0.5)
    assert "Pooled across 1" in remediation["recurrence_reduction_note"]
