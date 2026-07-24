"""Active parser contract against a captured n8n Cloud execution.

Execution 112117 was exported from n8n Cloud before its workflow was repaired.
It is sanitized at the source and exercises the same public-API payload shape an
external self-host user submits to the server.
"""

import json
from pathlib import Path

from pisama_n8n_engine import analyze
from pisama_n8n_engine.trace.execution import execution_to_turns_and_metadata


CAPTURE = (
    Path(__file__).resolve().parents[2]
    / "server"
    / "tests"
    / "fixtures"
    / "executions"
    / "data_contract"
    / "CLOUD-112117-missing-required-value.json"
)


def test_cloud_execution_preserves_order_runtime_error_and_workflow_context():
    execution = json.loads(CAPTURE.read_text())

    turns, metadata = execution_to_turns_and_metadata(execution)

    assert [turn.participant_id for turn in turns] == [
        "Baseline webhook",
        "Observed missing field",
    ]
    assert [turn.turn_number for turn in turns] == [0, 1]
    assert turns[1].turn_metadata["source_nodes"] == ["Baseline webhook"]
    assert turns[1].turn_metadata["execution_time_ms"] == 1468
    assert turns[1].turn_metadata["has_error"] is True
    assert turns[1].turn_metadata["error_message"] == (
        "Cannot read properties of undefined (reading 'value') [line 1]"
    )
    assert metadata["execution_id"] == "112117"
    assert metadata["workflow_id"] == "0H6n1fY53bCT6rhX"
    assert metadata["workflow_status"] == "error"
    assert metadata["workflow_duration_ms"] == 1468
    assert metadata["workflow_available"] is True


def test_cloud_execution_reaches_the_schema_detector_with_auditable_evidence():
    execution = json.loads(CAPTURE.read_text())
    turns, metadata = execution_to_turns_and_metadata(execution)

    report = analyze(turns=turns, metadata=metadata)
    schema = next(item for item in report.detections if item.detector == "schema")

    assert schema.detected is True
    assert schema.failure_mode == "n8n_data_contract"
    assert schema.evidence["issues"] == [
        {
            "node": "Observed missing field",
            "turn": 1,
            "message": "Cannot read properties of undefined (reading 'value') [line 1]",
        }
    ]
