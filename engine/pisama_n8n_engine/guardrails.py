"""Reusable, workflow-native controls for evidence-backed n8n failures."""

from __future__ import annotations

import copy
import json
import re
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
      && Object.hasOwn(current, segment)
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
                                # Real n8n captures carry a per-condition id; include it
                                # so a live import matches the shape n8n itself exports.
                                "id": str(uuid4()),
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


def assert_safe_guardrail_diff(
    baseline: dict[str, Any],
    mutated: dict[str, Any],
    fragment_node_names: Sequence[str],
) -> None:
    """Guard a guardrail-mutated workflow before it is written to live n8n.

    Even though the mutated workflow is server-generated, this is defense in depth: the
    ONLY node changes allowed are ADDING exactly ``fragment_node_names`` (the guard +
    destination). No existing node may be removed, retyped, or have its credentials
    changed. Raises GuardrailInsertionError on any violation.
    """
    expected_added = set(fragment_node_names)

    def _by_name(wf: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            n.get("name"): n
            for n in (wf.get("nodes") or [])
            if isinstance(n, dict) and n.get("name")
        }

    base = _by_name(baseline)
    mut = _by_name(mutated)
    added = set(mut) - set(base)
    removed = set(base) - set(mut)
    if removed:
        raise GuardrailInsertionError(
            f"guardrail apply may not remove nodes (removed={sorted(removed)})"
        )
    if added != expected_added:
        raise GuardrailInsertionError(
            f"guardrail apply added unexpected nodes "
            f"(added={sorted(added)}, expected={sorted(expected_added)})"
        )
    for name, bnode in base.items():
        mnode = mut[name]
        for field in ("type", "typeVersion"):
            if mnode.get(field) != bnode.get(field):
                raise GuardrailInsertionError(
                    f"guardrail apply may not change existing node {name!r} {field}"
                )
        if mnode.get("credentials") != bnode.get("credentials"):
            raise GuardrailInsertionError(
                f"guardrail apply may not change existing node {name!r} credentials"
            )


def input_schema_guardrail_recommendation() -> str:
    """Return the customer-facing remediation that names the reusable control."""
    return (
        "Add the reusable Pisama input-schema guard before the consumer: declare the "
        "required JSON paths, route its rejected terminal node to a rejection or error "
        "path, and connect only its validated terminal node to the business path."
    )


# ── observed-path extraction (evidence-grounded, never invented) ─────────────

# The property-read failures a schema guard can actually prevent. Anything else
# (ReferenceError typos, syntax errors) is an expression failure the guard cannot help.
_PROPERTY_READ_PATTERNS = (
    re.compile(r"Cannot read propert(?:y|ies) of (?:undefined|null) \(reading '([^']+)'\)"),
    re.compile(r"Cannot read property '([^']+)' of (?:undefined|null)"),
    re.compile(r"undefined is not an object \(evaluating '[^']*\.([A-Za-z0-9_$]+)'\)"),
)

# Property chains as a consumer reads them: $json.a.b.c / item.json.a.b / $input.item.json.a
_CHAIN_PATTERN = re.compile(
    r"(?:\$json|(?:\$input\.)?item\.json|\$\(['\"][^'\"]+['\"]\)\.item\.json)"
    r"((?:\.[A-Za-z_$][A-Za-z0-9_$]*)+)"
)


def property_read_leaf(message: Any) -> str | None:
    """The property whose read failed, from a recorded n8n error message, else None."""
    if not isinstance(message, str):
        return None
    for pattern in _PROPERTY_READ_PATTERNS:
        match = pattern.search(message)
        if match:
            return match.group(1)
    return None


def observed_consumer_input(execution: Any, consumer_node: str) -> Any:
    """The item json a consumer node received in a recorded execution, or None.

    In n8n runData a node's input is its source node's output; the run record carries a
    ``source`` back-reference. The guard is spliced onto this same edge, so this is
    exactly the shape the guard would inspect — which is what lets a required path be
    CONFIRMED against real evidence rather than assumed.
    """
    if not isinstance(execution, dict):
        return None
    run_data = (
        ((execution.get("data") or {}).get("resultData") or {}).get("runData") or {}
    )
    runs = run_data.get(consumer_node)
    if not runs or not isinstance(runs[0], dict):
        return None
    source = runs[0].get("source") or []
    prev = source[0].get("previousNode") if source and isinstance(source[0], dict) else None
    if not prev:
        return None
    prev_runs = run_data.get(prev)
    if not prev_runs or not isinstance(prev_runs[0], dict):
        return None
    main = ((prev_runs[0].get("data") or {}).get("main")) or []
    items = main[0] if main and isinstance(main[0], list) else []
    first = items[0] if items and isinstance(items[0], dict) else None
    return first.get("json") if isinstance(first, dict) else None


def _value_at_path(value: Any, path: str) -> Any:
    for segment in path.split("."):
        if not isinstance(value, dict) or segment not in value:
            return None
        value = value[segment]
    return value


def observed_required_paths(
    failing_node_code: str,
    error_message: str,
    observed_input_json: Any = None,
) -> dict[str, list[str]]:
    """Derive the guard's required paths from evidence, never inventing them.

    - ``failing_node_code``: the failing consumer's jsCode / expression text.
    - ``error_message``: the recorded runtime error (gives the failing leaf).
    - ``observed_input_json``: the item json the consumer actually received (the
      upstream node's recorded output), when available.

    Returns ``{"confirmed": [...], "candidates": [...]}``. A path is CONFIRMED when the
    consumer's code reads it, its final segment matches the failing leaf, and walking it
    through the observed input actually fails (missing or null on the way) — i.e. the
    guard, inserted immediately upstream of this consumer, would have rejected exactly
    this input. Chains that match the leaf but cannot be verified against a recorded
    input are CANDIDATES for the operator to confirm. No match -> both lists empty; the
    caller must fall back to operator-supplied paths rather than guessing.
    """
    leaf = property_read_leaf(error_message)
    if leaf is None or not isinstance(failing_node_code, str):
        return {"confirmed": [], "candidates": []}

    chains: list[str] = []
    for match in _CHAIN_PATTERN.finditer(failing_node_code):
        path = match.group(1).lstrip(".")
        segments = path.split(".")
        if leaf in segments:
            # Guard up to and including the failing leaf: reads deeper than the leaf
            # fail at the leaf's level, so requiring beyond it would over-constrain.
            chains.append(".".join(segments[: segments.index(leaf) + 1]))
    # de-dup, preserve order
    chains = list(dict.fromkeys(chains))

    if observed_input_json is None:
        return {"confirmed": [], "candidates": chains}

    confirmed = [
        path for path in chains if _value_at_path(observed_input_json, path) is None
    ]
    candidates = [path for path in chains if path not in confirmed]
    return {"confirmed": confirmed, "candidates": candidates}


# ── rejection destinations (operator-chosen, workflow-native) ────────────────

DESTINATION_KINDS = ("error_workflow", "alert", "respond_422")


class GuardrailDestinationError(ValueError):
    """The chosen rejection destination is invalid or incompatible with the workflow."""


def rejection_destination(
    kind: str,
    *,
    name_prefix: str = "Pisama",
    position: Sequence[int] = (0, 0),
    alert_url: str | None = None,
) -> dict[str, Any]:
    """Build the terminal node the guard's rejected branch routes into.

    - ``error_workflow``: a Stop and Error node — marks the execution failed and fires
      the workflow's configured error workflow (n8n's native alerting hook).
    - ``alert``: an HTTP Request POSTing the rejection record (missing path names only,
      never payload values) to an operator-supplied URL.
    - ``respond_422``: a Respond to Webhook node returning 422 with the missing paths.
      Only valid when the workflow's webhook trigger uses responseMode=responseNode —
      the caller validates that compatibility.
    """
    if kind not in DESTINATION_KINDS:
        raise GuardrailDestinationError(
            f"destination must be one of {DESTINATION_KINDS}, got {kind!r}"
        )
    x, y = position
    if kind == "error_workflow":
        return {
            "id": str(uuid4()),
            "name": f"{name_prefix} rejected: stop and error",
            "type": "n8n-nodes-base.stopAndError",
            "typeVersion": 1,
            "position": [x, y],
            "parameters": {
                "errorMessage": (
                    "={{ 'Pisama input-schema guard rejected this input. Missing: ' "
                    "+ ($json._pisama_input_schema.missing || []).join(', ') }}"
                ),
            },
        }
    if kind == "alert":
        if not isinstance(alert_url, str) or not alert_url.startswith(("http://", "https://")):
            raise GuardrailDestinationError(
                "alert destination requires an http(s) alert_url"
            )
        return {
            "id": str(uuid4()),
            "name": f"{name_prefix} rejected: alert",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [x, y],
            "parameters": {
                "method": "POST",
                "url": alert_url,
                "sendBody": True,
                "specifyBody": "json",
                # The rejection record carries only validity + missing path NAMES.
                "jsonBody": "={{ JSON.stringify($json._pisama_input_schema) }}",
                "options": {},
            },
        }
    # respond_422
    return {
        "id": str(uuid4()),
        "name": f"{name_prefix} rejected: 422 response",
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1.1,
        "position": [x, y],
        "parameters": {
            "respondWith": "json",
            "responseBody": (
                "={{ JSON.stringify({ error: 'invalid input', "
                "missing: $json._pisama_input_schema.missing }) }}"
            ),
            "options": {"responseCode": 422},
        },
    }


# ── whole-workflow assembly (deterministic; the repair the server applies) ───


class GuardrailInsertionError(ValueError):
    """The guard cannot be inserted safely into this workflow; reason in the message."""


def _webhook_trigger(workflow: dict[str, Any]) -> dict[str, Any] | None:
    for node in workflow.get("nodes", []):
        if isinstance(node, dict) and node.get("type") == "n8n-nodes-base.webhook":
            return node
    return None


def validate_destination_compatibility(workflow: dict[str, Any], kind: str) -> None:
    """Raise GuardrailDestinationError when the destination cannot work here."""
    if kind == "respond_422":
        trigger = _webhook_trigger(workflow)
        if trigger is None:
            raise GuardrailDestinationError(
                "respond_422 requires a webhook-triggered workflow"
            )
        if (trigger.get("parameters") or {}).get("responseMode") != "responseNode":
            raise GuardrailDestinationError(
                "respond_422 requires the webhook's responseMode to be 'responseNode'; "
                "changing responseMode would alter the valid path's behavior, so Pisama "
                "does not flip it automatically"
            )


def insert_guard_into_workflow(
    workflow: dict[str, Any],
    required_paths: Sequence[str],
    failing_node: str,
    destination: str,
    *,
    alert_url: str | None = None,
    name_prefix: str = "Pisama",
) -> dict[str, Any]:
    """Return a mutated deep copy with the guard inserted upstream of ``failing_node``.

    Deterministic, model-free. The guard sees exactly the item shape the failing
    consumer sees (it is spliced into the consumer's single main-input edge), so the
    required paths are the consumer-observed paths verbatim — no boundary translation.

    Refuses (GuardrailInsertionError) rather than guessing when: the failing node does
    not exist, has zero or multiple main-input edges, or a name collision cannot be
    resolved. Returns ``{"workflow", "fragment_node_names", "destination_node_name",
    "entry_node", "validated_node", "rejected_node"}``.
    """
    validate_destination_compatibility(workflow, destination)

    wf = copy.deepcopy(workflow)
    nodes_by_name = {
        n.get("name"): n for n in wf.get("nodes", []) if isinstance(n, dict)
    }
    if failing_node not in nodes_by_name:
        raise GuardrailInsertionError(f"node {failing_node!r} not found in the workflow")

    # Find the single main edge INTO the failing node.
    inbound: list[tuple[str, int, int]] = []  # (source, output_index, edge_index)
    for source, outputs in (wf.get("connections") or {}).items():
        for out_index, edges in enumerate((outputs or {}).get("main") or []):
            for edge_index, edge in enumerate(edges or []):
                if isinstance(edge, dict) and edge.get("node") == failing_node:
                    inbound.append((source, out_index, edge_index))
    if len(inbound) != 1:
        raise GuardrailInsertionError(
            f"guard insertion requires exactly one main input edge into "
            f"{failing_node!r}; found {len(inbound)}"
        )

    # Resolve a collision-free prefix (a second guard in the same workflow).
    prefix = name_prefix
    attempt = 2
    def _names(p: str) -> list[str]:
        return [
            f"{p} input schema inspection",
            f"{p} input schema valid?",
            f"{p} rejected input",
            f"{p} validated input",
            f"{p} rejected: stop and error",
            f"{p} rejected: alert",
            f"{p} rejected: 422 response",
        ]
    while any(name in nodes_by_name for name in _names(prefix)):
        prefix = f"{name_prefix} ({attempt})"
        attempt += 1
        if attempt > 20:
            raise GuardrailInsertionError("could not find a collision-free name prefix")

    consumer = nodes_by_name[failing_node]
    cx, cy = (consumer.get("position") or [600, 0])[:2]
    fragment = input_schema_guardrail(
        required_paths, name_prefix=prefix, position=(cx - 660, cy)
    )
    destination_node = rejection_destination(
        destination, name_prefix=prefix, position=(cx - 220, cy + 240), alert_url=alert_url
    )

    wf.setdefault("nodes", []).extend(fragment["nodes"])
    wf["nodes"].append(destination_node)
    connections = wf.setdefault("connections", {})
    # Fragment-internal wiring.
    for source, outputs in fragment["connections"].items():
        connections[source] = outputs
    # Rewire: source -> entry (replacing source -> failing edge).
    source, out_index, edge_index = inbound[0]
    connections[source]["main"][out_index][edge_index] = {
        "node": fragment["entry_node"], "type": "main", "index": 0,
    }
    # validated -> failing consumer; rejected -> destination.
    connections[fragment["validated_node"]] = {
        "main": [[{"node": failing_node, "type": "main", "index": 0}]]
    }
    connections[fragment["rejected_node"]] = {
        "main": [[{"node": destination_node["name"], "type": "main", "index": 0}]]
    }

    return {
        "workflow": wf,
        "fragment_node_names": [n["name"] for n in fragment["nodes"]]
        + [destination_node["name"]],
        "destination_node_name": destination_node["name"],
        "entry_node": fragment["entry_node"],
        "validated_node": fragment["validated_node"],
        "rejected_node": fragment["rejected_node"],
    }


# --- drift detection: is an APPLIED guard still doing its job? -------------
#
# The apply-time guards (`assert_safe_guardrail_diff`, the stale fingerprint check)
# only run at the moment an operator clicks something. Between clicks — which is
# ~100% of elapsed time — nobody is watching, so a guard deleted or rewired in the
# n8n editor keeps reading as "applied". This is the continuous check.
#
# Deliberately NOT an inversion of `assert_safe_guardrail_diff`: that function
# compares node SETS and node identity and never looks at `connections`, so the
# likeliest real drift — the guard nodes are all still present but someone rewired
# the source straight to the consumer — passes it cleanly. Wiring is what matters
# here, so this walks the edges.


def _main_edges(connections: dict, source: str) -> list:
    """Every main-output edge leaving ``source`` (flattened across output indexes)."""
    outputs = (connections or {}).get(source) or {}
    out = []
    for edges in (outputs.get("main") or []):
        for edge in (edges or []):
            if isinstance(edge, dict):
                out.append(edge)
    return out


def _reaches(connections: dict, source: str, target: str) -> bool:
    return any(edge.get("node") == target for edge in _main_edges(connections, source))


def assert_guard_still_wired(
    live_workflow: dict, guard_config: dict
) -> list[dict[str, Any]]:
    """Report how an applied input-schema guard has drifted in the live workflow.

    Returns a list of ``{"kind": ..., "detail": ...}``; an EMPTY list means the guard
    is intact. Pure function over two JSON documents — no I/O, no n8n calls — so it is
    safe to run on every poll.

    Kinds, in escalating order of "the guard is not protecting anything":
      ``guard_deleted``        one or more fragment nodes are gone
      ``guard_detached``       validated path no longer reaches the guarded consumer
      ``rejection_path_broken``rejected path no longer reaches the destination
      ``guard_bypassed``       something OTHER than the validated node feeds the
                               consumer directly — input can now skip the guard
                               entirely. This is the one that matters most, and the
                               one a node-set comparison cannot see.
    """
    drifts: list[dict[str, Any]] = []
    nodes = {
        n.get("name")
        for n in (live_workflow.get("nodes") or [])
        if isinstance(n, dict)
    }
    connections = live_workflow.get("connections") or {}

    fragment = [str(n) for n in (guard_config.get("fragment_node_names") or [])]
    consumer = guard_config.get("failing_node")
    validated = guard_config.get("validated_node")
    rejected = guard_config.get("rejected_node")
    destination = guard_config.get("destination_node_name")

    missing = [name for name in fragment if name not in nodes]
    if missing:
        drifts.append(
            {
                "kind": "guard_deleted",
                "detail": f"guard nodes removed from the workflow: {', '.join(sorted(missing))}",
            }
        )

    # A detached/broken path is only meaningful while the node still exists; a deleted
    # node is already reported above and would otherwise produce duplicate noise.
    if validated in nodes and consumer and not _reaches(connections, validated, consumer):
        drifts.append(
            {
                "kind": "guard_detached",
                "detail": f"{validated!r} no longer routes validated input to {consumer!r}",
            }
        )
    if rejected in nodes and destination and not _reaches(connections, rejected, destination):
        drifts.append(
            {
                "kind": "rejection_path_broken",
                "detail": f"{rejected!r} no longer routes rejected input to {destination!r}",
            }
        )

    # The bypass check: exactly the inverse of the single-inbound-edge requirement
    # `insert_guard_into_workflow` enforces when it splices the guard in.
    if consumer:
        bypassers = sorted(
            {
                source
                for source in connections
                if source != validated and _reaches(connections, source, consumer)
            }
        )
        if bypassers:
            drifts.append(
                {
                    "kind": "guard_bypassed",
                    "detail": (
                        f"{consumer!r} can be reached without passing the guard — "
                        f"direct input from: {', '.join(bypassers)}"
                    ),
                }
            )
    return drifts
