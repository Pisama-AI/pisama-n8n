#!/usr/bin/env python3
"""Score the closed-loop manifest against the pure Pisama evaluation engine."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

from pisama_n8n_engine import FAILURE_MODES, TAXONOMY_VERSION
from pisama_n8n_engine.evaluation import score_labeled_executions

MANIFEST_SCHEMA_VERSION = "1"
DEFAULT_MANIFEST = Path(__file__).with_name("closed_loop_cases.json")


def load_manifest(path: Path, split: Optional[str] = None) -> Dict[str, Any]:
    manifest = json.loads(path.read_text())
    _validate_manifest_versions(manifest)
    repo_root = path.resolve().parent.parent
    selected = _select_cases(manifest.get("cases") or [], split)
    if not selected:
        raise ValueError(f"No cases selected from {path}.")
    prepared = [_prepare_case(case, repo_root) for case in selected]
    labeled = [item[0] for item in prepared]
    result = score_labeled_executions(labeled)
    result.update(
        {
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
            "taxonomy_version": TAXONOMY_VERSION,
            "manifest": str(path),
            "split": split or "all",
            "case_provenance": {
                case_id: provenance for _, (case_id, provenance) in prepared
            },
        }
    )
    return result


def _validate_manifest_versions(manifest: Dict[str, Any]) -> None:
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("Unsupported or missing manifest schema_version.")
    if manifest.get("taxonomy_version") != TAXONOMY_VERSION:
        raise ValueError("Manifest taxonomy_version does not match the engine.")


def _select_cases(cases: list[Any], split: Optional[str]) -> list[Dict[str, Any]]:
    selected = []
    for case in cases:
        _validate_case(case)
        if split is None or case["split"] == split:
            selected.append(case)
    return selected


def _prepare_case(case: Dict[str, Any], repo_root: Path):
    payload, reference = _load_payload(case, repo_root)
    labeled = (case["id"], payload, set(case["expected_modes"]))
    provenance = {
        "payload": reference,
        "split": case["split"],
        "source": case["source"],
        "label_evidence": case["label_evidence"],
    }
    return labeled, (case["id"], provenance)


def _load_payload(case: Dict[str, Any], repo_root: Path):
    if "payload_path" not in case:
        return case["payload"], "inline credential-redacted execution"
    payload_path = repo_root / case["payload_path"]
    if not payload_path.is_file():
        raise ValueError(f"Missing payload for {case['id']}: {payload_path}")
    return json.loads(payload_path.read_text()), case["payload_path"]


def _validate_case(case: Any) -> None:
    if not isinstance(case, dict):
        raise ValueError("Every evaluation case must be an object.")
    _validate_text_fields(case)
    _validate_payload_reference(case)
    _validate_modes(case)
    _validate_provenance(case)


def _validate_text_fields(case: Dict[str, Any]) -> None:
    for field in ("id", "split"):
        if not isinstance(case.get(field), str) or not case[field].strip():
            raise ValueError(f"Evaluation case has an invalid {field}.")


def _validate_payload_reference(case: Dict[str, Any]) -> None:
    has_path = isinstance(case.get("payload_path"), str) and bool(
        case["payload_path"].strip()
    )
    has_inline = isinstance(case.get("payload"), (dict, list))
    if has_path == has_inline:
        raise ValueError(
            f"Case {case['id']} must have exactly one payload_path or inline payload."
        )


def _validate_modes(case: Dict[str, Any]) -> None:
    modes = case.get("expected_modes")
    if not isinstance(modes, list) or any(
        not isinstance(mode, str) or not mode for mode in modes
    ):
        raise ValueError(f"Case {case['id']} has invalid expected_modes.")
    if len(modes) != len(set(modes)):
        raise ValueError(f"Case {case['id']} repeats an expected mode.")
    unknown = sorted(set(modes) - FAILURE_MODES)
    if unknown:
        raise ValueError(f"Case {case['id']} uses unknown failure modes: {unknown}")


def _validate_provenance(case: Dict[str, Any]) -> None:
    source = case.get("source")
    if not isinstance(source, dict) or not source.get("capture"):
        raise ValueError(f"Case {case['id']} is missing source provenance.")
    evidence = case.get("label_evidence")
    if not isinstance(evidence, list) or not evidence or any(
        not isinstance(item, str) or not item.strip() for item in evidence
    ):
        raise ValueError(f"Case {case['id']} is missing independent label evidence.")


def _print_summary(result: Dict[str, Any]) -> None:
    print(
        f"closed-loop eval: {result['exact_set_matches']}/{result['n']} exact sets "
        f"({result['exact_set_accuracy']:.1%}), split={result['split']}"
    )
    print("mode                              TP  FP  FN  precision  recall")
    for mode, metrics in result["per_mode"].items():
        precision = "n/a" if metrics["precision"] is None else f"{metrics['precision']:.2f}"
        recall = "n/a" if metrics["recall"] is None else f"{metrics['recall']:.2f}"
        print(
            f"{mode:32} {metrics['tp']:3} {metrics['fp']:3} {metrics['fn']:3} "
            f"{precision:>9} {recall:>7}"
        )
    mismatches = [case for case in result["cases"] if not case["exact_match"]]
    for case in mismatches:
        print(
            f"MISMATCH {case['id']}: missing={case['missing_modes']} "
            f"unexpected={case['unexpected_modes']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--split", help="only score one named manifest split")
    parser.add_argument("--json", type=Path, help="write the full machine-readable report")
    parser.add_argument(
        "--require-exact",
        action="store_true",
        help="return non-zero when any case has a missing or unexpected mode",
    )
    args = parser.parse_args()
    try:
        result = load_manifest(args.manifest, split=args.split)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"closed-loop eval refused to score: {exc}")
        return 2
    _print_summary(result)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(f"wrote {args.json}")
    return 1 if args.require_exact and result["exact_set_accuracy"] != 1.0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
