#!/usr/bin/env python3
"""Runtime-lane detector eval for Pisama-for-n8n.

Measures per-detector precision / recall / F1 for the EXECUTION-lane detectors
(timeout, error, resource) — the lane that reads real n8n execution runData and was
previously unmeasurable from static workflow mining.

Two ground-truth sources (chosen with --source):

  controlled  (default) — a corpus of realistic n8n executions CONSTRUCTED with known
              labels: genuine node errors, hidden continue-on-fail failures, 60s+ slow
              nodes, payload explosions, PLUS healthy runs and ADVERSARIAL near-misses
              (slow-but-under-threshold, big-but-normal, error-mentioned-in-content).
              Gives a real precision/recall number for detector LOGIC with BOTH classes
              and a regression baseline. It is NOT a real-world distribution — a true
              real-world false-positive rate needs live production runData.

  mine        — fetch REAL executions from a connected n8n (N8N_HOST + N8N_API_KEY) and
              label by n8n's own ground truth (execution status + node-level error
              objects). Refuses to report precision/recall for a class that has no
              samples (the degenerate-corpus guard) instead of fabricating a number.

Honesty: the controlled labels are threshold-derived EXPECTATIONS. A disagreement is a
real finding (over-fire = precision loss, under-fire = recall loss), which is exactly
what the eval is for. The `mine` path is what upgrades this to a real-world number the
day a genuine n8n with healthy+failing traffic is available.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from pisama_n8n_engine.orchestrator import analyze
from pisama_n8n_engine.trace.execution import execution_to_turns_and_metadata

RUNTIME_DETECTORS = ("timeout", "error", "resource")


# ── execution payload construction (real n8n runData shape) ──────────────────

def _node(name: str, ntype: str, exec_ms: int, output: Any, error: Optional[str] = None,
          continue_on_fail: bool = False) -> Tuple[Dict, Dict]:
    """A (node-def, run-record) pair matching the n8n /executions?includeData shape."""
    params: Dict[str, Any] = {}
    if continue_on_fail:
        params["onError"] = "continueErrorOutput"
    node_def = {"name": name, "type": ntype, "parameters": params}
    run = {
        "executionTime": exec_ms,
        "executionStatus": "error" if error else "success",
        "data": {"main": [[{"json": output}] if output is not None else []]},
    }
    if error:
        run["error"] = {"message": error, "name": "NodeApiError"}
    return node_def, run


def make_execution(nodes: List[Tuple[Dict, Dict]], mode: str = "manual",
                   status: str = "success") -> Dict[str, Any]:
    """Assemble a full execution payload from (node_def, run) pairs."""
    node_defs = [nd for nd, _ in nodes]
    run_data = {nd["name"]: [run] for nd, run in nodes}
    return {
        "id": "eval",
        "workflowId": "wf-eval",
        "mode": mode,
        "status": status,
        "workflowData": {"nodes": node_defs, "connections": {}},
        "data": {"resultData": {"runData": run_data}},
    }


def _big(chars: int) -> Dict[str, str]:
    return {"payload": "x" * chars}


# ── controlled corpus: matched positives / negatives / adversarial near-misses ──

@dataclass
class Case:
    name: str
    category: str          # pos | neg | adversarial
    payload: Dict[str, Any]
    expected: Set[str]     # detectors that SHOULD fire


def build_corpus() -> List[Case]:
    C: List[Case] = []

    def add(name, category, expected, nodes, mode="manual", status="success"):
        C.append(Case(name, category, make_execution(nodes, mode=mode, status=status),
                      set(expected)))

    small = {"ok": 1}

    # ── TIMEOUT ──────────────────────────────────────────────────────────────
    add("timeout_webhook_64s", "pos", {"timeout"}, mode="webhook", status="error", nodes=[
        _node("Webhook", "n8n-nodes-base.webhook", 5, small),
        _node("HTTP", "n8n-nodes-base.httpRequest", 64_000, small),
        _node("Respond", "n8n-nodes-base.respondToWebhook", 10, small),
    ])
    add("timeout_workflow_6min", "pos", {"timeout"}, nodes=[
        _node(f"Slow{i}", "n8n-nodes-base.httpRequest", 80_000, small) for i in range(5)
    ])
    add("timeout_fast_healthy", "neg", set(), mode="webhook", nodes=[
        _node("Webhook", "n8n-nodes-base.webhook", 3, small),
        _node("HTTP", "n8n-nodes-base.httpRequest", 1_200, small),
        _node("Code", "n8n-nodes-base.code", 40, small),
        _node("Respond", "n8n-nodes-base.respondToWebhook", 8, small),
    ])
    add("timeout_webhook_25s_under", "adversarial", set(), mode="webhook", nodes=[
        _node("Webhook", "n8n-nodes-base.webhook", 5, small),
        _node("HTTP", "n8n-nodes-base.httpRequest", 25_000, small),  # slow but < 30s
        _node("Respond", "n8n-nodes-base.respondToWebhook", 10, small),
    ])
    add("timeout_workflow_under_all_thresholds", "adversarial", set(), nodes=[
        # default node threshold is 60s; keep each node under it AND total under 5 min.
        _node(f"N{i}", "n8n-nodes-base.noOp", 40_000, small) for i in range(7)  # 280s < 300s
    ])

    # ── ERROR ────────────────────────────────────────────────────────────────
    add("error_hidden_continue", "pos", {"error"}, status="success", nodes=[
        _node("Webhook", "n8n-nodes-base.webhook", 4, small),
        _node("HTTP", "n8n-nodes-base.httpRequest", 300, None,
              error="Request failed with status 500", continue_on_fail=True),  # hidden
        _node("Respond", "n8n-nodes-base.respondToWebhook", 8, small),
    ])
    add("error_high_rate_50pct", "pos", {"error"}, status="error", nodes=[
        _node("A", "n8n-nodes-base.httpRequest", 200, None, error="timeout"),
        _node("B", "n8n-nodes-base.httpRequest", 200, None, error="ECONNRESET"),
        _node("C", "n8n-nodes-base.httpRequest", 200, None, error="500"),
        _node("D", "n8n-nodes-base.set", 20, small),
        _node("E", "n8n-nodes-base.set", 20, small),
        _node("F", "n8n-nodes-base.set", 20, small),
    ])
    add("error_clean_healthy", "neg", set(), nodes=[
        _node("Webhook", "n8n-nodes-base.webhook", 4, small),
        _node("HTTP", "n8n-nodes-base.httpRequest", 300, {"users": [1, 2, 3]}),
        _node("Set", "n8n-nodes-base.set", 20, small),
    ])
    add("error_low_rate_visible", "adversarial", {"error"}, status="error", nodes=[
        # 1/10 errored, NOT continueOnFail (visible stop, rate 10% < 15%).
        # SEMANTIC DECISION (real-world validation, 2026-07-16): originally expected
        # EMPTY — the detector was hidden-errors-only, so a correctly-halted visible
        # failure was a designed negative. But on real community workflows that scope
        # meant a crashed execution could yield ZERO detections (terminal single-node
        # failure: no continueOnFail, no downstream turns, rate under 15%, and the
        # success-despite-failures check suppresses itself once the workflow is marked
        # failed) — invisible to dashboards and healing, which gate on detections. The
        # detector now has an execution_failure branch for loud failures; this case is
        # a positive of that type. The original FP-guard purpose is preserved by the
        # adjacent negatives (error_content_mentions_error, continueOnFail-no-failure).
        _node("N0", "n8n-nodes-base.httpRequest", 200, None, error="one failure"),
        *[_node(f"N{i}", "n8n-nodes-base.set", 20, small) for i in range(1, 10)],
    ])
    add("error_content_mentions_error", "adversarial", set(), nodes=[
        # Node output literally contains the word 'error' but nothing failed.
        _node("Webhook", "n8n-nodes-base.webhook", 4, small),
        _node("Code", "n8n-nodes-base.code", 30, {"message": "no error occurred", "status": "ok"}),
    ])

    # ── RESOURCE ─────────────────────────────────────────────────────────────
    add("resource_growth_explosion", "pos", {"resource"}, nodes=[
        _node("Trigger", "n8n-nodes-base.manualTrigger", 1, _big(200)),
        _node("Expand1", "n8n-nodes-base.code", 30, _big(2_000)),
        _node("Expand2", "n8n-nodes-base.code", 40, _big(20_000)),   # ~10x, and >10k
    ])
    add("resource_oversized_payload", "pos", {"resource"}, nodes=[
        _node("Webhook", "n8n-nodes-base.webhook", 4, small),
        _node("Fetch", "n8n-nodes-base.httpRequest", 500, _big(40_000)),  # >10k chars
    ])
    add("resource_stable_healthy", "neg", set(), nodes=[
        _node("Webhook", "n8n-nodes-base.webhook", 4, _big(300)),
        _node("HTTP", "n8n-nodes-base.httpRequest", 300, _big(320)),
        _node("Set", "n8n-nodes-base.set", 20, _big(310)),
    ])
    add("resource_growth_2x_under", "adversarial", set(), nodes=[
        _node("Trigger", "n8n-nodes-base.manualTrigger", 1, _big(1_000)),
        _node("Grow", "n8n-nodes-base.code", 30, _big(2_000)),  # 2x < 2.5x, under 10k
    ])
    add("resource_9k_under", "adversarial", set(), nodes=[
        _node("Webhook", "n8n-nodes-base.webhook", 4, small),
        _node("Fetch", "n8n-nodes-base.httpRequest", 400, _big(9_000)),  # <10k
    ])

    add("timeout_ai_node_90s_background", "adversarial", set(), mode="trigger", nodes=[
        # Background (no webhook caller): a 90s AI node is under the 120s AI node
        # threshold and total < 5 min, so it's expected-slow, not a timeout.
        _node("Schedule", "n8n-nodes-base.scheduleTrigger", 2, small),
        _node("LLM", "n8n-nodes-base.openAi", 90_000, small),
        _node("Save", "n8n-nodes-base.set", 15, small),
    ])
    add("resource_large_but_stable", "adversarial", set(), nodes=[
        # ~8k chars at every node: large-ish but NOT growing and under the 10k limit.
        _node("Webhook", "n8n-nodes-base.webhook", 4, _big(8_000)),
        _node("HTTP", "n8n-nodes-base.httpRequest", 400, _big(8_100)),
        _node("Set", "n8n-nodes-base.set", 20, _big(8_050)),
    ])

    # ── MIXED / realistic ────────────────────────────────────────────────────
    add("healthy_realistic", "neg", set(), mode="webhook", nodes=[
        _node("Webhook", "n8n-nodes-base.webhook", 3, small),
        _node("Fetch", "n8n-nodes-base.httpRequest", 800, {"data": [1, 2, 3, 4, 5]}),
        _node("Transform", "n8n-nodes-base.code", 25, {"count": 5}),
        _node("Respond", "n8n-nodes-base.respondToWebhook", 7, small),
    ])
    add("multi_signal_slow_and_hidden", "pos", {"timeout", "error"}, mode="webhook",
        status="success", nodes=[
        _node("Webhook", "n8n-nodes-base.webhook", 5, small),
        _node("SlowHTTP", "n8n-nodes-base.httpRequest", 48_000, None,
              error="upstream 504", continue_on_fail=True),
        _node("Respond", "n8n-nodes-base.respondToWebhook", 9, small),
    ])
    return C


# ── metrics ──────────────────────────────────────────────────────────────────

@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def prf(self) -> Dict[str, Optional[float]]:
        p = self.tp / (self.tp + self.fp) if (self.tp + self.fp) else None
        r = self.tp / (self.tp + self.fn) if (self.tp + self.fn) else None
        f1 = (2 * p * r / (p + r)) if (p and r) else (0.0 if (p == 0 or r == 0) else None)
        return {"precision": p, "recall": r, "f1": f1}


def _fired(payload: Dict[str, Any]) -> Set[str]:
    turns, metadata = execution_to_turns_and_metadata(payload)
    report = analyze(turns=turns, metadata=metadata, workflow_id=payload.get("workflowId"))
    return {d.detector for d in report.detections if d.detected and d.detector in RUNTIME_DETECTORS}


def evaluate(labeled: List[Tuple[str, Dict[str, Any], Set[str]]]) -> Dict[str, Any]:
    """labeled = [(name, payload, expected_set)]. Returns per-detector counts + prf."""
    per: Dict[str, Counts] = {d: Counts() for d in RUNTIME_DETECTORS}
    mistakes: List[str] = []
    for name, payload, expected in labeled:
        fired = _fired(payload)
        for d in RUNTIME_DETECTORS:
            want, got = d in expected, d in fired
            c = per[d]
            if want and got:
                c.tp += 1
            elif want and not got:
                c.fn += 1
                mistakes.append(f"  MISS  {d:8} expected but not fired  [{name}]")
            elif got and not want:
                c.fp += 1
                mistakes.append(f"  FALSE {d:8} fired but not expected  [{name}]")
            else:
                c.tn += 1
    return {"per_detector": per, "mistakes": mistakes, "n": len(labeled)}


def _fmt(x: Optional[float]) -> str:
    return "  n/a" if x is None else f"{x:5.2f}"


def print_report(result: Dict[str, Any], title: str) -> Dict[str, Any]:
    per: Dict[str, Counts] = result["per_detector"]
    print(f"\n=== {title} (n={result['n']} executions) ===")
    print(f"{'detector':10} {'TP':>3} {'FP':>3} {'FN':>3} {'TN':>3}  "
          f"{'prec':>5} {'recall':>6} {'f1':>5}")
    out_detectors = {}
    for d in RUNTIME_DETECTORS:
        c = per[d]
        m = c.prf()
        pos = c.tp + c.fn
        neg = c.tn + c.fp
        note = ""
        if pos == 0:
            note = "  (no positives → recall n/a)"
        elif neg == 0:
            note = "  (no negatives → precision n/a; corpus degenerate for this detector)"
        print(f"{d:10} {c.tp:3} {c.fp:3} {c.fn:3} {c.tn:3}  "
              f"{_fmt(m['precision'])} {_fmt(m['recall'])} {_fmt(m['f1'])}{note}")
        out_detectors[d] = {"tp": c.tp, "fp": c.fp, "fn": c.fn, "tn": c.tn, **m}
    if result["mistakes"]:
        print("\ndisagreements (detector vs label):")
        for line in result["mistakes"]:
            print(line)
    return {"title": title, "n": result["n"], "detectors": out_detectors}


# ── real-execution mining path (ground truth = n8n's own status/errors) ──────

def _n8n_label(execution: Dict[str, Any]) -> Set[str]:
    """Ground truth from n8n itself: a genuine node error → the 'error' detector should
    fire. (Timeout/resource have no clean n8n label, so mining measures 'error' only —
    honestly, rather than fabricating labels for the others.)"""
    rd = ((execution.get("data", {}) or {}).get("resultData", {}) or {}).get("runData", {}) or {}
    node_errors = sum(1 for runs in rd.values() for r in (runs or [])
                      if isinstance(r, dict) and r.get("error"))
    top_error = (execution.get("data", {}) or {}).get("resultData", {}).get("error")
    if node_errors > 0 or (execution.get("status") == "error" and top_error):
        return {"error"}
    return set()


def mine_real(limit: int = 250) -> List[Tuple[str, Dict[str, Any], Set[str]]]:
    import urllib.request

    host = os.environ.get("N8N_HOST") or os.environ.get("PISAMA_N8N_URL")
    key = os.environ.get("N8N_API_KEY") or os.environ.get("PISAMA_N8N_API_KEY")
    if not host or not key:
        raise SystemExit("mine: set N8N_HOST + N8N_API_KEY to fetch real executions.")
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/v1/executions?limit={limit}&includeData=true",
        headers={"X-N8N-API-KEY": key},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (trusted host)
        data = json.load(resp)
    labeled = []
    for e in data.get("data", []):
        payload = {**e, "workflowData": e.get("workflowData")
                   or (e.get("workflowId") and {"nodes": [], "connections": {}})}
        labeled.append((str(e.get("id")), payload, _n8n_label(e)))
    return labeled


def guard_degenerate(labeled) -> None:
    pos = sum(1 for _, _, exp in labeled if "error" in exp)
    neg = len(labeled) - pos
    print(f"\nmined {len(labeled)} real executions: {pos} labeled-failure, {neg} labeled-healthy")
    if pos == 0 or neg == 0:
        missing = "healthy negatives" if neg == 0 else "failure positives"
        print(f"\n!! DEGENERATE CORPUS: 0 {missing}. Precision/recall on real data is NOT")
        print("   reportable from this instance. Connect an n8n with BOTH real healthy and")
        print("   failing production executions to get a real-world number. (The controlled")
        print("   eval below still measures detector logic on both classes.)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["controlled", "mine"], default="controlled")
    ap.add_argument("--limit", type=int, default=250)
    ap.add_argument("--json", help="write the baseline metrics JSON here")
    args = ap.parse_args()

    baseline: Dict[str, Any] = {}

    if args.source == "mine":
        labeled = mine_real(args.limit)
        guard_degenerate(labeled)
        if any(exp for _, _, exp in labeled) and any(not exp for _, _, exp in labeled):
            res = evaluate([(n, p, e) for n, p, e in labeled])
            baseline["real"] = print_report(res, "REAL executions (n8n-status ground truth, ERROR lane)")
    else:
        corpus = build_corpus()
        labeled = [(c.name, c.payload, c.expected) for c in corpus]
        res = evaluate(labeled)
        baseline["controlled"] = print_report(
            res, "CONTROLLED corpus (constructed, both classes + adversarial)")
        # Adversarial-only slice: the precision stress test.
        adv = [(c.name, c.payload, c.expected) for c in corpus if c.category == "adversarial"]
        baseline["adversarial_only"] = print_report(
            evaluate(adv), "ADVERSARIAL near-misses only (should all be no-fire)")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(baseline, f, indent=2, default=str)
        print(f"\nbaseline written to {args.json}")


if __name__ == "__main__":
    main()
