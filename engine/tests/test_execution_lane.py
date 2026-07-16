"""Execution-lane detectors on the real captured n8n executions.

Each fixture is a genuine execution captured from a live n8n instance (the same corpus
the golden parity gate freezes); here we assert the full parse -> detect path yields
exactly the expected verdict per lane, and stays silent on the healthy run.
"""
from __future__ import annotations

import pytest

from pisama_n8n_engine.orchestrator import analyze
from pisama_n8n_engine.trace.execution import execution_to_turns_and_metadata

from conftest import fired_names, load_execution


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("timeout.json", ["timeout"]),
        ("error.json", ["error"]),
        ("resource.json", ["resource"]),
        ("healthy.json", []),
    ],
)
def test_real_execution_verdicts(bench_fixtures, fixture, expected):
    raw = load_execution(bench_fixtures, fixture)
    turns, metadata = execution_to_turns_and_metadata(raw)
    report = analyze(turns=turns, metadata=metadata)
    assert fired_names(report) == expected


def test_healthy_execution_produces_turns_but_no_fires(bench_fixtures):
    # Guard against the degenerate "nothing fired because nothing parsed" pass.
    raw = load_execution(bench_fixtures, "healthy.json")
    turns, metadata = execution_to_turns_and_metadata(raw)
    assert len(turns) > 0
    assert metadata["workflow_duration_ms"] >= 0
    assert not any(t.turn_metadata["has_error"] for t in turns)


def test_error_execution_carries_the_error_turn(bench_fixtures):
    raw = load_execution(bench_fixtures, "error.json")
    turns, _ = execution_to_turns_and_metadata(raw)
    error_turns = [t for t in turns if t.turn_metadata["has_error"]]
    assert error_turns, "the captured error execution must yield at least one error turn"
    assert any("ERROR" in t.content for t in error_turns)
