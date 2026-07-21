"""DB-level dedup of upstream execution ids (closes the poll/sync race).

The poller's seen-set check is read-then-insert: a background poll overlapping a
manual /sync can both pass the check and insert the same upstream execution. These
tests pin the layer that makes the dedup guarantee real regardless of interleaving:

  - a partial unique index on executions.source_execution_id, created at startup
    AFTER collapsing any duplicates a pre-index database already accumulated;
  - the DuplicateSourceExecution signal save_report raises for the losing writer,
    which poll_once treats as already-ingested (not a failure, not "new");
  - the full-window clip warning: a poll that fills its entire fetch window may
    have missed executions that rolled past, and must say so.

No mocks beyond the n8n client seam the polling tests already use.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest
from sqlalchemy import text

FIXTURES = Path(__file__).parent / "fixtures"


class _Report:
    """Minimal stand-in for an engine report at the storage boundary."""

    def __init__(self, workflow_id="wf-dedup"):
        self.workflow_id = workflow_id
        self.detections = []


def _storage(tmp_path, monkeypatch, name="dedup.db"):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / name}")
    from pisama_n8n_server.storage import Storage

    return Storage()


def test_second_insert_with_same_source_id_is_refused(tmp_path, monkeypatch):
    from pisama_n8n_server.storage import DuplicateSourceExecution

    s = _storage(tmp_path, monkeypatch)
    first = s.save_report({"workflowId": "wf"}, _Report(), source_execution_id="777")
    with pytest.raises(DuplicateSourceExecution) as exc:
        s.save_report({"workflowId": "wf"}, _Report(), source_execution_id="777")
    assert exc.value.existing_id == first
    # Webhook pushes carry no upstream id and stay unconstrained.
    assert s.save_report({"workflowId": "wf"}, _Report()) != first
    s.save_report({"workflowId": "wf"}, _Report())


def test_startup_collapses_historical_duplicates(tmp_path, monkeypatch):
    """A database written before the unique index existed can hold real duplicate
    rows; index creation would fail on them. Startup keeps the earliest row (the
    one reliability observation already counted) and drops the rest with their
    detections."""
    s = _storage(tmp_path, monkeypatch, "legacy.db")
    with s.engine.begin() as conn:
        conn.execute(text("DROP INDEX uq_executions_source"))
        for _ in range(3):
            conn.execute(
                text(
                    "INSERT INTO executions (workflow_id, received_at, raw, "
                    "source_execution_id) VALUES ('wf', 't', '{}', 'dup-1')"
                )
            )
        ids = [
            row[0]
            for row in conn.execute(
                text("SELECT id FROM executions WHERE source_execution_id = 'dup-1'")
            )
        ]
        for i in ids:
            conn.execute(
                text(
                    "INSERT INTO detections (execution_id, detector, detected, "
                    f"confidence, explanation, evidence) VALUES ({i}, 'error', 1, "
                    "1.0, '', '{}')"
                )
            )

    from pisama_n8n_server.storage import Storage

    s2 = Storage()  # same DATABASE_URL; startup ensure runs again
    with s2.engine.begin() as conn:
        kept = [
            row[0]
            for row in conn.execute(
                text("SELECT id FROM executions WHERE source_execution_id = 'dup-1'")
            )
        ]
        assert kept == [min(ids)]
        det_execs = {
            row[0]
            for row in conn.execute(text("SELECT execution_id FROM detections"))
        }
        assert det_execs == {min(ids)}
        # And the index now enforces what the cleanup restored.
        with pytest.raises(Exception):
            conn.execute(
                text(
                    "INSERT INTO executions (workflow_id, received_at, raw, "
                    "source_execution_id) VALUES ('wf', 't', '{}', 'dup-1')"
                )
            )


class _FakeN8n:
    """The client seam poll_once needs; workflow lookups fail gracefully."""

    def __init__(self, executions):
        self._executions = executions

    async def list_executions(self, limit=50, include_data=True, workflow_id=None):
        return [json.loads(json.dumps(e)) for e in self._executions[:limit]]

    async def get_workflow(self, workflow_id):
        raise RuntimeError("no workflow lookups in this test")


def _error_execution(exec_id: str):
    fx = json.loads((FIXTURES / "executions/error/ERROR-01-throw.json").read_text())
    fx["id"] = exec_id
    return fx


def test_poll_counts_a_raced_duplicate_once(tmp_path, monkeypatch):
    """The same upstream id appearing twice past the seen-set check (exactly what
    an overlapping poll produces) stores ONE row and counts ONE new execution."""
    from pisama_n8n_server.poller import poll_once

    s = _storage(tmp_path, monkeypatch, "race.db")
    client = _FakeN8n([_error_execution("9001"), _error_execution("9001")])
    summary = asyncio.run(poll_once(client, s, limit=10))
    assert summary["new"] == 1
    with s.engine.begin() as conn:
        rows = conn.execute(
            text("SELECT COUNT(*) FROM executions WHERE source_execution_id = '9001'")
        ).scalar()
        assert rows == 1


def test_full_fetch_window_logs_clip_warning(tmp_path, monkeypatch, caplog):
    from pisama_n8n_server.poller import poll_once

    s = _storage(tmp_path, monkeypatch, "clip.db")
    executions = [_error_execution("8001"), _error_execution("8002")]

    with caplog.at_level(logging.WARNING, logger="pisama_n8n_server"):
        asyncio.run(poll_once(_FakeN8n(executions), s, limit=2))
    assert any("full window" in r.message for r in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="pisama_n8n_server"):
        asyncio.run(poll_once(_FakeN8n([_error_execution("8003")]), s, limit=2))
    assert not any("full window" in r.message for r in caplog.records)
