#!/usr/bin/env python3
"""Mine REAL-WORLD n8n executions: run real community workflows on a real n8n engine
and score the runtime detectors' recall against independent ground truth.

What makes this "real-world" where `generate_real_corpus.py` is not: the workflow LOGIC
is authored by third parties (mined from public GitHub — the same 2,348-workflow corpus
the precision validation used). Their throws, their loops, their data explosions. We only
(a) swap the trigger for a manual trigger and (b) run each workflow once with empty input
on a local, network-isolated n8n.

Honesty box — read before quoting numbers:
- Ground truth is INDEPENDENT of the engine: computed directly from n8n's own execution
  record (status / node error objects / executionTime / output payload sizes) by
  `ground_truth()` below, which imports nothing from the engine. A disagreement is a
  finding, not a calibration knob.
- The failure DISTRIBUTION is not production: real third-party code reacting to an
  empty standardized input over-represents input-shape errors. What this validates is
  pipeline recall on organically diverse real executions (does parse->detect surface the
  failures n8n recorded?), not the production failure mix.
- Only workflows whose EXECUTING nodes are all in SAFE_EXECUTING_TYPES run (no external
  calls, no credentials); Code-node module loading is disabled in the harness container.
  This biases the sample toward data-shaping workflows — disclosed, and also exactly
  where the runtime lane's failure modes (throw / long loop / item explosion) live.

Usage:
    # harness: docker n8n at :5678, owner eval@test.local, key in /tmp/n8n_recall_key.txt
    python eval/mine_real_world.py --scan                  # corpus stats only
    python eval/mine_real_world.py --limit 20              # bounded batch
    python eval/mine_real_world.py --limit 250 --report eval/baseline_realworld.json
"""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

BASE = os.environ.get("N8N_EVAL_URL", "http://localhost:5678").rstrip("/")
EMAIL = os.environ.get("N8N_EVAL_EMAIL", "eval@test.local")
PASSWORD = os.environ.get("N8N_EVAL_PASSWORD", "EvalPass123!")
KEY_FILE = os.environ.get("N8N_EVAL_KEY_FILE", "/tmp/n8n_recall_key.txt")
CORPUS = Path(os.environ.get("N8N_CORPUS", "/tmp/n8n_corpus"))
DATA_DIR = Path(__file__).parent / "data" / "realworld"

# Detector-semantic thresholds the ground truth mirrors (see timeout_detector.py /
# resource_detector.py). Mirrored as CONSTANTS, not imports, to stay independent.
NODE_TIMEOUT_MS = 60_000
WORKFLOW_TIMEOUT_MS = 300_000
OVERSIZED_CHARS = 10_000
AMPLIFY_FACTOR = 2.5

# Executing node types that cannot reach the network or need credentials.
# (Triggers are handled separately — they get swapped for manualTrigger.)
SAFE_EXECUTING_TYPES = {
    "n8n-nodes-base.code", "n8n-nodes-base.function", "n8n-nodes-base.functionItem",
    "n8n-nodes-base.set", "n8n-nodes-base.if", "n8n-nodes-base.switch",
    "n8n-nodes-base.merge", "n8n-nodes-base.filter", "n8n-nodes-base.noOp",
    "n8n-nodes-base.itemLists", "n8n-nodes-base.splitInBatches",
    "n8n-nodes-base.splitOut", "n8n-nodes-base.aggregate", "n8n-nodes-base.summarize",
    "n8n-nodes-base.sort", "n8n-nodes-base.limit", "n8n-nodes-base.removeDuplicates",
    "n8n-nodes-base.renameKeys", "n8n-nodes-base.dateTime", "n8n-nodes-base.crypto",
    "n8n-nodes-base.markdown", "n8n-nodes-base.xml", "n8n-nodes-base.html",
    "n8n-nodes-base.stopAndError", "n8n-nodes-base.stickyNote",
}
TRIGGER_MARKERS = ("trigger", "webhook", "cron", "interval", "schedule", "start")


# ── corpus scan / transform ───────────────────────────────────────────────────

def _extract_workflow(doc: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(doc, dict):
        return None
    for key in ("workflow", "workflowData"):
        if isinstance(doc.get(key), dict) and "nodes" in doc[key]:
            doc = doc[key]
            break
    if not isinstance(doc.get("nodes"), list) or not doc.get("nodes"):
        return None
    return doc


def _is_trigger(node: Dict[str, Any]) -> bool:
    t = (node.get("type") or "").lower()
    return any(m in t for m in TRIGGER_MARKERS) and "stickynote" not in t


def eligible(wf: Dict[str, Any], max_nodes: int = 60) -> Tuple[bool, str]:
    nodes = wf.get("nodes") or []
    if not (2 <= len(nodes) <= max_nodes):
        return False, "size"
    has_trigger = False
    has_executing = False
    for n in nodes:
        if not isinstance(n, dict):
            return False, "malformed"
        if n.get("credentials"):
            return False, "credentials"
        if _is_trigger(n):
            has_trigger = True
            continue
        t = n.get("type") or ""
        if t == "n8n-nodes-base.stickyNote":
            continue
        if t not in SAFE_EXECUTING_TYPES:
            return False, f"unsafe:{t}"
        has_executing = True
    if not has_trigger:
        return False, "no-trigger"
    if not has_executing:
        return False, "no-executing-nodes"
    return True, "ok"


def transform(wf: Dict[str, Any], name: str) -> Tuple[Dict[str, Any], str]:
    """Swap every trigger for a bare manualTrigger; leave ALL other nodes byte-intact.

    Returns (workflow, start_node_name) — the first swapped trigger, for
    `triggerToStartFrom` on the manual-run endpoint.
    """
    out = {
        "name": name,
        "nodes": [],
        "connections": wf.get("connections") or {},
        "settings": wf.get("settings") or {},
    }
    start = None
    for n in wf["nodes"]:
        n = dict(n)
        n.pop("webhookId", None)
        if _is_trigger(n):
            n["type"] = "n8n-nodes-base.manualTrigger"
            n["typeVersion"] = 1
            n["parameters"] = {}
            if start is None:
                start = n.get("name")
        out["nodes"].append(n)
    return out, start or "Start"


def scan_corpus(max_nodes: int = 60) -> Tuple[List[Tuple[Path, Dict[str, Any]]], Dict[str, int]]:
    seen: Set[str] = set()
    picked: List[Tuple[Path, Dict[str, Any]]] = []
    reasons: Dict[str, int] = {}
    for p in sorted(CORPUS.rglob("*.json")):
        try:
            doc = json.loads(p.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            reasons["unparseable"] = reasons.get("unparseable", 0) + 1
            continue
        wf = _extract_workflow(doc)
        if wf is None:
            reasons["not-a-workflow"] = reasons.get("not-a-workflow", 0) + 1
            continue
        digest = hashlib.sha256(
            json.dumps({"n": wf.get("nodes"), "c": wf.get("connections")},
                       sort_keys=True, default=str).encode()
        ).hexdigest()
        if digest in seen:
            reasons["duplicate"] = reasons.get("duplicate", 0) + 1
            continue
        seen.add(digest)
        ok, reason = eligible(wf, max_nodes=max_nodes)
        key = "eligible" if ok else reason.split(":")[0]
        reasons[key] = reasons.get(key, 0) + 1
        if ok:
            picked.append((p, wf))
    return picked, reasons


# ── n8n harness client ────────────────────────────────────────────────────────

class Harness:
    def __init__(self) -> None:
        self.key = Path(KEY_FILE).read_text().strip()
        cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        req = urllib.request.Request(
            f"{BASE}/rest/login",
            data=json.dumps({"emailOrLdapLoginId": EMAIL, "password": PASSWORD}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        self.opener.open(req, timeout=15)

    def api(self, method: str, path: str, body: Any = None) -> Any:
        req = urllib.request.Request(
            f"{BASE}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-N8N-API-KEY": self.key, "Content-Type": "application/json"},
            method=method)
        return json.load(urllib.request.urlopen(req, timeout=60))

    def run_once(self, wf: Dict[str, Any], start_node: str, deadline_s: int = 90) -> Optional[Dict[str, Any]]:
        created = self.api("POST", "/api/v1/workflows", wf)
        body = {
            "workflowData": {k: created[k] for k in ("id", "name", "nodes", "connections", "settings")},
            "triggerToStartFrom": {"name": start_node},
        }
        req = urllib.request.Request(
            f"{BASE}/rest/workflows/{created['id']}/run",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        resp = json.load(self.opener.open(req, timeout=30))
        exec_id = (resp.get("data") or {}).get("executionId")
        if not exec_id:
            return None
        t0 = time.time()
        while time.time() - t0 < deadline_s:
            time.sleep(1.5)
            try:
                ex = self.api("GET", f"/api/v1/executions/{exec_id}?includeData=true")
            except urllib.error.HTTPError:
                continue
            if ex.get("status") not in ("running", "new", "waiting"):
                return ex
        # Deadline hit: stop it and report the partial record, marked.
        try:
            req = urllib.request.Request(f"{BASE}/rest/executions/{exec_id}/stop",
                                         data=b"{}", headers={"Content-Type": "application/json"},
                                         method="POST")
            self.opener.open(req, timeout=15)
            time.sleep(2)
            ex = self.api("GET", f"/api/v1/executions/{exec_id}?includeData=true")
            ex["_harness_deadline"] = True
            return ex
        except (urllib.error.HTTPError, urllib.error.URLError, OSError):
            return None


# ── independent ground truth (NO engine imports) ─────────────────────────────

def _content_chars(run: Dict[str, Any]) -> int:
    data = run.get("data") or {}
    main = data.get("main") or []
    branch = main[0] if main and isinstance(main[0], list) else []
    try:
        return len(json.dumps(branch, default=str))
    except (TypeError, ValueError):
        return 0


def _items_out(run: Dict[str, Any]) -> int:
    data = run.get("data") or {}
    main = data.get("main") or []
    branch = main[0] if main and isinstance(main[0], list) else []
    return len(branch)


def _node_on_error(execution: Dict[str, Any]) -> Dict[str, str]:
    """node name -> onError mode, from the execution's own workflow snapshot."""
    wf = execution.get("workflow") or execution.get("workflowData") or {}
    out: Dict[str, str] = {}
    for n in wf.get("nodes") or []:
        if not isinstance(n, dict) or not n.get("name"):
            continue
        mode = n.get("onError") or ""
        if not mode and (
            (n.get("settings") or {}).get("continueOnFail") or n.get("continueOnFail")
        ):
            mode = "continueRegularOutput"
        if mode:
            out[n["name"]] = mode
    return out


def _swallowed_failure(run: Dict[str, Any], mode: str) -> bool:
    """A continue-on-fail node that actually failed: n8n records NO run error and
    keeps status success — the failure is only visible in how the output routed.
    Mirrors n8n's documented continue-on-fail semantics, computed from the raw record."""
    main = (run.get("data") or {}).get("main") or []
    if mode == "continueErrorOutput":
        return len(main) > 1 and bool(main[1])
    if mode == "continueRegularOutput":
        branch = main[0] if main and isinstance(main[0], list) else []
        for item in branch:
            j = item.get("json") if isinstance(item, dict) else None
            err = j.get("error") if isinstance(j, dict) else None
            if isinstance(err, str) and err.strip():
                return True
            # n8n also records the failure as a structured error object
            # ({message, name, ...}) — seen on real wild production executions.
            if isinstance(err, dict) and isinstance(err.get("message"), str) and err["message"].strip():
                return True
    return False


def ground_truth(execution: Dict[str, Any]) -> Set[str]:
    """Facts n8n itself recorded, per detector semantics. Independent of the engine."""
    gt: Set[str] = set()
    data = execution.get("data") or {}
    result = data.get("resultData") or {}
    run_data = result.get("runData") or {}

    # error: the execution visibly failed, a node recorded an error object, or a
    # continue-on-fail node silently failed (no run.error by design — the failure is
    # only visible in the output routing; the highest-value hidden-failure class).
    failed_status = execution.get("status") in ("error", "crashed") or execution.get("finished") is False
    node_error = any(
        isinstance(r, dict) and r.get("error")
        for runs in run_data.values() if isinstance(runs, list)
        for r in runs
    )
    on_error = _node_on_error(execution)
    swallowed = any(
        isinstance(r, dict) and _swallowed_failure(r, on_error.get(name, ""))
        for name, runs in run_data.items() if isinstance(runs, list)
        for r in runs
    )
    if result.get("error") or node_error or failed_status or swallowed:
        gt.add("error")

    # timeout: n8n's own per-node timing exceeded the semantic thresholds.
    total_ms = 0
    prev_items = 1
    for _, runs in run_data.items():
        if not isinstance(runs, list):
            continue
        for r in runs:
            if not isinstance(r, dict):
                continue
            ms = r.get("executionTime") or 0
            total_ms += ms
            if ms > NODE_TIMEOUT_MS:
                gt.add("timeout")
            chars = _content_chars(r)
            items = _items_out(r)
            if chars > OVERSIZED_CHARS:
                gt.add("resource")
            if prev_items > 0 and items / max(prev_items, 1) >= AMPLIFY_FACTOR and items >= 10:
                gt.add("resource")
            prev_items = max(items, 1)
    if total_ms > WORKFLOW_TIMEOUT_MS:
        gt.add("timeout")
    return gt


# ── scoring ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="corpus stats only, no execution")
    ap.add_argument("--rescore", action="store_true",
                    help="re-score the saved executions in eval/data/realworld "
                         "(no n8n needed) — for after detector or gt changes")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--max-nodes", type=int, default=60,
                    help="workflow size cap; raise past 60 to reach the holdout pool "
                         "of larger community workflows")
    ap.add_argument("--report", type=Path, default=None)
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).parent))
    from runtime_eval import evaluate, print_report  # noqa: E402

    if args.rescore:
        labeled = [
            (p.stem, json.loads(p.read_text()), None)
            for p in sorted(DATA_DIR.glob("*.json"))
        ]
        labeled = [(n, ex, ground_truth(ex)) for n, ex, _ in labeled]
        if not labeled:
            print(f"no saved executions under {DATA_DIR}")
            return 1
        result = evaluate(labeled)
        report = print_report(
            result, "REAL-WORLD community workflows (rescored saved executions)")
        if args.report:
            report["source"] = ("community workflows executed on local n8n; "
                                "ground truth from n8n's own record")
            args.report.write_text(json.dumps(report, indent=2) + "\n")
            print(f"wrote {args.report}")
        return 0

    picked, reasons = scan_corpus(max_nodes=args.max_nodes)
    print(f"corpus scan: {sum(reasons.values())} unique docs → {len(picked)} eligible")
    for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {k:24s} {v}")
    if args.scan:
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    harness = Harness()
    batch = picked[args.offset:args.offset + args.limit]
    labeled: List[Tuple[str, Dict[str, Any], Set[str]]] = []
    skipped = 0
    for i, (path, wf) in enumerate(batch):
        name = f"rw_{hashlib.sha256(str(path).encode()).hexdigest()[:10]}"
        if (DATA_DIR / f"{name}.json").exists():
            # Already captured in an earlier batch — don't re-execute, and don't
            # score it in THIS invocation (each batch reports only what it ran, so
            # a holdout run stays a genuine holdout).
            continue
        twf, start = transform(wf, name)
        try:
            ex = harness.run_once(twf, start)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
            print(f"  [{i}] SKIP (harness refused: {type(exc).__name__}) {path.name}")
            skipped += 1
            continue
        if ex is None:
            print(f"  [{i}] SKIP (no execution captured) {path.name}")
            skipped += 1
            continue
        ex["_source"] = str(path)
        (DATA_DIR / f"{name}.json").write_text(json.dumps(ex, default=str))
        gt = ground_truth(ex)
        labeled.append((name, ex, gt))
        print(f"  [{i}] {name} status={ex.get('status')} gt={sorted(gt) or '-'} src={path.name[:60]}")

    print(f"\nexecuted {len(labeled)}, skipped {skipped}")
    if not labeled:
        print("REFUSING to score an empty corpus.")
        return 1

    result = evaluate(labeled)
    report = print_report(result, "REAL-WORLD community workflows (independent n8n ground truth)")
    if args.report:
        report["source"] = "community workflows executed on local n8n; ground truth from n8n's own record"
        report["skipped"] = skipped
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
