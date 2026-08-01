"""Tests for the package's stable top-level interface."""

import json
from pathlib import Path

import pytest

from pisama_n8n_engine import (
    TAXONOMY_VERSION,
    Detection,
    DetectionReport,
    ExecutionAnalysis,
    analyze,
    analyze_execution,
)


REAL_EXECUTION = (
    Path(__file__).resolve().parents[2]
    / "server"
    / "tests"
    / "fixtures"
    / "executions"
    / "data_contract"
    / "CLOUD-112117-missing-required-value.json"
)


def test_top_level_api_is_importable():
    report = analyze(workflow_json={"nodes": [], "connections": {}})

    assert isinstance(report, DetectionReport)
    assert all(isinstance(detection, Detection) for detection in report.detections)
    assert TAXONOMY_VERSION == "1"


def test_analyze_execution_is_the_pure_real_execution_seam():
    payload = json.loads(REAL_EXECUTION.read_text())

    analysis = analyze_execution(payload)

    assert isinstance(analysis, ExecutionAnalysis)
    assert analysis.payload["id"] == "112117"
    assert analysis.report.workflow_id == "0H6n1fY53bCT6rhX"
    assert {item.failure_mode for item in analysis.report.fired} >= {
        "n8n_expression",
        "n8n_data_contract",
    }


def test_analyze_execution_rejects_an_unknown_shape():
    with pytest.raises(ValueError, match="Unrecognized execution payload"):
        analyze_execution("not an n8n execution")
