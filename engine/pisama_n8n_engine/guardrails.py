"""Reusable, workflow-native controls for evidence-backed n8n failures."""

from __future__ import annotations

import json
from typing import Any, Sequence
from uuid import uuid4


def _required_paths(required_paths: Sequence[str]) -> list[str]:
    """Validate the JSON paths this guard must require at the workflow boundary."""
    paths = list(required_paths)
    if not paths or any(
        not isinstance(path, str)
        or not path.strip()
        or any(not segment for segment in path.split("."))
        for path in paths
    ):
        raise ValueError("required_paths must contain non-empty dot-separated JSON paths")
    return paths


def input_schema_guardrail(
    required_paths: Sequence[str],
    *,
    name_prefix: str = "Pisama",
    position: Sequence[int] = (0, 0),
) -> dict[str, Any]:
    """Return an n8n-native input-schema guardrail fragment.

    The fragment uses a Code node to record missing paths, an IF node to branch, then
    Code nodes that either remove guard metadata for the business path or project a
    small rejection record. This is deliberately a subgraph rather than a Code node
    with multiple outputs: n8n's public workflow API rejects that unsupported shape.

    Connect the source to ``entry_node``, the business path to ``validated_node``, and
    the error/rejection path to ``rejected_node``. The returned connections are only
    internal to the fragment.
    """
    paths = _required_paths(required_paths)
    if len(position) != 2 or not all(isinstance(value, int) for value in position):
        raise ValueError("position must contain exactly two integers")
    if not isinstance(name_prefix, str) or not name_prefix.strip():
        raise ValueError("name_prefix must be a non-empty string")

    paths_json = json.dumps(paths)
    inspection_name = f"{name_prefix} input schema inspection"
    route_name = f"{name_prefix} input schema valid?"
    rejected_name = f"{name_prefix} rejected input"
    validated_name = f"{name_prefix} validated input"
    inspection_code = f"""const requiredPaths = {paths_json};

function valueAtPath(value, path) {{
  return path.split('.').reduce(
    (current, segment) => current !== null && typeof current === 'object'
      ? current[segment]
      : undefined,
    value,
  );
}}

return $input.all().map((item) => {{
  const missing = requiredPaths.filter((path) => {{
    const value = valueAtPath(item.json, path);
    return value === undefined || value === null;
  }});
  return {{
    ...item,
    json: {{
      ...item.json,
      _pisama_input_schema: {{ valid: missing.length === 0, missing }},
    }},
  }};
}});"""
    rejected_code = """return $input.all().map((item) => ({
  json: {
    _pisama_input_schema: {
      valid: false,
      missing: item.json._pisama_input_schema.missing,
    },
  },
}));"""
    validated_code = """return $input.all().map(({ json, ...item }) => {
  const { _pisama_input_schema, ...original } = json;
  return { ...item, json: original };
});"""
    x, y = position
    return {
        "entry_node": inspection_name,
        "validated_node": validated_name,
        "rejected_node": rejected_name,
        "nodes": [
            {
                "id": str(uuid4()),
                "name": inspection_name,
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [x, y],
                "parameters": {
                    "mode": "runOnceForAllItems",
                    "language": "javaScript",
                    "jsCode": inspection_code,
                },
            },
            {
                "id": str(uuid4()),
                "name": route_name,
                "type": "n8n-nodes-base.if",
                "typeVersion": 2.2,
                "position": [x + 220, y],
                "parameters": {
                    "conditions": {
                        "options": {
                            "caseSensitive": True,
                            "leftValue": "",
                            "typeValidation": "strict",
                            "version": 2,
                        },
                        "combinator": "and",
                        "conditions": [
                            {
                                "operator": {
                                    "type": "boolean",
                                    "operation": "true",
                                    "singleValue": True,
                                },
                                "leftValue": "={{ $json._pisama_input_schema.valid }}",
                                "rightValue": "",
                            }
                        ],
                    },
                    "options": {},
                },
            },
            {
                "id": str(uuid4()),
                "name": rejected_name,
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [x + 440, y + 120],
                "parameters": {
                    "mode": "runOnceForAllItems",
                    "language": "javaScript",
                    "jsCode": rejected_code,
                },
            },
            {
                "id": str(uuid4()),
                "name": validated_name,
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [x + 440, y - 120],
                "parameters": {
                    "mode": "runOnceForAllItems",
                    "language": "javaScript",
                    "jsCode": validated_code,
                },
            },
        ],
        "connections": {
            inspection_name: {
                "main": [[{"node": route_name, "type": "main", "index": 0}]]
            },
            route_name: {
                "main": [
                    [{"node": validated_name, "type": "main", "index": 0}],
                    [{"node": rejected_name, "type": "main", "index": 0}],
                ]
            },
        },
    }


def input_schema_guardrail_recommendation() -> str:
    """Return the customer-facing remediation that names the reusable control."""
    return (
        "Add the reusable Pisama input-schema guard before the consumer: declare the "
        "required JSON paths, route its rejected terminal node to a rejection or error "
        "path, and connect only its validated terminal node to the business path."
    )
