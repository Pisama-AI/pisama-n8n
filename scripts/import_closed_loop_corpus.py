#!/usr/bin/env python3
"""Import the repository's reviewed real-execution corpus into Pisama storage."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from pisama_n8n_engine import FAILURE_MODES, TAXONOMY_VERSION
from pisama_n8n_server.processing import process_evaluation_ingest
from pisama_n8n_server.storage import Storage, execution_payload_sha256


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def import_corpus(root: Path, manifest_path: Path, database_url: str) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("taxonomy_version") != TAXONOMY_VERSION:
        raise ValueError(
            f"Corpus taxonomy v{manifest.get('taxonomy_version')} does not match "
            f"engine taxonomy v{TAXONOMY_VERSION}."
        )
    manifest_sha256 = hashlib.sha256(_canonical(manifest).encode("utf-8")).hexdigest()
    dataset_id = f"closed-loop-corpus:{manifest_sha256}"
    storage = Storage(url=database_url)
    imported = []
    try:
        for case in manifest["cases"]:
            unknown = sorted(set(case["expected_modes"]) - FAILURE_MODES)
            if unknown:
                raise ValueError(f"Case {case['id']} has unknown modes: {unknown}")
            payload = json.loads(
                (root / case["payload_path"]).read_text(encoding="utf-8")
            )
            source_hash = execution_payload_sha256(_canonical(payload))
            expected_hash = case["source"]["payload_sha256"]
            if source_hash != expected_hash:
                raise ValueError(
                    f"Case {case['id']} source hash mismatch: {source_hash} != "
                    f"{expected_hash}"
                )
            retained = process_evaluation_ingest(
                payload,
                storage,
                dataset_id,
                case["id"],
            )
            split = "holdout" if case["split"] == "legacy_holdout" else case["split"]
            if split not in {"regression", "holdout"}:
                raise ValueError(
                    f"Case {case['id']} has unsupported split {case['split']}"
                )
            provenance = {
                "manifest_sha256": manifest_sha256,
                "manifest_schema_version": manifest["schema_version"],
                "original_split": case["split"],
                "payload_path": case["payload_path"],
                "source": case["source"],
                "source_payload_sha256": source_hash,
                "retained_payload_sha256": retained["payload_sha256"],
            }
            imported.append(
                storage.import_corpus_evaluation_case(
                    retained["execution_id"],
                    case["id"],
                    case["expected_modes"],
                    split,
                    "\n".join(case["label_evidence"]),
                    manifest["taxonomy_version"],
                    provenance,
                    f"corpus:{manifest_sha256}",
                )
            )
    finally:
        storage.close()
    by_split: dict[str, int] = {}
    for case in imported:
        by_split[case["split"]] = by_split.get(case["split"], 0) + 1
    return {
        "manifest_sha256": manifest_sha256,
        "case_count": len(imported),
        "by_split": by_split,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=root / "eval" / "closed_loop_cases.json",
    )
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    result = import_corpus(root, args.manifest.resolve(), args.database_url)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
