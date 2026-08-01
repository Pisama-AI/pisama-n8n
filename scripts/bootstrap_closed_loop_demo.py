#!/usr/bin/env python3
"""Provision an isolated n8n evaluation table/workflow and a Pisama score run."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx


def _data(response: httpx.Response) -> Any:
    response.raise_for_status()
    body = response.json()
    return body.get("data", body)


def _dataset_rows(root: Path, manifest: dict, dataset_id: str) -> list[dict]:
    return [
        {
            "dataset_id": dataset_id,
            "case_id": case["id"],
            "execution_payload": json.dumps(
                json.loads((root / case["payload_path"]).read_text(encoding="utf-8")),
                separators=(",", ":"),
            ),
            "expected_modes": json.dumps(case["expected_modes"], separators=(",", ":")),
            "label_evidence": "\n".join(case["label_evidence"]),
        }
        for case in manifest["cases"]
    ]


def _configure_workflow(
    workflow_path: Path,
    data_table_id: str,
    pisama_api_url: str,
    pisama_api_key: str,
) -> dict:
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    for key in ("versionId", "id", "createdAt", "updatedAt"):
        workflow.pop(key, None)
    workflow["active"] = False
    for node in workflow["nodes"]:
        parameters = node.get("parameters", {})
        if "dataTableId" in parameters:
            parameters["dataTableId"]["value"] = data_table_id
        if node["name"] == "Evaluate execution with Pisama":
            parameters["url"] = f"{pisama_api_url}/api/v1/n8n/evaluate"
        elif node["name"] == "Retain execution for review":
            parameters["url"] = f"{pisama_api_url}/api/v1/n8n/evaluation-ingest"
        else:
            continue
        parameters.pop("authentication", None)
        parameters.pop("genericAuthType", None)
        parameters["sendHeaders"] = True
        parameters["headerParameters"] = {
            "parameters": [
                {"name": "Authorization", "value": f"Bearer {pisama_api_key}"}
            ]
        }
    return workflow


def bootstrap_n8n(
    root: Path,
    n8n_url: str,
    password: str,
    pisama_api_url: str,
    pisama_api_key: str,
    manifest: dict,
    dataset_id: str,
) -> dict:
    client = httpx.Client(base_url=n8n_url, timeout=60)
    owner = {
        "email": "demo@pisama.local",
        "firstName": "Pisama",
        "lastName": "Demo",
        "password": password,
    }
    setup = client.post("/rest/owner/setup", json=owner)
    if setup.status_code != 200:
        login = client.post(
            "/rest/login",
            json={
                "emailOrLdapLoginId": owner["email"],
                "password": password,
            },
        )
        if login.status_code != 200:
            raise RuntimeError(
                f"n8n owner setup failed ({setup.status_code}: {setup.text}); "
                f"login failed ({login.status_code}: {login.text})"
            )
    projects = _data(client.get("/rest/projects"))
    project_id = projects[0]["id"]
    columns = [
        {"name": name, "type": "string"}
        for name in (
            "dataset_id",
            "case_id",
            "execution_payload",
            "expected_modes",
            "label_evidence",
        )
    ]
    table = _data(
        client.post(
            f"/rest/projects/{project_id}/data-tables",
            json={"name": "Pisama verified 19-case corpus", "columns": columns},
        )
    )
    rows = _dataset_rows(root, manifest, dataset_id)
    _data(
        client.post(
            f"/rest/projects/{project_id}/data-tables/{table['id']}/insert",
            json={"data": rows, "returnType": "count"},
        )
    )
    workflow = _configure_workflow(
        root / "examples" / "pisama-closed-loop-evaluation.json",
        table["id"],
        pisama_api_url,
        pisama_api_key,
    )
    created_workflow = _data(client.post("/rest/workflows", json=workflow))
    return {
        "project_id": project_id,
        "data_table_id": table["id"],
        "data_table_rows": len(rows),
        "workflow_id": created_workflow["id"],
    }


def bootstrap_pisama(
    pisama_api_url: str,
    pisama_api_key: str,
    holdout_key: str,
    baseline_revision: str,
) -> dict:
    headers = {
        "Authorization": f"Bearer {pisama_api_key}",
        "X-Pisama-Holdout-Key": holdout_key,
    }
    client = httpx.Client(base_url=pisama_api_url, headers=headers, timeout=60)
    protocol = _data(
        client.post(
            "/api/v1/evaluation-protocols",
            json={
                "name": "Verified 19-case demo",
                "baseline_build_revision": baseline_revision,
            },
        )
    )
    run = _data(
        client.post(
            "/api/v1/evaluation-runs",
            json={"protocol_id": protocol["id"]},
        )
    )
    for _ in range(300):
        run = _data(client.get(f"/api/v1/evaluation-runs/{run['id']}"))
        if run["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.1)
    if run["status"] != "succeeded":
        raise RuntimeError(f"Pisama evaluation run failed: {run.get('error')}")
    return {
        "protocol_id": protocol["id"],
        "evaluation_run_id": run["id"],
        "case_count": run["case_count"],
        "exact_set_accuracy": run["result"]["exact_set_accuracy"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--n8n-url", required=True)
    parser.add_argument("--n8n-password", required=True)
    parser.add_argument("--pisama-api-url", required=True)
    parser.add_argument("--pisama-api-key", required=True)
    parser.add_argument("--holdout-key", required=True)
    parser.add_argument("--baseline-revision", required=True)
    args = parser.parse_args()
    manifest = json.loads(
        (args.root / "eval" / "closed_loop_cases.json").read_text(encoding="utf-8")
    )
    dataset_id = "pisama-verified-19-v1"
    n8n = bootstrap_n8n(
        args.root,
        args.n8n_url,
        args.n8n_password,
        args.pisama_api_url,
        args.pisama_api_key,
        manifest,
        dataset_id,
    )
    pisama = bootstrap_pisama(
        args.pisama_api_url,
        args.pisama_api_key,
        args.holdout_key,
        args.baseline_revision,
    )
    print(json.dumps({"n8n": n8n, "pisama": pisama}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
