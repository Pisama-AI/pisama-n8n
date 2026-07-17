"""Orchestrator contract: lane selection, report shape, and the per-detector safety net."""
from __future__ import annotations

from pisama_n8n_engine.orchestrator import analyze

from conftest import chain_workflow, fired_names

STRUCTURAL = {"cycle", "complexity"}
EXECUTION = {
    "schema", "timeout", "error", "resource", "truncation", "retry_recovery",
    "error_workflow", "agent_diagnostics",
}


def test_no_inputs_runs_no_lane():
    report = analyze()
    assert report.detections == []
    assert report.fired == []


def test_workflow_json_runs_only_structural_lane():
    report = analyze(workflow_json=chain_workflow(3))
    assert {d.detector for d in report.detections} == STRUCTURAL
    assert fired_names(report) == []


def test_turns_runs_only_execution_lane():
    report = analyze(turns=[])
    assert {d.detector for d in report.detections} == EXECUTION


def test_both_inputs_run_both_lanes():
    report = analyze(workflow_json=chain_workflow(3), turns=[])
    assert {d.detector for d in report.detections} == STRUCTURAL | EXECUTION


def test_workflow_id_passthrough_and_to_dict():
    report = analyze(workflow_json=chain_workflow(2), workflow_id="wf-42")
    assert report.workflow_id == "wf-42"
    d = report.to_dict()
    assert d["workflow_id"] == "wf-42"
    assert {row["detector"] for row in d["detections"]} == STRUCTURAL
    # Every detection row is JSON-shaped: plain keys, typed fields.
    for row in d["detections"]:
        assert isinstance(row["detected"], bool)
        assert isinstance(row["confidence"], float)


def test_detector_exception_does_not_sink_the_run():
    # An int is not a workflow document; every structural detector raises internally.
    # The orchestrator must still return one non-fired entry per detector, with the
    # error surfaced in the explanation, instead of propagating.
    report = analyze(workflow_json=42)  # type: ignore[arg-type]
    assert {d.detector for d in report.detections} == STRUCTURAL
    for d in report.detections:
        assert d.detected is False
        assert d.explanation.startswith("error:")


def test_fired_property_filters_to_detected():
    report = analyze(workflow_json=chain_workflow(50))
    assert [d.detector for d in report.fired] == ["complexity"]
    assert all(d.detected for d in report.fired)
