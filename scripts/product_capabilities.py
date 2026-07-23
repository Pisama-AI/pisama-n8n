#!/usr/bin/env python3
"""Keep n8n consumers synchronized with Pisama's canonical product manifest."""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_SOURCE = ROOT.parent / "pisama" / "product" / "capabilities.json"
TARGETS = (
    ROOT / "dashboard" / "src" / "data" / "product-capabilities.generated.json",
    ROOT / "server" / "pisama_n8n_server" / "product_capabilities.generated.json",
)
CANONICAL_URL = "https://pisama.ai/product-capabilities.json"
REQUIRED_CAPABILITY_IDS = {
    "local_heuristic_detection",
    "evidence_backed_diagnosis",
    "deterministic_repairs",
    "model_generated_fixes",
    "advanced_detection",
    "managed_operations",
    "team_governance",
}
PUBLIC_CLAIMS = {
    ROOT / "README.md": {
        "Local heuristic detection",
        "Evidence-backed diagnosis",
        "Deterministic repairs",
        "Model-generated fixes",
        "Advanced detection",
        "Managed operations",
        "Team governance",
        'NOT OSI "open source"',
    },
    ROOT / "dashboard" / "src" / "app" / "page.tsx": {
        "product-capabilities.generated.json",
        "Compare the full Pisama product family",
    },
    ROOT / "server" / "README.md": {
        "Fair-code",
        "Deterministic repairs",
        "Model-generated fixes",
    },
    ROOT / "server" / "pisama_n8n_server" / "app.py": {
        '@app.get("/api/v1/capabilities")',
        "product_capabilities.generated.json",
    },
}


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fetch() -> dict[str, Any]:
    with urllib.request.urlopen(CANONICAL_URL, timeout=30) as response:
        return json.load(response)


def _validate(manifest: dict[str, Any]) -> None:
    capability_ids = {item["id"] for item in manifest["capabilities"]}
    if capability_ids != REQUIRED_CAPABILITY_IDS:
        raise ValueError("canonical capability IDs changed unexpectedly")
    products = {item["id"]: item for item in manifest["products"]}
    if products["n8n_self_hosted"]["category"] != "fair_code":
        raise ValueError("n8n self-hosting must remain fair-code")
    if (
        "not included"
        in products["n8n_self_hosted"]["capabilities"]["deterministic_repairs"].lower()
    ):
        raise ValueError("deterministic repairs must remain available when self-hosted")
    if products["n8n_cloud_free"]["allowances"]["n8n_connections"] != 1:
        raise ValueError("n8n Cloud Free must keep one connection")
    if products["n8n_pro"]["allowances"]["model_fix_generations_per_month"] != 200:
        raise ValueError("n8n Pro must keep 200 model fix generations")


def sync(source: dict[str, Any], write: bool) -> None:
    _validate(source)
    for target in TARGETS:
        if write:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(source, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        elif not target.exists() or _read(target) != source:
            raise ValueError(
                f"{target.relative_to(ROOT)} is stale; refresh it from the "
                "canonical Pisama manifest"
            )
    for surface, claims in PUBLIC_CLAIMS.items():
        text = surface.read_text(encoding="utf-8")
        missing = sorted(claim for claim in claims if claim not in text)
        if missing:
            raise ValueError(
                f"{surface.relative_to(ROOT)} is missing canonical claims: {missing}"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    source_path = args.source
    if source_path is None and DEFAULT_LOCAL_SOURCE.exists() and not args.remote:
        source_path = DEFAULT_LOCAL_SOURCE
    if args.remote:
        source = _fetch()
    elif source_path is not None:
        source = _read(source_path.resolve())
    elif TARGETS[0].exists():
        source = _read(TARGETS[0])
    else:
        raise ValueError("provide --source or --remote for the first synchronization")

    sync(source, write=args.write)
    print("n8n product capability consumers are synchronized")


if __name__ == "__main__":
    main()
