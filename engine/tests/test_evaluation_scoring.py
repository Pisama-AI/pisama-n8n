import json
from pathlib import Path

import pytest

from pisama_n8n_engine import score_labeled_executions

ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "eval" / "closed_loop_cases.json"


def _manifest_cases():
    manifest = json.loads(MANIFEST.read_text())
    return [
        (
            case["id"],
            json.loads((ROOT / case["payload_path"]).read_text()),
            set(case["expected_modes"]),
        )
        for case in manifest["cases"]
    ]


def test_real_execution_manifest_has_exact_multi_label_parity():
    result = score_labeled_executions(_manifest_cases())

    assert result["n"] == 19
    assert result["exact_set_accuracy"] == 1.0
    assert result["micro"]["precision"] == 1.0
    assert result["micro"]["recall"] == 1.0
    assert result["per_mode"]["F13"]["tp"] == 4
    assert result["per_mode"]["F6"]["tp"] == 4
    assert any(len(case["expected_modes"]) == 3 for case in result["cases"])


def test_scoring_reports_missing_mode_without_fabricating_precision():
    case_id, payload, _ = _manifest_cases()[6]
    result = score_labeled_executions([(case_id, payload, {"F13"})])

    assert result["exact_set_accuracy"] == 0.0
    assert result["per_mode"]["F13"] == {
        "tp": 0,
        "fp": 0,
        "fn": 1,
        "tn": 0,
        "precision": None,
        "recall": 0.0,
        "f1": None,
    }
    assert result["cases"][0]["missing_modes"] == ["F13"]


def test_scoring_rejects_duplicate_case_ids():
    case = _manifest_cases()[0]
    with pytest.raises(ValueError, match="Duplicate evaluation case id"):
        score_labeled_executions([case, case])
