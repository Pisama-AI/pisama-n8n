"""Decode n8n's "flatted" execution-data wire format into a plain execution dict.

n8n stores the ``execution_data.data`` column as the serialization of the `flatted`
npm package (github.com/WebReflection/flatted): a JSON ARRAY where entry 0 is the
root, every object/array/string is its own entry, and string values inside
containers are stringified indices referencing other entries. Users who dump
executions from n8n's DB or logs get this shape — real production failure data the
plain ``data.resultData.runData`` parser cannot read (``json.loads`` yields a list;
``.get()`` dies). A GitHub sweep of wild execution exports found 6 of 8 genuine
production failures locked in this format or in hand-dereferenced variants of it.

``decode`` is the full reviver; ``normalize_execution`` detects the shapes raw
payloads actually arrive in and returns a plain execution dict the existing parser
consumes unchanged:

1. Plain API export (``data.resultData.runData``) — returned as-is, same object.
2. Flatted array (the raw DB column, or a DB row whose ``data`` is the still-
   stringified column) — decoded and wrapped as ``{"data": <decoded>}``.
3. Partially-dereferenced dumps — a bare data-column dict (``{version, startData,
   resultData, executionData}``), possibly carrying ``<<LOOP: n>>`` markers where a
   hand-resolver gave up. Wrapped and sanitized so unresolved refs degrade to
   missing data instead of a crash.

Zero-dependency, pure Python, like the rest of the engine.
"""
from __future__ import annotations

import json
from typing import Any, Dict, FrozenSet, List, Optional

_LOOP_MARKER = "<<LOOP: {index}>>"


def decode(entries: List[Any]) -> Any:
    """Revive a flatted array into the object it serializes. Raises ValueError if the
    list is not flatted (a string value that is not an in-range index reference).

    Shared references resolve to the same Python object. A genuine cycle (an entry
    referencing its own ancestor) is broken with a ``<<LOOP: n>>`` marker string —
    the same convention wild hand-dereferenced dumps use — so the result is always
    JSON-serializable and safe for the parser downstream.
    """
    if not isinstance(entries, list) or not entries:
        raise ValueError("not a flatted array: expected a non-empty JSON list")

    memo: Dict[int, Any] = {}

    def deref(value: Any, stack: FrozenSet[int]) -> Any:
        if not isinstance(value, str):
            return value
        try:
            index = int(value)
        except ValueError:
            raise ValueError(
                f"not a flatted array: string value {value[:40]!r} is not an index reference"
            ) from None
        if not 0 <= index < len(entries):
            raise ValueError(f"not a flatted array: reference {index} out of range")
        return resolve(index, stack)

    def resolve(index: int, stack: FrozenSet[int]) -> Any:
        if index in stack:
            return _LOOP_MARKER.format(index=index)
        if index in memo:
            return memo[index]
        entry = entries[index]
        if isinstance(entry, dict):
            stack = stack | {index}
            out_dict = {k: deref(v, stack) for k, v in entry.items()}
            memo[index] = out_dict
            return out_dict
        if isinstance(entry, list):
            stack = stack | {index}
            out_list = [deref(v, stack) for v in entry]
            memo[index] = out_list
            return out_list
        # A string entry is a leaf string VALUE (flatted stores every string as its
        # own entry, so it is never itself a reference). Numbers/bools/null likewise.
        memo[index] = entry
        return entry

    try:
        return resolve(0, frozenset())
    except RecursionError:
        raise ValueError("not a decodable flatted array: nesting too deep") from None


def normalize_execution(payload: Any) -> Optional[Dict[str, Any]]:
    """Return a plain execution dict for any of the three wild payload shapes, the
    same object untouched for an already-plain dict, or None for the undecodable.
    Sibling row fields (executionId/workflowId/status/startedAt/...) are preserved.
    """
    if isinstance(payload, list):
        try:
            root = decode(payload)
        except ValueError:
            return None
        # Guard against a non-flatted list that happens to decode (e.g. a dump that
        # is a JSON array of plain executions): a real data column carries resultData.
        if not isinstance(root, dict) or "resultData" not in root:
            return None
        return {"data": _sanitize_data_column(root)}

    if not isinstance(payload, dict):
        return None

    normalized = payload
    data = payload.get("data")
    if isinstance(data, str):
        # A DB row export with the data column still stringified.
        decoded_data = _decode_data_column_string(data)
        if decoded_data is not None:
            normalized = {**payload, "data": decoded_data}
    elif isinstance(data, list):
        # Same row shape, but the exporter already parsed the column to a list.
        try:
            root = decode(data)
        except ValueError:
            root = None
        if isinstance(root, dict) and "resultData" in root:
            normalized = {**payload, "data": _sanitize_data_column(root)}
    elif data is None and "resultData" in payload:
        # A bare (possibly hand-dereferenced) data-column dict.
        normalized = {"data": _sanitize_data_column(payload)}

    workflow_data = normalized.get("workflowData")
    if isinstance(workflow_data, str):
        # DB row dumps also stringify the workflow JSON.
        try:
            parsed = json.loads(workflow_data)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            if normalized is payload:
                normalized = dict(payload)
            normalized["workflowData"] = parsed

    return normalized


def _decode_data_column_string(data: str) -> Optional[Dict[str, Any]]:
    try:
        parsed = json.loads(data)
    except (ValueError, TypeError):
        return None
    if isinstance(parsed, list):
        try:
            root = decode(parsed)
        except ValueError:
            return None
        if isinstance(root, dict) and "resultData" in root:
            return _sanitize_data_column(root)
        return None
    if isinstance(parsed, dict) and "resultData" in parsed:
        return _sanitize_data_column(parsed)
    return None


def _sanitize_data_column(data_column: Dict[str, Any]) -> Dict[str, Any]:
    """Make a decoded / hand-dereferenced data column safe for the parser: an
    unresolved ref leaves resultData, runData, a node's run list, or a single run as
    a marker STRING where a dict/list belongs — decode what's possible, drop only
    the unresolvable parts (a wild dump was seen with a real top-level
    resultData.error but runData behind an unresolvable ref)."""
    result_data = data_column.get("resultData")
    if not isinstance(result_data, dict):
        result_data = {}
    run_data = result_data.get("runData")
    if not isinstance(run_data, dict):
        run_data = {}
    clean_run_data = {
        node: [run for run in runs if isinstance(run, dict)]
        for node, runs in run_data.items()
        if isinstance(runs, list)
    }
    return {**data_column, "resultData": {**result_data, "runData": clean_run_data}}
