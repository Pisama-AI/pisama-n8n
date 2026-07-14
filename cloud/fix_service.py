"""Pisama cloud — fix-generation service (the PAID tier, NOT part of the OSS repo).

This is a minimal stand-in for the monorepo's closed healing/fix machinery, built so the
self-host paid seam can be demonstrated end-to-end. It takes a detection + the workflow,
asks Claude for a single targeted fix, applies it deterministically, and returns the
mutated workflow. The real product reuses the monorepo's `fixes/` + `healing/` engine.

Run: ANTHROPIC_API_KEY=... uvicorn cloud.fix_service:app --port 8500
Auth: any Bearer token (this is the scaffold cloud; the real one validates entitlements).
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict

from anthropic import Anthropic
from fastapi import FastAPI

app = FastAPI(title="Pisama Cloud — Fix Service (scaffold)")

FIX_MODEL = os.environ.get("PISAMA_FIX_MODEL", "claude-sonnet-5")

_FIX_TOOL = {
    "name": "propose_fix",
    "description": "Propose ONE concrete, minimal fix to an n8n workflow for the detected failure.",
    "input_schema": {
        "type": "object",
        "properties": {
            "explanation": {"type": "string", "description": "Plain-English fix, 1-2 sentences."},
            "target": {"type": "string", "enum": ["settings", "node"],
                       "description": "Patch the workflow settings or a specific node's parameters."},
            "node_name": {"type": "string", "description": "Node to patch (required when target=node)."},
            "key": {"type": "string", "description": "Parameter/setting key to set."},
            "value": {"description": "New value for the key (number, string, or bool)."},
        },
        "required": ["explanation", "target", "key", "value"],
    },
}


def _apply_patch(workflow: Dict[str, Any], fix: Dict[str, Any]) -> Dict[str, Any]:
    wf = copy.deepcopy(workflow)
    if fix["target"] == "settings":
        wf.setdefault("settings", {})[fix["key"]] = fix["value"]
    else:
        for node in wf.get("nodes", []):
            if node.get("name") == fix.get("node_name"):
                node.setdefault("parameters", {})[fix["key"]] = fix["value"]
                break
    return wf


@app.post("/v1/n8n/fix")
async def fix(body: Dict[str, Any]) -> Dict[str, Any]:
    detection = body.get("detection", {})
    workflow = body.get("workflow", {})
    node_summary = [
        {"name": n.get("name"), "type": n.get("type")}
        for n in workflow.get("nodes", [])
    ]
    client = Anthropic()
    msg = client.messages.create(
        model=FIX_MODEL,
        max_tokens=1024,
        tools=[_FIX_TOOL],
        tool_choice={"type": "tool", "name": "propose_fix"},
        messages=[{
            "role": "user",
            "content": (
                "An n8n workflow failure was detected. Propose one minimal fix.\n\n"
                f"Detection: {json.dumps(detection)}\n"
                f"Workflow settings: {json.dumps(workflow.get('settings', {}))}\n"
                f"Nodes: {json.dumps(node_summary)}\n"
            ),
        }],
    )
    fix_input: Dict[str, Any] = {}
    for block in msg.content:
        if block.type == "tool_use":
            fix_input = block.input
            break

    mutated = _apply_patch(workflow, fix_input)
    patch_ops = [{
        "op": "set",
        "target": fix_input.get("target"),
        "node": fix_input.get("node_name"),
        "key": fix_input.get("key"),
        "value": fix_input.get("value"),
    }]
    return {
        "explanation": fix_input.get("explanation", ""),
        "patch_ops": patch_ops,
        "mutated_workflow": mutated,
    }
