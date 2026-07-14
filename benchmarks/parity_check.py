#!/usr/bin/env python3
"""Parity gate: the extracted engine must produce identical detections to the monorepo.

This is the guard that lets the monorepo remain the single source of truth. Re-run after
any re-extraction; CI fails the build on any mismatch. Run the MONOREPO side under its own
venv + JWT_SECRET (its detectors import the full app config); the engine side needs nothing.

Usage:
    JWT_SECRET=<clean-random-32+> \
    PYTHONPATH=<monorepo>/backend:<repo>/engine \
    <monorepo>/backend/.venv/bin/python benchmarks/parity_check.py --monorepo <monorepo>
"""
import argparse
import glob
import json
import sys
from pathlib import Path


def load(p: str) -> dict:
    d = json.load(open(p))
    return d if "nodes" in d else (d.get("workflow") or d.get("workflowData") or d)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--monorepo", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    from pisama_n8n_engine.orchestrator import analyze
    from app.detection.n8n import (
        N8NCycleDetector, N8NSchemaDetector, N8NComplexityDetector,
    )

    mono = {"cycle": N8NCycleDetector(), "schema": N8NSchemaDetector(),
            "complexity": N8NComplexityDetector()}
    backend = args.monorepo / "backend"
    workflows = (glob.glob(str(backend / "data/external/n8n_templates/*.json"))[:args.limit]
                 + glob.glob(str(args.monorepo / "n8n-workflows/complexity/*.json")))

    mismatch = total = 0
    for p in workflows:
        wf = load(p)
        eng = {d.detector: d.detected for d in analyze(workflow_json=wf).detections}
        for name, det in mono.items():
            m = det.detect_workflow(wf).detected
            e = eng.get(name)
            total += 1
            if m != e:
                mismatch += 1
                print(f"  MISMATCH {name} on {Path(p).name}: mono={m} engine={e}")

    print(f"Parity: {total - mismatch}/{total} identical structural verdicts "
          f"({mismatch} mismatches)")
    if mismatch:
        print("FAIL: extracted engine diverged from the monorepo — re-extract.")
        return 1
    print("PASS: extracted engine matches the monorepo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
