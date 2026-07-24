#!/usr/bin/env python3
"""Extract the n8n detection engine from the Pisama monorepo into pisama_n8n_engine.

Single source of truth is the monorepo (backend/app/...); this script vendors a copy
with import paths rewritten to the standalone package namespace. It is the sync tool the
plan calls for: re-run it to pull detector improvements, and use ``--check`` from a
checkout that also has the Pisama monorepo to inspect source drift.

Usage:
    python scripts/extract_from_monorepo.py --monorepo /path/to/pisama
"""
import argparse
import re
import sys
from pathlib import Path

# (source rel to backend/app, target rel to engine/pisama_n8n_engine)
MANIFEST = [
    ("detection/turn_aware/_base.py", "detect/base.py"),
    ("core/n8n_utils.py", "detect/n8n_utils.py"),
    ("core/n8n_constants.py", "detect/n8n_constants.py"),
    ("detection/truncation.py", "detect/truncation.py"),
    ("detection/n8n/__init__.py", "detect/structural/__init__.py"),
    ("detection/n8n/cycle_detector.py", "detect/structural/cycle_detector.py"),
    ("detection/n8n/resource_detector.py", "detect/structural/resource_detector.py"),
    ("detection/n8n/complexity_detector.py", "detect/structural/complexity_detector.py"),
]

# Locally owned in pisama-n8n and deliberately NOT re-extracted. The structural
# detectors use the standalone runtime classifier, and the universal trace module
# provides a dependency-free StateSnapshot compatibility type. Re-extracting these
# files would restore monorepo-only imports and break standalone installs.
LOCAL_OVERRIDES = (
    "trace/universal_trace.py",
    "detect/structural/schema_detector.py",
    "detect/structural/timeout_detector.py",
    "detect/structural/error_detector.py",
)

# import-path rewrites (longest-prefix first)
REWRITES = [
    (r"app\.ingestion\.universal_trace", "pisama_n8n_engine.trace.universal_trace"),
    (r"app\.detection\.turn_aware\._base", "pisama_n8n_engine.detect.base"),
    (r"app\.detection\.truncation", "pisama_n8n_engine.detect.truncation"),
    (r"app\.detection\.n8n", "pisama_n8n_engine.detect.structural"),
    (r"app\.core\.n8n_utils", "pisama_n8n_engine.detect.n8n_utils"),
    (r"app\.core\.n8n_constants", "pisama_n8n_engine.detect.n8n_constants"),
]

BANNER = "# VENDORED from the pisama monorepo by scripts/extract_from_monorepo.py — do not edit here.\n"


def rewrite(text: str) -> str:
    for pat, repl in REWRITES:
        text = re.sub(pat, repl, text)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--monorepo", required=True, type=Path)
    ap.add_argument("--check", action="store_true",
                    help="Exit non-zero if the vendored copy differs from a fresh extract (drift gate).")
    args = ap.parse_args()

    app_dir = args.monorepo / "backend" / "app"
    if not app_dir.exists():
        print(f"ERROR: {app_dir} not found", file=sys.stderr)
        return 2

    engine = Path(__file__).resolve().parent.parent / "engine" / "pisama_n8n_engine"
    drift = []
    for src_rel, dst_rel in MANIFEST:
        src = app_dir / src_rel
        if not src.exists():
            print(f"ERROR: source missing: {src}", file=sys.stderr)
            return 2
        dst = engine / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        new = BANNER + rewrite(src.read_text())
        if args.check:
            if not dst.exists() or dst.read_text() != new:
                drift.append(dst_rel)
        else:
            dst.write_text(new)
            print(f"  {src_rel}  ->  {dst_rel}")

    if args.check:
        if drift:
            print("DRIFT: vendored copies differ from the monorepo source:", file=sys.stderr)
            for d in drift:
                print(f"  {d}", file=sys.stderr)
            return 1
        print("OK: vendored engine matches the monorepo source.")
        return 0
    print(f"\nExtracted {len(MANIFEST)} files into {engine}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
