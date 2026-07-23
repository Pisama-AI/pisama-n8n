"""Tests for the package's stable top-level interface."""

from pisama_n8n_engine import Detection, DetectionReport, analyze


def test_top_level_api_is_importable():
    report = analyze(workflow_json={"nodes": [], "connections": {}})

    assert isinstance(report, DetectionReport)
    assert all(isinstance(detection, Detection) for detection in report.detections)
