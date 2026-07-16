#!/usr/bin/env python3
"""Parity / regression gate for the extracted pisama-n8n engine.

The detectors are vendored from the Pisama monorepo (the single source of truth) via
`scripts/extract_from_monorepo.py`. This gate freezes the vendored engine's behaviour on a
committed corpus (`benchmarks/fixtures/`) so a regression, or a botched re-extraction, fails
the build.

Modes
-----
Default (what CI runs; needs only the installed engine, no monorepo, no network):

    python benchmarks/parity_check.py

  Runs the engine on every fixture under `benchmarks/fixtures/` and asserts the fired
  detectors match `benchmarks/golden.json` exactly.

`--update-golden`
  Regenerate `benchmarks/golden.json` from the current engine, then review the diff before
  committing. Use after an intentional detector change plus a re-extraction.

`--monorepo <path>`
  Maintainer cross-check. Also runs the MONOREPO structural detectors (the source of truth)
  on the structural fixtures and asserts engine == monorepo. Needs the precision-fixed
  detector branch on disk, a clean `JWT_SECRET`, and `PYTHONPATH=<monorepo>/backend`. Run it
  after re-vendoring; if it fails, re-extract and `--update-golden`. This mode cannot run in
  the public repo's CI (the monorepo is private), which is exactly why the golden exists.

Exit code 0 = parity holds, 1 = mismatch.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # benchmarks/
FIXTURES = ROOT / "fixtures"
GOLDEN = ROOT / "golden.json"


def _load_workflow(path: Path) -> dict:
    d = json.loads(path.read_text())
    return d.get("workflow") or d.get("workflowData") or d


def _iter_fixtures():
    """Yield (relative_key, absolute_path, kind) for every committed fixture, sorted.

    `structural/*` fixtures are n8n workflow JSON (run through the workflow-JSON lane);
    everything else is an n8n execution record (run through the runtime lane).
    """
    for p in sorted(FIXTURES.rglob("*.json")):
        rel = p.relative_to(FIXTURES).as_posix()
        kind = "structural" if rel.startswith("structural/") else "execution"
        yield rel, p, kind


def _engine_fired(path: Path, kind: str) -> list:
    from pisama_n8n_engine.orchestrator import analyze

    if kind == "structural":
        report = analyze(workflow_json=_load_workflow(path))
    else:
        from pisama_n8n_engine.trace.execution import execution_to_turns_and_metadata

        turns, metadata = execution_to_turns_and_metadata(json.loads(path.read_text()))
        report = analyze(turns=turns, metadata=metadata)
    return sorted(d.detector for d in report.detections if getattr(d, "detected", False))


def _compute_golden() -> dict:
    return {rel: _engine_fired(path, kind) for rel, path, kind in _iter_fixtures()}


def _write_golden(golden: dict) -> None:
    GOLDEN.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n")


def _check_against_golden() -> int:
    if not GOLDEN.exists():
        print(f"FAIL: {GOLDEN} is missing — run with --update-golden first.")
        return 1
    golden = json.loads(GOLDEN.read_text())
    fixtures = list(_iter_fixtures())
    if not fixtures:
        print(f"FAIL: no fixtures under {FIXTURES} — the gate would be vacuous.")
        return 1
    mismatch = 0
    seen = set()
    for rel, path, kind in fixtures:
        seen.add(rel)
        expected = golden.get(rel)
        actual = _engine_fired(path, kind)
        if expected is None:
            print(f"  MISSING GOLDEN for {rel}: engine fired {actual}")
            mismatch += 1
        elif sorted(expected) != actual:
            print(f"  MISMATCH {rel}: golden={sorted(expected)} engine={actual}")
            mismatch += 1
    for rel in golden:
        if rel not in seen:
            print(f"  STALE GOLDEN entry (no matching fixture): {rel}")
            mismatch += 1
    total = len(fixtures)
    print(f"Golden parity: {total - mismatch}/{total} fixtures match ({mismatch} mismatches).")
    return 1 if mismatch else 0


def _check_against_monorepo(monorepo: Path) -> int:
    """Assert engine == monorepo on the structural fixtures (maintainer cross-check)."""
    from pisama_n8n_engine.orchestrator import analyze

    try:
        from app.detection.n8n import (
            N8NComplexityDetector,
            N8NCycleDetector,
            N8NSchemaDetector,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"FAIL: cannot import monorepo detectors ({exc!r}). "
            f"Set PYTHONPATH={monorepo}/backend and a clean JWT_SECRET, and use the "
            f"precision-fixed detector branch."
        )
        return 1
    mono = {
        "cycle": N8NCycleDetector(),
        "schema": N8NSchemaDetector(),
        "complexity": N8NComplexityDetector(),
    }
    mismatch = total = 0
    for rel, path, kind in _iter_fixtures():
        if kind != "structural":
            continue
        wf = _load_workflow(path)
        engine = {d.detector: d.detected for d in analyze(workflow_json=wf).detections}
        for name, det in mono.items():
            total += 1
            m = bool(det.detect_workflow(wf).detected)
            e = bool(engine.get(name))
            if m != e:
                mismatch += 1
                print(f"  MISMATCH {name} on {rel}: monorepo={m} engine={e}")
    print(
        f"Monorepo parity: {total - mismatch}/{total} structural verdicts identical "
        f"({mismatch} mismatches)."
    )
    return 1 if mismatch else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Parity/regression gate for the extracted engine.",
    )
    ap.add_argument(
        "--update-golden",
        action="store_true",
        help="Regenerate benchmarks/golden.json from the current engine.",
    )
    ap.add_argument(
        "--monorepo",
        type=Path,
        default=None,
        help="Path to a monorepo checkout for the live engine-vs-monorepo cross-check.",
    )
    args = ap.parse_args()

    if args.update_golden:
        golden = _compute_golden()
        _write_golden(golden)
        print(f"Wrote {GOLDEN} ({len(golden)} fixtures). Review the diff before committing:")
        for rel, fired in sorted(golden.items()):
            print(f"  {rel}: {fired}")
        return 0

    rc = _check_against_golden()
    if args.monorepo is not None:
        rc |= _check_against_monorepo(args.monorepo)
    print("PASS" if rc == 0 else "FAIL")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
