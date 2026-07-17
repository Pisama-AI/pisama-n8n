#!/usr/bin/env python3
"""End-to-end proof that Pisama safely INSTALLS and VERIFIES an input-schema guardrail.

Runs the whole lifecycle against a real local n8n + a real Pisama OSS server, asserting
each stage (exit non-zero on any failure):

  baseline failure -> detection -> propose -> apply refused without destination ->
  choose destination -> apply -> malformed input rejected -> valid input passes ->
  both prevention probes recorded -> rollback restores the workflow.

Env:
  PISAMA_N8N_URL          n8n base URL (default http://127.0.0.1:5678)
  PISAMA_N8N_API_KEY      n8n public-API key (required)
  PISAMA_SERVER_URL       Pisama server base URL (default http://127.0.0.1:8477)
  PISAMA_API_KEY          Pisama bearer (required)
The Pisama server must itself be configured with PISAMA_N8N_URL + PISAMA_N8N_API_KEY so
its /sync and apply/rollback reach the same n8n. The guardrail is a free repair, so no
PISAMA_CLOUD_KEY is needed.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

N8N_URL = os.getenv("PISAMA_N8N_URL", "http://127.0.0.1:5678").rstrip("/")
SERVER_URL = os.getenv("PISAMA_SERVER_URL", "http://127.0.0.1:8477").rstrip("/")
WEBHOOK_PATH = "pisama-guardrail-lifecycle"
CONSUMER = "Consumer reads body.required.value"


def _req(method: str, url: str, headers: Dict[str, str], body: Any = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw else {}


def _n8n(method: str, path: str, body: Any = None) -> Any:
    key = os.environ["PISAMA_N8N_API_KEY"]
    return _req(method, f"{N8N_URL}{path}",
                {"X-N8N-API-KEY": key, "Content-Type": "application/json"}, body)


def _server(method: str, path: str, body: Any = None, expect: Optional[int] = None) -> Any:
    key = os.environ["PISAMA_API_KEY"]
    url = f"{SERVER_URL}{path}"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    data = None if body is None else json.dumps(body).encode()
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read()
            result = json.loads(raw) if raw else {}
            status = response.status
    except HTTPError as exc:
        result = exc.read().decode(errors="replace")
        status = exc.code
    if expect is not None and status != expect:
        raise AssertionError(f"{method} {path} -> {status} (expected {expect}): {result}")
    return result


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ok: {message}")


def _lifecycle_workflow() -> Dict[str, Any]:
    return {
        "name": "Pisama guardrail lifecycle",
        "settings": {"executionOrder": "v1"},
        "nodes": [
            # An explicit webhookId is REQUIRED: the n8n public API does not assign one,
            # and without it the production webhook never registers (fires 404).
            {"parameters": {"httpMethod": "POST", "path": WEBHOOK_PATH},
             "webhookId": str(uuid4()),
             "id": "wh", "name": "Webhook", "type": "n8n-nodes-base.webhook",
             "typeVersion": 2, "position": [0, 0]},
            {"parameters": {"mode": "runOnceForAllItems", "language": "javaScript",
                            "jsCode": "return [{ json: { value: $json.body.required.value } }];"},
             "id": "cons", "name": CONSUMER, "type": "n8n-nodes-base.code",
             "typeVersion": 2, "position": [260, 0]},
        ],
        "connections": {"Webhook": {"main": [[{"node": CONSUMER, "type": "main", "index": 0}]]}},
    }


def _fire(body: Dict[str, Any]) -> None:
    try:
        _req("POST", f"{N8N_URL}/webhook/{WEBHOOK_PATH}",
             {"Content-Type": "application/json"}, body)
    except HTTPError:
        pass  # a rejected (stopAndError) run returns 500 to the caller; the run is what matters


def _latest_execution(workflow_id: str) -> Optional[str]:
    execs = _n8n("GET", f"/api/v1/executions?workflowId={workflow_id}&limit=1").get("data", [])
    return str(execs[0]["id"]) if execs else None


def _wait_new_execution(workflow_id: str, prev: Optional[str]) -> str:
    for _ in range(40):
        latest = _latest_execution(workflow_id)
        if latest and latest != prev:
            # wait for it to finish
            for _ in range(40):
                ex = _n8n("GET", f"/api/v1/executions/{latest}")
                if ex.get("finished") is not None and ex.get("stoppedAt"):
                    return latest
                time.sleep(0.5)
            return latest
        time.sleep(0.5)
    raise AssertionError("no new n8n execution appeared")


def _activate(workflow_id: str) -> None:
    _n8n("POST", f"/api/v1/workflows/{workflow_id}/activate")


def _sync() -> Dict[str, Any]:
    return _server("POST", "/api/v1/n8n/sync")


def main() -> int:
    for var in ("PISAMA_N8N_API_KEY", "PISAMA_API_KEY"):
        if not os.environ.get(var):
            print(f"set {var}", file=sys.stderr)
            return 2

    workflow_id = None
    try:
        # ── Stage 1: a workflow that crashes on missing input ──────────────
        print("stage 1: create + activate the consumer workflow")
        created = _n8n("POST", "/api/v1/workflows", _lifecycle_workflow())
        workflow_id = (created.get("data") or created)["id"]
        _activate(workflow_id)
        baseline = _n8n("GET", f"/api/v1/workflows/{workflow_id}")
        baseline_nodes = {n["name"] for n in (baseline.get("data") or baseline)["nodes"]}
        _check(CONSUMER in baseline_nodes, "workflow created with the consumer node")

        # ── Stage 2: baseline failure on malformed input ───────────────────
        print("stage 2: fire malformed input -> baseline data-contract failure")
        prev = _latest_execution(workflow_id)
        _fire({})  # no body.required.value
        _wait_new_execution(workflow_id, prev)
        _sync()
        rows = _server("GET", "/api/v1/detections")
        dc = [r for r in rows
              if r["failure_mode"] == "n8n_data_contract" and r["detected"]
              and r["workflow_id"] == str(workflow_id)]
        _check(bool(dc), "Pisama detected an n8n_data_contract failure")
        detection_id = dc[0]["id"]

        # ── Stage 3: propose the guardrail ─────────────────────────────────
        print("stage 3: propose the input-schema guardrail")
        proposal = _server("POST", "/api/v1/n8n/guardrail",
                            {"detection_id": detection_id}, expect=200)
        repair_id = proposal["repair"]["id"]
        _check(proposal["path_options"]["confirmed"] == ["body.required.value"],
               "required path confirmed from evidence: body.required.value")

        # ── Stage 4: apply is REFUSED before a destination is chosen ────────
        print("stage 4: apply refused without a rejection destination")
        refused = _server("POST", "/api/v1/n8n/apply", {"repair_id": repair_id}, expect=409)
        _check("destination" in str(refused), "apply returns 409 until a destination is chosen")

        # ── Stage 5: choose destination + apply ────────────────────────────
        print("stage 5: choose destination -> apply the guard")
        built = _server("POST", f"/api/v1/n8n/repairs/{repair_id}/destination",
                        {"destination": "error_workflow"}, expect=200)
        guard = built["repair"]["guard_config"]
        applied = _server("POST", "/api/v1/n8n/apply", {"repair_id": repair_id}, expect=200)
        _check(applied["repair"]["status"] == "applied", "guard applied to the live workflow")
        _activate(workflow_id)  # a workflow update can drop the active flag
        live = _n8n("GET", f"/api/v1/workflows/{workflow_id}")
        live_names = {n["name"] for n in (live.get("data") or live)["nodes"]}
        _check(guard["entry_node"] in live_names, "guard nodes are live in n8n")
        case = _server("GET", "/api/v1/reliability-cases")[0]
        case_id = case["id"]

        # ── Stage 6: malformed input is now REJECTED by the guard ──────────
        print("stage 6: malformed input rejected by the installed guard")
        prev = _latest_execution(workflow_id)
        _fire({})
        rejected_exec = _wait_new_execution(workflow_id, prev)
        _sync()
        v = _server("POST", f"/api/v1/reliability-cases/{case_id}/guard-verification",
                    {"kind": "malformed_rejected", "source_execution_id": rejected_exec},
                    expect=200)
        _check(v.get("guard_malformed_rejected_execution_id") is not None,
               "malformed_rejected probe recorded (destination ran, consumer skipped)")

        # ── Stage 7: valid input PASSES through the guard ──────────────────
        print("stage 7: valid input passes through to the consumer")
        prev = _latest_execution(workflow_id)
        _fire({"required": {"value": "present"}})
        valid_exec = _wait_new_execution(workflow_id, prev)
        _sync()
        v = _server("POST", f"/api/v1/reliability-cases/{case_id}/guard-verification",
                    {"kind": "valid_passed", "source_execution_id": valid_exec}, expect=200)
        _check(v.get("guard_valid_passed_execution_id") is not None,
               "valid_passed probe recorded (consumer ran, destination skipped)")

        # ── Stage 8: rollback restores the original workflow ───────────────
        print("stage 8: rollback restores the pre-guard workflow")
        rb = _server("POST", "/api/v1/n8n/rollback", {"repair_id": repair_id}, expect=200)
        _check(rb["repair"]["status"] == "rolled_back", "repair rolled back")
        _activate(workflow_id)
        restored = _n8n("GET", f"/api/v1/workflows/{workflow_id}")
        restored_names = {n["name"] for n in (restored.get("data") or restored)["nodes"]}
        _check(restored_names == baseline_nodes,
               "workflow node set restored to the pre-guard baseline")
        _check(guard["entry_node"] not in restored_names, "guard nodes removed on rollback")

        print("\nDONE: full guardrail lifecycle verified (install + prove + rollback).")
        return 0
    except AssertionError as exc:
        print(f"\nLIFECYCLE FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if workflow_id:
            try:
                _n8n("POST", f"/api/v1/workflows/{workflow_id}/deactivate")
                _n8n("DELETE", f"/api/v1/workflows/{workflow_id}")
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
