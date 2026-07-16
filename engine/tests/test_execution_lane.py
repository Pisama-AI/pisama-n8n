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
        ("error.json", ["error", "error_workflow"]),
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


def test_loud_terminal_failure_yields_a_detection():
    """A crashed execution must never produce ZERO detections.

    Real-world regression (eval corpus rw_7e9aa5d6cc): a terminal single-node failure
    in an 8-node workflow tripped none of the hidden-error checks — no continueOnFail,
    no downstream turns, error rate 12.5% under the 15% threshold, and the
    success-despite-failures check suppresses itself once the workflow is marked
    failed. The execution_failure branch now covers loud failures.
    """
    from conftest import execution_doc

    run = {
        "executionTime": 5,
        "executionStatus": "success",
        "source": [{"previousNode": "Prev"}],
        "data": {"main": [[{"json": {"ok": True}}]]},
    }
    failing = dict(run, executionStatus="error", error={"message": "merge misconfig"})
    run_data = {f"N{i}": [dict(run)] for i in range(7)}
    run_data["Merge"] = [failing]
    raw = execution_doc(run_data, status="error", finished=False)

    turns, metadata = execution_to_turns_and_metadata(raw)
    report = analyze(turns=turns, metadata=metadata)
    assert "error" in fired_names(report)


def test_small_payload_growth_is_not_a_resource_failure():
    """The resource growth checks need an absolute floor: 41 -> 260 chars is a 6x
    ratio but trivially small (9 of 11 real-world false positives were ratio-only)."""
    from conftest import execution_doc

    def run_with(payload):
        return {
            "executionTime": 5,
            "executionStatus": "success",
            "source": [{"previousNode": "Prev"}],
            "data": {"main": [[{"json": payload}]]},
        }

    raw = execution_doc({
        "Start": [run_with({"a": 1})],
        "Shape": [run_with({"b": "x" * 60})],
        "Render": [run_with({"c": "y" * 200})],
    }, status="success", finished=True)
    turns, metadata = execution_to_turns_and_metadata(raw)
    report = analyze(turns=turns, metadata=metadata)
    assert "resource" not in fired_names(report)

    # Same shape but growing to a genuinely oversized payload still fires.
    raw_big = execution_doc({
        "Start": [run_with({"a": 1})],
        "Blow": [run_with({"c": "y" * 30000})],
    }, status="success", finished=True)
    turns, metadata = execution_to_turns_and_metadata(raw_big)
    report = analyze(turns=turns, metadata=metadata)
    assert "resource" in fired_names(report)
