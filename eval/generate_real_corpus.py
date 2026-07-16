#!/usr/bin/env python3
"""Generate a REAL n8n execution corpus and eval the runtime detectors on it.

Expects a local n8n at N8N_EVAL_URL (default localhost:5678) with owner creds
(N8N_EVAL_EMAIL/N8N_EVAL_PASSWORD) and a public API key (N8N_EVAL_KEY). Creates
manual-trigger workflows that each exhibit a KNOWN runtime failure mode (or are healthy),
executes each via n8n's internal manual-run (records a real execution with full runData),
fetches the executions via the public API, labels them BY DESIGN, and runs the eval.

Real n8n engine, real per-node timings/errors/payloads, both classes — the real-world
number the controlled corpus stands in for. Timeout is exercised with a 65s node (over
the 60s default per-node threshold) so it fires under manual (non-webhook) execution.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Set, Tuple

BASE = os.environ.get("N8N_EVAL_URL", "http://localhost:5678").rstrip("/")
KEY = os.environ.get("N8N_EVAL_KEY", "")
EMAIL = os.environ.get("N8N_EVAL_EMAIL", "eval@test.local")
PASSWORD = os.environ.get("N8N_EVAL_PASSWORD", "EvalPass123!")

_cj = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cj))


def _login() -> None:
    r = urllib.request.Request(f"{BASE}/rest/login",
                               data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    _opener.open(r, timeout=15)


def _api(method: str, path: str, body: Any = None) -> Any:
    r = urllib.request.Request(f"{BASE}{path}",
                               data=json.dumps(body).encode() if body is not None else None,
                               headers={"X-N8N-API-KEY": KEY, "Content-Type": "application/json"},
                               method=method)
    return json.load(urllib.request.urlopen(r, timeout=30))


def _run(wf: Dict) -> None:
    body = {"workflowData": {k: wf[k] for k in ("id", "name", "nodes", "connections", "settings")}}
    r = urllib.request.Request(f"{BASE}/rest/workflows/{wf['id']}/run",
                               data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    _opener.open(r, timeout=120).read()


# ── workflow builders (manual trigger + a code node exhibiting the mode) ─────

def _mt() -> Dict:
    return {"parameters": {}, "id": "mt", "name": "Start",
            "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [0, 0]}


def _code(name: str, js: str, on_error: str | None = None, pos=(260, 0)) -> Dict:
    node = {"parameters": {"mode": "runOnceForAllItems", "jsCode": js},
            "id": f"c-{name}", "name": name, "type": "n8n-nodes-base.code",
            "typeVersion": 2, "position": list(pos)}
    if on_error:
        node["onError"] = on_error
    return node


def _wf(name: str, *code_nodes: Dict) -> Dict:
    nodes = [_mt(), *code_nodes]
    conns: Dict[str, Any] = {}
    prev = "Start"
    for cn in code_nodes:
        conns[prev] = {"main": [[{"node": cn["name"], "type": "main", "index": 0}]]}
        prev = cn["name"]
    return {"name": name, "nodes": nodes, "connections": conns, "settings": {"executionOrder": "v1"}}


def corpus_specs() -> List[Tuple[Dict, Set[str]]]:
    return [
        (_wf("eval_healthy_small", _code("Work", "return [{json:{ok:true,n:3}}];")), set()),
        (_wf("eval_healthy_list", _code("Work", "return [1,2,3,4,5].map(n=>({json:{id:n}}));")), set()),
        (_wf("eval_healthy_slow_ok",
             _code("Wait", "await new Promise(r=>setTimeout(r,3000));return [{json:{ok:true}}];")), set()),
        (_wf("eval_node_error", _code("Boom", "throw new Error('processing failed: upstream 500');")), {"error"}),
        (_wf("eval_hidden_error",
             _code("MaybeFail", "throw new Error('silently swallowed');", on_error="continueErrorOutput")),
         {"error"}),
        (_wf("eval_timeout_65s",
             _code("Slow", "await new Promise(r=>setTimeout(r,65000));return [{json:{done:true}}];")),
         {"timeout"}),
        (_wf("eval_resource_big", _code("Big", "return [{json:{payload:'x'.repeat(50000)}}];")), {"resource"}),
        (_wf("eval_resource_growth",
             _code("Seed", "return [{json:{s:'x'.repeat(500)}}];"),
             _code("Blow", "return [{json:{s:'x'.repeat(30000)}}];", pos=(520, 0))), {"resource"}),
        # adversarial negatives — precision stress for the continue-on-fail parser fix:
        # a node CONFIGURED continue-on-fail that did NOT fail must not be flagged,
        (_wf("eval_adv_cof_healthy",
             _code("MaybeFail", "return [{json:{ok:true,processed:3}}];", on_error="continueRegularOutput")),
         set()),
        # and a healthy node whose output legitimately carries a field named "error".
        (_wf("eval_adv_error_field_benign",
             _code("Report", "return [{json:{status:'ok',error:null,note:'no error occurred'}}];")), set()),
    ]


def _create_and_run() -> None:
    """Recreate the eval workflows and execute each one (the 65s timeout runs ~65s)."""
    for w in _api("GET", "/api/v1/workflows?limit=100").get("data", []):
        if w["name"].startswith("eval_"):
            try:
                _api("DELETE", f"/api/v1/workflows/{w['id']}")
            except Exception:
                pass
    created = []
    for wf, _ in corpus_specs():
        full = _api("POST", "/api/v1/workflows", wf)
        full = full.get("data") or full
        created.append(full)
        print(f"created {wf['name']} (id={full['id']})")
    print("\nexecuting (the 65s timeout workflow really runs ~65s)…")
    for wf in created:
        _run(wf)
        print(f"  ran {wf['name']}")
    want = {wf["id"] for wf in created}
    for _ in range(130 // 3):
        got = {str(e["workflowId"]) for e in _api("GET", "/api/v1/executions?limit=100").get("data", [])
               if str(e.get("workflowId")) in {str(w) for w in want} and e.get("finished") is not None}
        if len(got) >= len(want):
            break
        time.sleep(3)


def _fetch_labeled() -> List[Tuple[str, Dict, Set[str]]]:
    """Fetch the real executions, attach real node defs, label each by workflow name."""
    expected_by_name = {wf["name"]: exp for wf, exp in corpus_specs()}
    wfs = {str(w["id"]): w for w in _api("GET", "/api/v1/workflows?limit=100").get("data", [])}
    execs = _api("GET", "/api/v1/executions?limit=100&includeData=true").get("data", [])
    labeled: List[Tuple[str, Dict, Set[str]]] = []
    seen: Set[str] = set()
    for e in execs:  # newest first — keep the latest execution per eval workflow
        wid = str(e.get("workflowId"))
        w = wfs.get(wid)
        if not w or not w["name"].startswith("eval_") or w["name"] in seen:
            continue
        if e.get("finished") is None:
            continue
        seen.add(w["name"])
        if not (e.get("workflowData") or e.get("workflow")):
            e = {**e, "workflowData": {"nodes": w["nodes"], "connections": w["connections"]}}
        labeled.append((w["name"], e, expected_by_name[w["name"]]))
    return labeled


def main() -> None:
    if not KEY:
        raise SystemExit("set N8N_EVAL_KEY")
    from runtime_eval import evaluate, print_report

    _login()
    print("logged in")
    if os.environ.get("REUSE") != "1":
        _create_and_run()

    labeled = _fetch_labeled()
    for name, e, expected in labeled:
        rd = ((e.get("data", {}) or {}).get("resultData", {}) or {}).get("runData", {})
        node_errs = sum(1 for runs in rd.values() for r in (runs or []) if isinstance(r, dict) and r.get("error"))
        tmax = max([r.get("executionTime", 0) for runs in rd.values() for r in (runs or []) if isinstance(r, dict)] + [0])
        print(f"  {name:22} finished={str(e.get('finished')):5} nodes={len(rd)} node_errs={node_errs} maxms={tmax} expect={sorted(expected) or '[]'}")

    pos = sum(1 for _, _, exp in labeled if exp)
    print(f"\ncaptured {len(labeled)} real executions | {pos} failure, {len(labeled)-pos} healthy")
    res = evaluate(labeled)
    report = print_report(res, "REAL n8n executions (local engine, by-design labels)")
    out = os.path.join(os.path.dirname(__file__), "baseline_real.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nreal baseline written to {out}")


if __name__ == "__main__":
    main()
