#!/usr/bin/env python3
"""Deterministic classifier + sanitizer for the corpus guard campaign.

Reads the committed community corpus (eval/data/realworld/rw_*.json — full n8n
execution payloads whose workflowData was trigger-neutered to manualTrigger by
eval/mine_real_world.py) and emits a committed manifest describing, per workflow:
what it is, whether and how it can be honestly driven, which repair lane it likely
belongs to, and the exact webhook re-attachment that makes it drivable.

HONESTY CONTRACT (the campaign's, enforced here):
  - Business logic is NEVER modified. The ONLY mutation is replacing one
    manualTrigger node with a webhook trigger of the SAME NODE NAME (so connections
    need no rewiring), plus filtering settings to the n8n-create whitelist. The
    manifest records every dropped settings key.
  - Everything is deterministic (uuid5 webhook ids, sorted iteration) so
    `--check` can prove the committed manifest matches a re-derivation.
  - Classification is a GUESS to plan budgets; the campaign driver decides lanes
    empirically from real executions and records the divergence.

Usage:
  python3 scripts/corpus_campaign_prepare.py             # write the manifest
  python3 scripts/corpus_campaign_prepare.py --check     # re-derive + diff (CI)
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "eval" / "data" / "realworld"
MANIFEST = ROOT / "eval" / "campaigns" / "manifest_2026-07.json"

# Mirrors engine guardrails._CHAIN_PATTERN — the reads the path derivation can parse.
CHAIN_PATTERN = re.compile(
    r"(?:\$json|(?:\$input\.)?item\.json|\$\(['\"][^'\"]+['\"]\)\.item\.json)"
    r"((?:\.[A-Za-z_$][A-Za-z0-9_$]*)+)"
)
# Nondeterminism markers: Tier-A candidates must be excluded when consumer output
# depends on these (a "valid" payload could still fail on a later run → recurrence).
NONDET_PATTERN = re.compile(r"Math\.random|new Date\(|Date\.now\(")

TRIGGER_TYPES = {
    "n8n-nodes-base.manualTrigger",
    "n8n-nodes-base.webhook",
    "n8n-nodes-base.cron",
    "n8n-nodes-base.scheduleTrigger",
}

# n8n POST /workflows settings whitelist (1.70.0-safe). errorWorkflow is KEPT — the
# two corpus files carrying a stale one are the n8n_error_workflow_target_missing
# lane. Everything else is dropped and RECORDED.
SETTINGS_WHITELIST = {
    "executionOrder",
    "errorWorkflow",
    "executionTimeout",
    "timezone",
    "saveDataErrorExecution",
    "saveDataSuccessExecution",
    "saveManualExecutions",
    "saveExecutionProgress",
}


def _short_hash(name: str) -> str:
    return hashlib.sha256(name.encode()).hexdigest()[:10]


def _code_of(node: Dict[str, Any]) -> str:
    params = node.get("parameters") or {}
    return params.get("jsCode") or params.get("functionCode") or ""


def _chains(code: str) -> List[str]:
    return sorted({m.group(1).lstrip(".") for m in CHAIN_PATTERN.finditer(code)})


def _method_leaf_chains(code: str, chains: List[str]) -> List[str]:
    """Chains whose leaf is invoked as a call (e.g. message.text.split). The
    engine derivation (guardrails.observed_required_paths) strips a call-site
    leaf and requires its RECEIVER path, so these no longer screen a workflow
    out of the input_schema lane; recorded as a diagnostic and used by the
    campaign driver as a regression tripwire on derived paths."""
    flagged = []
    for chain in chains:
        leaf = chain.rsplit(".", 1)[-1]
        if re.search(re.escape(chain) + r"\s*\(", code) or re.search(
            r"\." + re.escape(leaf) + r"\s*\(", code
        ):
            flagged.append(chain)
    return flagged


def _reachable(connections: Dict[str, Any], start: str) -> set:
    """Node names reachable from `start` over main connections."""
    seen, stack = set(), [start]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        for branch in (connections.get(node) or {}).get("main") or []:
            for edge in branch or []:
                target = (edge or {}).get("node")
                if target and target not in seen:
                    stack.append(target)
    return seen


def classify(path: Path) -> Dict[str, Any]:
    doc = json.loads(path.read_text())
    wf = doc.get("workflowData") or {}
    nodes = wf.get("nodes") or []
    connections = wf.get("connections") or {}
    settings = wf.get("settings") or {}
    result_data = (doc.get("data") or {}).get("resultData") or {}
    error = result_data.get("error") or {}
    failing_node = None
    if isinstance(error.get("node"), dict):
        failing_node = error["node"].get("name")
    failing_node = failing_node or result_data.get("lastNodeExecuted")

    triggers = [n for n in nodes if n.get("type") in TRIGGER_TYPES]
    # Chosen trigger: the one whose reachable set contains the recorded failing
    # node; fallback to the first trigger with outgoing main edges (C8).
    chosen = None
    for trig in triggers:
        if failing_node and failing_node in _reachable(connections, trig.get("name")):
            chosen = trig.get("name")
            break
    if chosen is None:
        for trig in triggers:
            if (connections.get(trig.get("name")) or {}).get("main"):
                chosen = trig.get("name")
                break
    if chosen is None and triggers:
        chosen = triggers[0].get("name")

    all_chains: List[str] = []
    method_leafs: List[str] = []
    nondet = False
    for node in nodes:
        code = _code_of(node)
        if not code:
            continue
        chains = _chains(code)
        all_chains.extend(chains)
        method_leafs.extend(_method_leaf_chains(code, chains))
        if NONDET_PATTERN.search(code):
            nondet = True
    all_chains = sorted(set(all_chains))
    method_leafs = sorted(set(method_leafs))
    body_chains = [c for c in all_chains if c == "body" or c.startswith("body.")]

    error_workflow = settings.get("errorWorkflow")
    dropped = sorted(set(settings) - SETTINGS_WHITELIST)

    # Lane GUESS (driver decides empirically): input_schema needs a body-satisfiable
    # chain read; error_route needs a failure and a missing or stale error route
    # (68/70 missing, 2 stale). Method-call leaves no longer disqualify: the engine
    # requires the call's receiver path, not the method name.
    if doc.get("status") == "error" and body_chains:
        lane_guess = "input_schema"
    elif doc.get("status") == "error" or all_chains:
        lane_guess = "error_route"
    else:
        lane_guess = "error_route_if_failure_induceable"

    name = path.stem
    return {
        "id": name,
        "original_name": wf.get("name"),
        "source": doc.get("_source"),
        "original_status": doc.get("status"),
        "failing_node": failing_node,
        "trigger_count": len(triggers),
        "chosen_trigger": chosen,
        "error_workflow": error_workflow,
        "settings_dropped": dropped,
        "chain_reads": all_chains,
        "body_chains": body_chains,
        "method_leaf_chains": method_leafs,
        "nondeterministic": nondet,
        "lane_guess": lane_guess,
        "webhook_path": f"pisama-camp-{_short_hash(name)}",
        "webhook_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"pisama-campaign/{name}")),
    }


def reattach_webhook(wf: Dict[str, Any], entry: Dict[str, Any]) -> Dict[str, Any]:
    """The ONLY workflow mutation the campaign makes: replace the chosen
    manualTrigger with a webhook trigger of the SAME NODE NAME (connections stay
    byte-identical), and filter settings to the create whitelist."""
    out = copy.deepcopy(wf)
    for node in out.get("nodes") or []:
        if node.get("name") == entry["chosen_trigger"]:
            node["type"] = "n8n-nodes-base.webhook"
            node["typeVersion"] = 2
            node["parameters"] = {"httpMethod": "POST", "path": entry["webhook_path"]}
            node["webhookId"] = entry["webhook_id"]
            node.pop("credentials", None)
            break
    settings = {
        k: v for k, v in (out.get("settings") or {}).items() if k in SETTINGS_WHITELIST
    }
    return {
        "name": f"[pisama-campaign] {entry['id']}",
        "nodes": out.get("nodes") or [],
        "connections": out.get("connections") or {},
        "settings": settings,
    }


def build_manifest() -> Dict[str, Any]:
    entries = [classify(p) for p in sorted(CORPUS.glob("rw_*.json"))]
    lanes: Dict[str, int] = {}
    for entry in entries:
        lanes[entry["lane_guess"]] = lanes.get(entry["lane_guess"], 0) + 1
    return {
        "corpus_dir": str(CORPUS.relative_to(ROOT)),
        "total": len(entries),
        "lane_guess_counts": dict(sorted(lanes.items())),
        "disclosures": [
            "The 17 'wild' workflows from the recall validation have no committed "
            "artifacts (third-party PII) and are excluded; the claim ceiling is the "
            "committed corpus.",
            "Every workflow was trigger-neutered to manualTrigger by the mining "
            "harness; the campaign re-attaches a webhook trigger (same node name, "
            "business logic byte-identical) to make it drivable. Disclosed, not "
            "hidden.",
            "lane_guess is a planning estimate; the campaign driver decides lanes "
            "from real executions and records divergences.",
        ],
        "workflows": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    manifest = build_manifest()
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not MANIFEST.exists():
            print(f"MISSING: {MANIFEST}", file=sys.stderr)
            return 1
        if MANIFEST.read_text() != rendered:
            print("MANIFEST DRIFT: re-run scripts/corpus_campaign_prepare.py",
                  file=sys.stderr)
            return 1
        print(f"manifest OK ({manifest['total']} workflows)")
        return 0
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(rendered)
    print(f"wrote {MANIFEST} ({manifest['total']} workflows)")
    print("lane guesses:", manifest["lane_guess_counts"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
