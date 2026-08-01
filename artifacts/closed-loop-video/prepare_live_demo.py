#!/usr/bin/env python3
"""Create a clearly labeled synthetic n8n workflow for the live demo video."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[2]
DATASET_ID = "video-synthetic-v1"


CASES = (
    (
        "SYN-01-clean-order-handoff",
        "Clean order handoff",
        "server/tests/fixtures/executions/healthy/HEALTHY-01.json",
        [],
    ),
    (
        "SYN-02-clean-invoice-agent",
        "Clean invoice agent",
        "server/tests/fixtures/executions/healthy/HEALTHY-02.json",
        [],
    ),
    (
        "SYN-03-timeout-inventory-sync",
        "Timeout in inventory sync",
        "server/tests/fixtures/executions/timeout/TIMEOUT-01.json",
        ["F13"],
    ),
    (
        "SYN-04-missing-customer-field",
        "Missing required customer field",
        "server/tests/fixtures/executions/data_contract/CLOUD-112117-missing-required-value.json",
        ["n8n_data_contract", "n8n_expression", "n8n_missing_error_workflow"],
    ),
    (
        "SYN-05-tool-node-error",
        "Tool node throws an error",
        "server/tests/fixtures/executions/error/ERROR-01-throw.json",
        ["n8n_node_error", "n8n_missing_error_workflow"],
    ),
)


def _data(response: httpx.Response) -> Any:
    response.raise_for_status()
    body = response.json()
    return body.get("data", body)


def _synthetic_cases() -> list[dict[str, Any]]:
    result = []
    for index, (case_id, scenario, payload_path, expected_modes) in enumerate(CASES, 1):
        payload = json.loads((ROOT / payload_path).read_text(encoding="utf-8"))
        payload = copy.deepcopy(payload)
        payload["id"] = f"video-synth-{index:02d}"
        payload["workflowId"] = f"video-synth-workflow-{index:02d}"
        workflow = payload.get("workflowData") or payload.get("workflow") or {}
        workflow["id"] = f"video-synth-workflow-{index:02d}"
        workflow["name"] = f"SYNTHETIC DEMO: {scenario}"
        payload["customData"] = {
            **(payload.get("customData") or {}),
            "pisama_dataset": DATASET_ID,
            "synthetic": True,
            "scenario": scenario,
        }
        result.append(
            {
                "dataset_id": DATASET_ID,
                "case_id": case_id,
                "scenario": scenario,
                "synthetic": True,
                "expected_modes": expected_modes,
                "label_evidence": (
                    "Synthetic teaching case derived from a detector fixture. "
                    "Excluded from the verified 19-case release corpus."
                ),
                "execution_payload": payload,
            }
        )
    return result


def _node(node_id: str, name: str, node_type: str, position: list[int], parameters: dict) -> dict:
    return {
        "id": node_id,
        "name": name,
        "type": node_type,
        "typeVersion": 2 if node_type == "n8n-nodes-base.code" else 1,
        "position": position,
        "parameters": parameters,
    }


def _http_node(node_id: str, name: str, position: list[int], url: str, body: str, auth: str) -> dict:
    node = _node(
        node_id,
        name,
        "n8n-nodes-base.httpRequest",
        position,
        {
            "method": "POST",
            "url": url,
            "sendHeaders": True,
            "headerParameters": {"parameters": [{"name": "Authorization", "value": auth}]},
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": body,
            "options": {},
        },
    )
    node["typeVersion"] = 4.2
    return node


def _workflow(cases: list[dict[str, Any]], auth: str) -> dict:
    source_code = "const cases = " + json.dumps(cases, separators=(",", ":")) + ";\nreturn cases.map((json) => ({ json }));"
    compare_code = """const source = $('Generate 5 synthetic cases').item.json;
const expected = [...new Set(source.expected_modes)].sort();
const actual = [...new Set($json.fired_modes ?? [])].sort();
const missing = expected.filter((mode) => !actual.includes(mode));
const unexpected = actual.filter((mode) => !expected.includes(mode));
return { json: {
  synthetic: true,
  case_id: source.case_id,
  scenario: source.scenario,
  expected_modes: expected,
  actual_modes: actual,
  exact_set_match: missing.length === 0 && unexpected.length === 0,
  missing_modes: missing,
  unexpected_modes: unexpected,
  detector_count: $json.detection_count,
}};"""
    receipt_code = """const source = $('Generate 5 synthetic cases').item.json;
return { json: {
  synthetic: true,
  case_id: source.case_id,
  scenario: source.scenario,
  retained_execution_id: $json.execution_id,
  duplicate_prevented: $json.deduplicated ?? false,
}};"""
    nodes = [
        {
            "id": "note-synthetic",
            "name": "SYNTHETIC DATA ONLY",
            "type": "n8n-nodes-base.stickyNote",
            "typeVersion": 1,
            "position": [-700, -420],
            "parameters": {
                "content": (
                    "# SYNTHETIC DATA ONLY\n\n"
                    "Five teaching cases: two clean flows and three failures.\n\n"
                    "These rows are excluded from the verified 19-case release corpus and from production accuracy claims."
                ),
                "height": 270,
                "width": 560,
                "color": 7,
            },
        },
        _node("trigger", "Run the live demo", "n8n-nodes-base.manualTrigger", [-560, 0], {}),
        _node(
            "generate",
            "Generate 5 synthetic cases",
            "n8n-nodes-base.code",
            [-300, 0],
            {"mode": "runOnceForAllItems", "jsCode": source_code},
        ),
        _http_node(
            "evaluate",
            "Detect failures with Pisama",
            [0, -100],
            "http://127.0.0.1:8501/api/v1/n8n/evaluate",
            "={{ $json.execution_payload }}",
            auth,
        ),
        _node(
            "compare",
            "Compare expected and actual",
            "n8n-nodes-base.code",
            [300, -100],
            {"mode": "runOnceForEachItem", "jsCode": compare_code},
        ),
        _http_node(
            "retain",
            "Retain for human review",
            [0, 200],
            "http://127.0.0.1:8501/api/v1/n8n/evaluation-ingest",
            "={{ { dataset_id: $json.dataset_id, case_id: $json.case_id, execution_payload: $json.execution_payload } }}",
            auth,
        ),
        _node(
            "receipt",
            "Show idempotent receipt",
            "n8n-nodes-base.code",
            [300, 200],
            {"mode": "runOnceForEachItem", "jsCode": receipt_code},
        ),
    ]
    return {
        "name": "VIDEO DEMO: synthetic clean and failure flows",
        "nodes": nodes,
        "connections": {
            "Run the live demo": {
                "main": [[{"node": "Generate 5 synthetic cases", "type": "main", "index": 0}]]
            },
            "Generate 5 synthetic cases": {
                "main": [[
                    {"node": "Detect failures with Pisama", "type": "main", "index": 0},
                    {"node": "Retain for human review", "type": "main", "index": 0},
                ]]
            },
            "Detect failures with Pisama": {
                "main": [[{"node": "Compare expected and actual", "type": "main", "index": 0}]]
            },
            "Retain for human review": {
                "main": [[{"node": "Show idempotent receipt", "type": "main", "index": 0}]]
            },
        },
        "settings": {"executionOrder": "v1"},
        "pinData": {},
        "active": False,
        "tags": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--n8n-url",
        default=os.getenv("PISAMA_VIDEO_N8N_URL", "http://127.0.0.1:5701"),
    )
    parser.add_argument(
        "--n8n-email",
        default=os.getenv("PISAMA_VIDEO_N8N_EMAIL", "demo@pisama.local"),
    )
    parser.add_argument(
        "--n8n-password",
        default=os.getenv("PISAMA_VIDEO_N8N_PASSWORD"),
    )
    parser.add_argument(
        "--source-workflow-id",
        default=os.getenv("PISAMA_VIDEO_SOURCE_WORKFLOW_ID"),
    )
    args = parser.parse_args()
    if not args.n8n_password or not args.source_workflow_id:
        parser.error(
            "set --n8n-password and --source-workflow-id, or their PISAMA_VIDEO_* environment variables"
        )
    cases = _synthetic_cases()
    client = httpx.Client(base_url=args.n8n_url, timeout=60)
    login = client.post(
        "/rest/login",
        json={"emailOrLdapLoginId": args.n8n_email, "password": args.n8n_password},
    )
    login.raise_for_status()
    source = _data(client.get(f"/rest/workflows/{args.source_workflow_id}"))
    auth = next(
        parameter["value"]
        for node in source["nodes"]
        if node["name"] == "Evaluate execution with Pisama"
        for parameter in node["parameters"]["headerParameters"]["parameters"]
        if parameter["name"] == "Authorization"
    )
    created = _data(client.post("/rest/workflows", json=_workflow(cases, auth)))
    print(
        json.dumps(
            {
                "dataset_id": DATASET_ID,
                "case_count": len(cases),
                "workflow_id": created["id"],
                "workflow_url": f"{args.n8n_url}/workflow/{created['id']}",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
