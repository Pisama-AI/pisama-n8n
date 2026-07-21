#!/usr/bin/env python3
"""Corpus guard campaign driver: real guard lifecycles across community workflows.

Imports manifest-prepared community workflows into a REAL n8n, drives controlled
payloads through their production webhooks, and runs Pisama's own repair endpoints:
detect -> propose -> (destination|target) -> apply -> real probes -> success
accumulation. Emits one JSONL row per workflow recording exactly how far it got and
why it stopped — the FUNNEL is the deliverable, drop-offs included.

HONESTY CONTRACT (do not weaken):
  - Every execution is a real n8n run through a production webhook. No replay.
  - Inputs are CONTROLLED payloads (varied values, never varied schema on the valid
    side) over re-attached webhook triggers. The claim language says so.
  - The driver NEVER concludes an outcome. POST /outcome is an accountable human
    conclusion; the driver stops at ready_for_outcome_review. A human runs
    `--conclude <case_id>` per case after reviewing the evidence.
  - Thresholds are the product defaults (30 successes / 10-comparison) everywhere.
  - Before marking a case ready, the SQLite audit must show ZERO duplicate
    source_execution_id rows for the workflow (the poll/sync dedup race is real)
    and >= 30 DISTINCT post-apply ingested executions backing the success count.

Env:  PISAMA_N8N_URL, PISAMA_N8N_API_KEY, PISAMA_SERVER_URL, PISAMA_API_KEY
      PISAMA_CAMPAIGN_DB (path to the server's SQLite, for the audit; optional on
      tiers that skip audit)
Usage:
  --manifest eval/campaigns/manifest_2026-07.json
  --tier {local,live-a,live-b}   --only id1,id2   --max-executions N
  --out results.jsonl            --deactivate-after
  --conclude CASE_ID             (human-invoked, one case, prints evidence first)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

N8N_URL = os.environ.get("PISAMA_N8N_URL", "").rstrip("/")
SERVER_URL = os.environ.get("PISAMA_SERVER_URL", "http://127.0.0.1:8400").rstrip("/")

ALERT_TARGET_NAME = "[pisama-campaign] alerting target"
MALFORMED_MATRIX = [{}, {"unexpected": 1}, []]

FIRED = {"count": 0, "max": 10_000}


class Budget(Exception):
    pass


class ImportRejected(Exception):
    """n8n refused the import/activation — a real compatibility funnel cell."""


# ── plumbing (shapes cloned from run_guardrail_lifecycle.py) ─────────────────

def _req(method: str, url: str, headers: Dict[str, str], body: Any = None,
         timeout: int = 45) -> Any:
    data = None if body is None else json.dumps(body).encode()
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def _n8n(method: str, path: str, body: Any = None) -> Any:
    key = os.environ["PISAMA_N8N_API_KEY"]
    return _req(method, f"{N8N_URL}{path}",
                {"X-N8N-API-KEY": key, "Content-Type": "application/json"}, body)


def _server(method: str, path: str, body: Any = None,
            expect: Optional[int] = None) -> Any:
    key = os.environ["PISAMA_API_KEY"]
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    data = None if body is None else json.dumps(body).encode()
    request = Request(f"{SERVER_URL}{path}", data=data, headers=headers,
                      method=method)
    try:
        with urlopen(request, timeout=90) as response:
            raw = response.read()
            result = json.loads(raw) if raw else {}
            status = response.status
    except HTTPError as exc:
        result = exc.read().decode(errors="replace")
        status = exc.code
    if expect is not None and status != expect:
        raise AssertionError(
            f"{method} {path} -> {status} (expected {expect}): {result}")
    return {"_status": status, "_body": result} if expect is None else result


def _fire(path: str, body: Any) -> None:
    if FIRED["count"] >= FIRED["max"]:
        raise Budget(f"--max-executions {FIRED['max']} reached")
    FIRED["count"] += 1
    try:
        _req("POST", f"{N8N_URL}/webhook/{path}",
             {"Content-Type": "application/json"}, body)
    except HTTPError:
        pass  # a failing run returns 500 to the caller; the run is what matters


def _latest_execution(workflow_id: str) -> Optional[str]:
    execs = _n8n("GET", f"/api/v1/executions?workflowId={workflow_id}&limit=1"
                 ).get("data", [])
    return str(execs[0]["id"]) if execs else None


def _wait_new_execution(workflow_id: str, prev: Optional[str],
                        tries: int = 60) -> Optional[str]:
    for _ in range(tries):
        latest = _latest_execution(workflow_id)
        if latest and latest != prev:
            for _ in range(60):
                ex = _n8n("GET", f"/api/v1/executions/{latest}")
                if ex.get("finished") is not None and ex.get("stoppedAt"):
                    return latest
                time.sleep(0.5)
            return latest
        time.sleep(0.5)
    return None


def _activate(workflow_id: str) -> None:
    _n8n("POST", f"/api/v1/workflows/{workflow_id}/activate")


def _deactivate(workflow_id: str) -> None:
    _n8n("POST", f"/api/v1/workflows/{workflow_id}/deactivate")


def _sync() -> None:
    _server("POST", "/api/v1/n8n/sync", expect=200)


def _fire_and_sync(path: str, workflow_id: str, body: Any) -> Optional[str]:
    """One real execution, ingested: fire -> wait finished -> sync (per-fire sync
    keeps us inside the newest-50 ingestion window and serialized)."""
    prev = _latest_execution(workflow_id)
    _fire(path, body)
    exec_id = _wait_new_execution(workflow_id, prev)
    _sync()
    return exec_id


def _detections_for(workflow_id: str) -> List[Dict[str, Any]]:
    rows = _server("GET", "/api/v1/detections", expect=200)
    return [r for r in rows
            if str(r.get("workflow_id")) == str(workflow_id) and r.get("detected")]


def _case_for(workflow_id: str) -> Optional[Dict[str, Any]]:
    cases = _server("GET", "/api/v1/reliability-cases", expect=200)
    for case in cases:
        if str(case.get("workflow_id")) == str(workflow_id):
            return case
    return None


# ── workflow + target management ─────────────────────────────────────────────

def _list_workflows() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    cursor = ""
    while True:
        suffix = f"&cursor={cursor}" if cursor else ""
        page = _n8n("GET", f"/api/v1/workflows?limit=100{suffix}")
        out.extend(page.get("data", []))
        cursor = page.get("nextCursor")
        if not cursor:
            break
    return out


def ensure_alert_target(existing: Dict[str, str]) -> str:
    """Find-or-create the shared Error Trigger target. NEVER activated — n8n runs
    error workflows without activation, so this costs no Cloud active slot."""
    if ALERT_TARGET_NAME in existing:
        return existing[ALERT_TARGET_NAME]
    created = _n8n("POST", "/api/v1/workflows", {
        "name": ALERT_TARGET_NAME,
        "settings": {"executionOrder": "v1"},
        "nodes": [
            {"parameters": {}, "id": "et", "name": "Error Trigger",
             "type": "n8n-nodes-base.errorTrigger", "typeVersion": 1,
             "position": [0, 0]},
            {"parameters": {}, "id": "noop", "name": "Recorded",
             "type": "n8n-nodes-base.noOp", "typeVersion": 1,
             "position": [260, 0]},
        ],
        "connections": {"Error Trigger": {"main": [[{"node": "Recorded",
                                                     "type": "main", "index": 0}]]}},
    })
    return str((created.get("data") or created)["id"])


def ensure_workflow(entry: Dict[str, Any], prepared: Dict[str, Any],
                    existing: Dict[str, str]) -> str:
    """Idempotent import: reuse by name (a recreated workflow would get a new n8n id
    and orphan its reliability case), else create + activate."""
    name = prepared["name"]
    if name in existing:
        wid = existing[name]
        _activate(wid)
        return wid
    try:
        created = _n8n("POST", "/api/v1/workflows", prepared)
    except HTTPError as exc:
        raise ImportRejected(exc.read().decode(errors="replace")[:300]) from None
    wid = str((created.get("data") or created)["id"])
    try:
        _activate(wid)
    except HTTPError as exc:
        raise ImportRejected(
            "activation: " + exc.read().decode(errors="replace")[:300]) from None
    return wid


# ── payloads ─────────────────────────────────────────────────────────────────

def valid_payload(entry: Dict[str, Any], i: int) -> Optional[Dict[str, Any]]:
    """A candidate SUCCEEDING payload built from the consumer's own body.* reads —
    values varied per fire (never the schema). None when the workflow reads no
    body-satisfiable path (then no succeeding webhook input may exist at all)."""
    chains = entry.get("body_chains") or []
    if not chains:
        return None
    body: Dict[str, Any] = {}
    for chain in chains:
        parts = chain.split(".")[1:]  # strip leading "body"
        if not parts:
            continue
        node = body
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = f"ok-{i}"
    return body


# ── the audit gate ───────────────────────────────────────────────────────────

def audit_workflow(db_path: str, workflow_id: str,
                   applied_at: Optional[str]) -> Dict[str, Any]:
    """Direct SQLite integrity audit. Duplicate source rows would silently inflate
    successful_execution_count (the poll/sync dedup race); distinct post-apply rows
    bound the trustworthy success count."""
    con = sqlite3.connect(db_path)
    try:
        dups = con.execute(
            "SELECT source_execution_id, COUNT(*) c FROM executions "
            "WHERE workflow_id = ? AND source_execution_id IS NOT NULL "
            "GROUP BY 1 HAVING c > 1", (str(workflow_id),)).fetchall()
        distinct_post = 0
        if applied_at:
            distinct_post = con.execute(
                "SELECT COUNT(DISTINCT source_execution_id) FROM executions "
                "WHERE workflow_id = ? AND received_at > ?",
                (str(workflow_id), applied_at)).fetchone()[0]
        return {"duplicate_sources": [d[0] for d in dups],
                "distinct_post_apply": distinct_post}
    finally:
        con.close()


# ── lanes ────────────────────────────────────────────────────────────────────

def input_schema_flow(entry, workflow_id, detection, row, success_target) -> None:
    proposal = _server("POST", "/api/v1/n8n/guardrail",
                       {"detection_id": detection["id"]})
    if proposal["_status"] != 200:
        row["lane"] = "error_route"
        row["lane_reason"] = f"guardrail propose {proposal['_status']}"
        return error_route_flow(entry, workflow_id, detection, row, success_target)
    body = proposal["_body"]
    repair_id = body["repair"]["id"]
    options = body.get("path_options") or {}
    chosen = list(options.get("confirmed") or []) or list(options.get("candidates") or [])
    row["derived_paths"] = chosen
    # Method-leaf screen (C2 product bug: such a guard would reject ALL input).
    if any(p in (entry.get("method_leaf_chains") or []) for p in chosen) or not all(
            p == "body" or p.startswith("body.") for p in chosen):
        row["lane"] = "error_route"
        row["lane_reason"] = "derived path body-unsatisfiable or method-leaf"
        return error_route_flow(entry, workflow_id, detection, row, success_target)

    # MANDATORY pre-apply end-to-end success of the exact valid payload (the
    # valid-side recurrence trap: an unforeseen second failing path post-apply
    # would permanently block 'prevented').
    ok_payload = valid_payload(entry, 0)
    pre_ok = False
    if ok_payload is not None:
        for _ in range(3):
            exec_id = _fire_and_sync(entry["webhook_path"], workflow_id, ok_payload)
            ex = _n8n("GET", f"/api/v1/executions/{exec_id}") if exec_id else {}
            if ex.get("finished") and ex.get("status", "success") != "error":
                pre_ok = True
                break
    if not pre_ok:
        row["lane"] = "error_route"
        row["lane_reason"] = "no pre-apply end-to-end success (valid_passed unachievable)"
        return error_route_flow(entry, workflow_id, detection, row, success_target)

    dest = _server("POST", f"/api/v1/n8n/repairs/{repair_id}/destination",
                   {"destination": "error_workflow"})
    if dest["_status"] != 200:
        row["stage"] = "destination_failed"
        row["detail"] = str(dest["_body"])[:300]
        return
    applied = _server("POST", "/api/v1/n8n/apply", {"repair_id": repair_id})
    if applied["_status"] != 200:
        row["stage"] = "apply_failed"
        row["detail"] = str(applied["_body"])[:300]
        return
    row["repair_id"] = repair_id
    row["stage"] = "applied"
    _activate(workflow_id)  # apply drops the active flag
    time.sleep(2)

    case = _case_for(workflow_id)
    row["case_id"] = case["id"]

    rejected = _fire_and_sync(entry["webhook_path"], workflow_id, {})
    probe = _server("POST",
                    f"/api/v1/reliability-cases/{case['id']}/guard-verification",
                    {"kind": "malformed_rejected", "source_execution_id": rejected})
    row["probe_malformed"] = probe["_status"] == 200
    valid_exec = _fire_and_sync(entry["webhook_path"], workflow_id,
                                valid_payload(entry, 1))
    probe = _server("POST",
                    f"/api/v1/reliability-cases/{case['id']}/guard-verification",
                    {"kind": "valid_passed", "source_execution_id": valid_exec})
    row["probe_valid"] = probe["_status"] == 200
    row["stage"] = "probed"

    _accumulate_successes(entry, workflow_id, row, success_target, offset=2)


ROUTE_MODES = ("n8n_missing_error_workflow", "n8n_error_workflow_target_missing",
               "n8n_error_workflow_missing_trigger")


def error_route_flow(entry, workflow_id, detection, row, success_target) -> None:
    row.setdefault("lane", "error_route")
    # A fallback from the input_schema lane arrives with the SCHEMA detection;
    # error-route propose only accepts error-workflow modes — re-select.
    if detection.get("failure_mode") not in ROUTE_MODES:
        candidates = [d for d in _detections_for(workflow_id)
                      if d.get("failure_mode") in ROUTE_MODES]
        if not candidates:
            row["stage"] = "propose_failed"
            row["detail"] = "no error-workflow detection to fall back to"
            return
        detection = candidates[0]
    proposal = _server("POST", "/api/v1/n8n/error-route",
                       {"detection_id": detection["id"]})
    if proposal["_status"] != 200:
        row["stage"] = "propose_failed"
        row["detail"] = str(proposal["_body"])[:300]
        return
    repair_id = proposal["_body"]["repair"]["id"]
    row["repair_id"] = repair_id
    target = _server("POST", f"/api/v1/n8n/repairs/{repair_id}/error-target",
                     {"target_workflow_id": row["alert_target_id"]})
    if target["_status"] != 200:
        row["stage"] = "target_failed"
        row["detail"] = str(target["_body"])[:300]
        return
    applied = _server("POST", "/api/v1/n8n/apply", {"repair_id": repair_id})
    if applied["_status"] != 200:
        row["stage"] = "apply_failed"
        row["detail"] = str(applied["_body"])[:300]
        return
    row["stage"] = "applied"
    _activate(workflow_id)
    time.sleep(2)  # route-probe ordering uses raw-string timestamps (C5)

    case = _case_for(workflow_id)
    row["case_id"] = case["id"]

    # ONE real routed incident: fire the failing payload, wait for a NEW execution
    # of the TARGET workflow, verify its Error Trigger item references THIS source
    # (the server checks workflow + ordering; provenance is on us), then record.
    target_prev = _latest_execution(row["alert_target_id"])
    _fire_and_sync(entry["webhook_path"], workflow_id, row.get("failing_payload", {}))
    target_exec = _wait_new_execution(row["alert_target_id"], target_prev, tries=40)
    if not target_exec:
        row["stage"] = "route_not_delivered"
        return
    detail = _n8n("GET", f"/api/v1/executions/{target_exec}?includeData=true")
    blob = json.dumps(detail.get("data") or {})
    if str(workflow_id) not in blob:
        row["stage"] = "route_provenance_mismatch"
        return
    _sync()
    probe = _server("POST",
                    f"/api/v1/reliability-cases/{case['id']}/route-verification",
                    {"source_execution_id": target_exec})
    row["probe_route"] = probe["_status"] == 200
    row["stage"] = "probed" if row["probe_route"] else "route_probe_rejected"
    if not row["probe_route"]:
        row["detail"] = str(probe["_body"])[:300]
        return

    _accumulate_successes(entry, workflow_id, row, success_target, offset=0)


def _accumulate_successes(entry, workflow_id, row, target, offset) -> None:
    """Varied-value VALID payloads to the product's 30-success bar — only when a
    succeeding payload exists. Otherwise the case honestly stays observing with a
    standing durable guard, and we say so."""
    if target <= 0:
        row["successes_note"] = "success accumulation skipped on this tier"
        return
    if valid_payload(entry, 0) is None and (entry.get("original_status") == "error"):
        row["successes_note"] = (
            "no succeeding webhook payload exists for this workflow; "
            "case stays observing (standing durable guard)")
        return
    # Pre-probe ONE candidate before committing 30 fires: a workflow that succeeded
    # on empty MANUAL input can still fail on empty WEBHOOK input (the wrapper
    # changes $json). Without this check the loop burns ~30 executions per
    # workflow proving nothing — fatal against a metered Cloud quota.
    probe_payload = valid_payload(entry, offset)
    probe_exec = _fire_and_sync(entry["webhook_path"], workflow_id,
                                probe_payload if probe_payload is not None else {})
    probe = _n8n("GET", f"/api/v1/executions/{probe_exec}") if probe_exec else {}
    if not probe.get("finished") or probe.get("status") == "error":
        row["successes_note"] = (
            "no succeeding webhook payload found (candidate payload fails under "
            "the webhook wrapper); case stays observing (standing durable guard)")
        return
    for i in range(target - 1):
        payload = valid_payload(entry, i + offset + 1)
        _fire_and_sync(entry["webhook_path"], workflow_id,
                       payload if payload is not None else {})
    case = _case_for(workflow_id)
    row["successful_execution_count"] = case.get("successful_execution_count")
    row["recurrence_count"] = case.get("recurrence_count")
    db = os.environ.get("PISAMA_CAMPAIGN_DB")
    if db:
        # The case is created inside mark_repair_applied (same clock, same
        # moment), so its created_at is the post-apply boundary — the OSS server
        # exposes no GET-repair endpoint to read applied_at from.
        row["audit"] = audit_workflow(db, workflow_id, case.get("created_at"))
        clean = not row["audit"]["duplicate_sources"]
    else:
        row["audit"] = "skipped (no PISAMA_CAMPAIGN_DB)"
        clean = True
    threshold = int(os.environ.get(
        "PISAMA_VERIFICATION_MIN_SUCCESSFUL_EXECUTIONS", "30"))
    row["ready_for_outcome_review"] = bool(
        clean
        and (case.get("successful_execution_count") or 0) >= threshold
        and (case.get("recurrence_count") or 0) == 0
        and row.get("stage") == "probed"
    )
    row["stage"] = "ready" if row["ready_for_outcome_review"] else row["stage"]


# ── per-workflow orchestration ───────────────────────────────────────────────

def run_workflow(entry, prepared, existing, alert_id, tier) -> Dict[str, Any]:
    row: Dict[str, Any] = {"id": entry["id"], "lane": None, "stage": "start",
                           "alert_target_id": alert_id}
    try:
        try:
            workflow_id = ensure_workflow(entry, prepared, existing)
        except ImportRejected as exc:
            row["stage"] = "import_failed"
            row["detail"] = str(exc)
            return row
        row["workflow_id"] = workflow_id
        row["stage"] = "activated"

        # Baseline: real failing traffic BEFORE any apply. Tier A gets >=10 so the
        # comparison window can publish; standing-guard tiers get 3.
        baseline_target = {"local": 10, "live-a": 10, "live-b": 3}[tier]
        failing_payload = None
        first = _fire_and_sync(entry["webhook_path"], workflow_id, {})
        if first is None:
            row["stage"] = "no_execution_appeared"
            return row
        detections = _detections_for(workflow_id)
        if any(d["failure_mode"] == "n8n_data_contract" for d in detections) or any(
                d["detector"] == "error_workflow" for d in detections):
            failing_payload = {}
        else:
            for candidate in MALFORMED_MATRIX[1:]:
                _fire_and_sync(entry["webhook_path"], workflow_id, candidate)
                detections = _detections_for(workflow_id)
                if any(d["detector"] in ("schema", "error_workflow")
                       for d in detections):
                    failing_payload = candidate
                    break
        if failing_payload is None:
            row["stage"] = "excluded"
            row["lane"] = "none"
            row["lane_reason"] = "no_observed_failure"
            return row
        row["failing_payload"] = failing_payload
        for _ in range(max(0, baseline_target - 1)):
            _fire_and_sync(entry["webhook_path"], workflow_id, failing_payload)
        row["stage"] = "baseline_done"

        detections = _detections_for(workflow_id)
        schema = [d for d in detections if d["failure_mode"] == "n8n_data_contract"]
        route = [d for d in detections
                 if d["detector"] == "error_workflow"
                 and d["failure_mode"] in ("n8n_missing_error_workflow",
                                           "n8n_error_workflow_target_missing",
                                           "n8n_error_workflow_missing_trigger")]
        success_target = {"local": 30, "live-a": 30, "live-b": 0}[tier]
        if schema:
            row["lane"] = "input_schema"
            input_schema_flow(entry, workflow_id, schema[0], row, success_target)
        elif route:
            row["lane"] = "error_route"
            error_route_flow(entry, workflow_id, route[0], row, success_target)
        else:
            row["stage"] = "excluded"
            row["lane"] = "none"
            row["lane_reason"] = "failure observed but no eligible detection"
        return row
    except Budget:
        raise
    except Exception as exc:  # noqa: BLE001 — one workflow must not sink the run
        row["stage"] = "error"
        row["detail"] = f"{type(exc).__name__}: {exc}"[:300]
        return row


# ── entry ────────────────────────────────────────────────────────────────────

def conclude(case_id: int) -> int:
    """Human-invoked, one case: print the evidence, require typed confirmation."""
    case = _server("GET", f"/api/v1/reliability-cases/{case_id}", expect=200)
    print(json.dumps(case, indent=2))
    answer = input("Conclude this case as PREVENTED? Type 'prevented' to confirm: ")
    if answer.strip() != "prevented":
        print("aborted")
        return 1
    done = _server("POST", f"/api/v1/reliability-cases/{case_id}/outcome",
                   {"outcome": "prevented",
                    "note": "Corpus campaign: reviewed and concluded by operator."},
                   expect=200)
    print("concluded:", done.get("outcome"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="eval/campaigns/manifest_2026-07.json")
    parser.add_argument("--tier", choices=["local", "live-a", "live-b"],
                        default="local")
    parser.add_argument("--only", default="")
    parser.add_argument("--max-executions", type=int, default=2000)
    parser.add_argument("--out", default="campaign_results.jsonl")
    parser.add_argument("--deactivate-after", action="store_true")
    parser.add_argument("--conclude", type=int)
    args = parser.parse_args()

    if args.conclude:
        return conclude(args.conclude)

    FIRED["max"] = args.max_executions
    manifest = json.loads(Path(args.manifest).read_text())
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from corpus_campaign_prepare import reattach_webhook  # noqa: E402

    only = {s for s in args.only.split(",") if s}
    entries = [e for e in manifest["workflows"] if not only or e["id"] in only]

    existing = {w.get("name"): str(w.get("id")) for w in _list_workflows()}
    alert_id = ensure_alert_target(existing)
    print(f"alert target: {alert_id} | workflows to run: {len(entries)} "
          f"| tier {args.tier} | budget {args.max_executions}", flush=True)

    out = Path(args.out)
    done_ids = set()
    if out.exists():  # resume: JSONL is the source of truth
        for line in out.read_text().splitlines():
            try:
                done_ids.add(json.loads(line)["id"])
            except (ValueError, KeyError):
                pass

    health = _server("GET", "/healthz", expect=200)
    summary_env = {
        "server_build_revision": health.get("build_revision"),
        "n8n_url_host": N8N_URL.split("//")[-1].split("/")[0],
        "tier": args.tier,
        "invocation": " ".join(sys.argv),
    }

    with out.open("a") as sink:
        for i, entry in enumerate(entries):
            if entry["id"] in done_ids:
                continue
            corpus_file = (Path(args.manifest).resolve().parents[1]
                           / "data" / "realworld" / f"{entry['id']}.json")
            doc = json.loads(corpus_file.read_text())
            prepared = reattach_webhook(doc["workflowData"], entry)
            print(f"[{i + 1}/{len(entries)}] {entry['id']} "
                  f"(fired so far: {FIRED['count']})", flush=True)
            try:
                row = run_workflow(entry, prepared, existing, alert_id, args.tier)
            except Budget as exc:
                print(f"STOP: {exc}", flush=True)
                break
            if args.deactivate_after and row.get("workflow_id") and \
                    row.get("stage") not in ("ready",):
                try:
                    _deactivate(row["workflow_id"])
                    row["deactivated"] = True
                except Exception:  # noqa: BLE001
                    row["deactivated"] = False
            sink.write(json.dumps(row) + "\n")
            sink.flush()

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    funnel: Dict[str, int] = {}
    for row in rows:
        funnel[row.get("stage", "?")] = funnel.get(row.get("stage", "?"), 0) + 1
    lanes: Dict[str, int] = {}
    for row in rows:
        lanes[str(row.get("lane"))] = lanes.get(str(row.get("lane")), 0) + 1
    summary = {
        "environment": summary_env,
        "total": len(rows),
        "executions_fired": FIRED["count"],
        "stages": dict(sorted(funnel.items())),
        "lanes": dict(sorted(lanes.items())),
        "applied": sum(1 for r in rows if r.get("stage") in
                       ("applied", "probed", "ready")),
        "probed": sum(1 for r in rows if r.get("stage") in ("probed", "ready")),
        "ready_for_outcome_review": sum(
            1 for r in rows if r.get("ready_for_outcome_review")),
    }
    print(json.dumps(summary, indent=2))
    Path(args.out).with_suffix(".summary.json").write_text(
        json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
