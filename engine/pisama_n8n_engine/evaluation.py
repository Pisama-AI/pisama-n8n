"""Multi-label scoring for independently labeled n8n executions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Set, Tuple

from pisama_n8n_engine.orchestrator import analyze_execution

LabeledExecution = Tuple[str, Any, Set[str]]


@dataclass
class ModeCounts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def metrics(self) -> Dict[str, Optional[float]]:
        precision = _ratio(self.tp, self.tp + self.fp)
        recall = _ratio(self.tp, self.tp + self.fn)
        return {"precision": precision, "recall": recall, "f1": _f1(precision, recall)}

    def observe(self, wanted: bool, fired: bool) -> None:
        if wanted and fired:
            self.tp += 1
        elif wanted:
            self.fn += 1
        elif fired:
            self.fp += 1
        else:
            self.tn += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "tn": self.tn,
            **self.metrics(),
        }


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    return numerator / denominator if denominator else None


def _f1(
    precision: Optional[float], recall: Optional[float]
) -> Optional[float]:
    if precision is None or recall is None:
        return None
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def _case_result(case_id: str, payload: Any, expected: Set[str]) -> Dict[str, Any]:
    actual = {
        detection.failure_mode
        for detection in analyze_execution(payload).report.fired
        if detection.failure_mode
    }
    return {
        "id": case_id,
        "expected_modes": sorted(expected),
        "actual_modes": sorted(actual),
        "missing_modes": sorted(expected - actual),
        "unexpected_modes": sorted(actual - expected),
        "exact_match": expected == actual,
    }


def _evaluate_cases(cases: Iterable[LabeledExecution]) -> list[Dict[str, Any]]:
    results = []
    seen_ids = set()
    for case_id, payload, expected in cases:
        if case_id in seen_ids:
            raise ValueError(f"Duplicate evaluation case id: {case_id}")
        seen_ids.add(case_id)
        results.append(_case_result(case_id, payload, set(expected)))
    return results


def _count_modes(case_results: list[Dict[str, Any]]) -> Dict[str, ModeCounts]:
    all_modes = {
        mode
        for result in case_results
        for mode in result["expected_modes"] + result["actual_modes"]
    }
    per_mode = {mode: ModeCounts() for mode in sorted(all_modes)}
    for result in case_results:
        expected = set(result["expected_modes"])
        actual = set(result["actual_modes"])
        for mode, counts in per_mode.items():
            counts.observe(mode in expected, mode in actual)
    return per_mode


def _sum_counts(per_mode: Dict[str, ModeCounts]) -> ModeCounts:
    return ModeCounts(
        tp=sum(counts.tp for counts in per_mode.values()),
        fp=sum(counts.fp for counts in per_mode.values()),
        fn=sum(counts.fn for counts in per_mode.values()),
        tn=sum(counts.tn for counts in per_mode.values()),
    )


def _macro_metrics(per_mode: Dict[str, ModeCounts]) -> Dict[str, Optional[float]]:
    result = {}
    for metric in ("precision", "recall", "f1"):
        values = [
            value
            for counts in per_mode.values()
            if (value := counts.metrics()[metric]) is not None
        ]
        result[metric] = sum(values) / len(values) if values else None
    return result


def score_labeled_executions(cases: Iterable[LabeledExecution]) -> Dict[str, Any]:
    """Score exact failure-mode sets and per-mode classification metrics."""
    case_results = _evaluate_cases(cases)
    if not case_results:
        raise ValueError("At least one labeled execution is required.")
    per_mode = _count_modes(case_results)
    exact_matches = sum(result["exact_match"] for result in case_results)
    return {
        "n": len(case_results),
        "exact_set_matches": exact_matches,
        "exact_set_accuracy": exact_matches / len(case_results),
        "micro": _sum_counts(per_mode).to_dict(),
        "macro": _macro_metrics(per_mode),
        "per_mode": {mode: counts.to_dict() for mode, counts in per_mode.items()},
        "cases": case_results,
    }
