"""The flatted DB wire format decodes to the same turns the plain export parses to.

n8n stores execution_data.data as the `flatted` npm serialization; users who dump
executions from the DB (or its logs) get a JSON ARRAY of index-referenced entries, or a
partially-dereferenced variant with ``<<LOOP: n>>`` markers. A wild-execution mining
sweep found most genuine production failures locked in exactly these shapes, so the
parse contract is: flatted in == plain in, markers degrade gracefully, plain untouched.

No mocks: the round-trip fixture is built by re-encoding a real-shaped execution with a
minimal flatted encoder that mirrors the npm package's wire format.
"""
from __future__ import annotations

import json

import pytest

from pisama_n8n_engine.trace.execution import execution_to_turns_and_metadata
from pisama_n8n_engine.trace.flatted import decode, normalize_execution

from conftest import execution_doc, make_node


def flatted_encode(root):
    """Encode like flatted.stringify: every container/string becomes its own entry,
    string values inside containers are stringified indices, strings dedupe by value."""
    entries = []
    seen = {}

    def add(value):
        key = id(value) if isinstance(value, (dict, list)) else ("str", value)
        if key in seen:
            return seen[key]
        index = len(entries)
        entries.append(None)
        seen[key] = index
        if isinstance(value, dict):
            entries[index] = {k: ref(v) for k, v in value.items()}
        elif isinstance(value, list):
            entries[index] = [ref(v) for v in value]
        else:
            entries[index] = value
        return index

    def ref(value):
        if isinstance(value, (dict, list, str)):
            return str(add(value))
        return value

    add(root)
    return entries


def _run(status="success", error=None, output=None, time_ms=5, start_time=1771950000000):
    run = {
        "startTime": start_time,
        "executionTime": time_ms,
        "executionStatus": status,
        "source": [{"previousNode": "Prev"}],
        "data": {"main": [output if output is not None else [{"json": {"ok": True}}]]},
    }
    if error is not None:
        run["error"] = error
    return run


def _data_column(run_data, **result_extra):
    return {
        "version": 1,
        "startData": {},
        "resultData": {"runData": run_data, **result_extra},
        "executionData": {},
    }


# 1. The decoder itself.

class TestDecode:
    def test_refs_resolve_and_strings_dedupe(self):
        # "hello" is stored once and referenced twice; entry 2 is a nested object.
        entries = [{"a": "1", "b": "2", "c": "1"}, "hello", {"d": 3.5, "e": None}]
        assert decode(entries) == {"a": "hello", "b": {"d": 3.5, "e": None}, "c": "hello"}

    def test_numeric_looking_string_value_is_not_re_resolved(self):
        # The VALUE "2" lives at entry 1. Wire strings are refs; entry strings are
        # leaves — even when the leaf itself looks like an index.
        assert decode([{"n": "1"}, "2"]) == {"n": "2"}

    def test_cycle_becomes_loop_marker(self):
        assert decode([{"self": "0"}]) == {"self": "<<LOOP: 0>>"}
        nested = decode([{"child": "1"}, {"parent": "0", "name": "2"}, "leaf"])
        assert nested == {"child": {"parent": "<<LOOP: 0>>", "name": "leaf"}}

    def test_shared_reference_resolves_to_same_object(self):
        out = decode([{"x": "1", "y": "1"}, {"v": 1}])
        assert out["x"] is out["y"]

    @pytest.mark.parametrize(
        "entries",
        [
            [],
            [{"a": "not-an-index"}],
            [{"a": "99"}],
            [{"file": "a.json", "repo": "owner/name"}],  # a metadata list, not flatted
        ],
    )
    def test_non_flatted_list_raises(self, entries):
        with pytest.raises(ValueError):
            decode(entries)


# 2. Format detection / normalization.

class TestNormalizeExecution:
    def test_plain_execution_passes_through_as_the_same_object(self):
        raw = execution_doc({"Fetch": [_run()]})
        assert normalize_execution(raw) is raw

    def test_flatted_array_of_non_execution_is_none(self):
        assert normalize_execution(flatted_encode({"foo": "bar"})) is None

    def test_non_flatted_list_is_none(self):
        assert normalize_execution([{"file": "a.json"}, {"file": "b.json"}]) is None
        assert normalize_execution([1, 2, 3]) is None

    def test_scalar_is_none(self):
        assert normalize_execution("not an execution") is None

    def test_undecodable_payload_raises_in_parser(self):
        with pytest.raises(ValueError):
            execution_to_turns_and_metadata([1, 2, 3])


# 3. The contract: flatted in == plain in.

class TestFlattedRoundTrip:
    def test_flatted_array_parses_to_the_same_turns_as_plain(self):
        run_data = {
            "Fetch": [_run(time_ms=120)],
            "Boom": [_run(status="error", time_ms=30,
                          error={"message": "exploded", "name": "NodeApiError"})],
        }
        plain = execution_doc(run_data)
        wire = flatted_encode(_data_column(run_data))

        plain_turns, plain_meta = execution_to_turns_and_metadata(plain)
        flat_turns, flat_meta = execution_to_turns_and_metadata(wire)

        assert [t.participant_id for t in flat_turns] == ["Fetch", "Boom"]
        for p, f in zip(plain_turns, flat_turns):
            assert f.participant_id == p.participant_id
            assert f.content == p.content
            assert f.turn_metadata == p.turn_metadata
        assert flat_meta["workflow_duration_ms"] == plain_meta["workflow_duration_ms"] == 150
        # The bare DB data column carries no workflowId/mode; those degrade, not crash.
        assert flat_meta["workflow_id"] is None
        assert flat_meta["workflow_status"] == "success"

    def test_db_row_with_stringified_data_column_parses(self):
        # A dumped execution row keeps sibling fields and stores the data column as
        # the still-serialized flatted TEXT; workflowData is stringified JSON too.
        run_data = {"Fetch": [_run(time_ms=42)]}
        node = make_node("Fetch", "n8n-nodes-base.httpRequest")
        row = {
            "id": 62,
            "workflowId": "wf-db-dump",
            "status": "success",
            "startedAt": "2026-02-24T16:30:36.124Z",
            "data": json.dumps(flatted_encode(_data_column(run_data))),
            "workflowData": json.dumps({"nodes": [node], "connections": {}}),
        }
        turns, meta = execution_to_turns_and_metadata(row)
        (turn,) = turns
        assert turn.turn_metadata["execution_time_ms"] == 42
        assert turn.turn_metadata["node_type"] == "n8n-nodes-base.httpRequest"
        assert meta["workflow_id"] == "wf-db-dump"
        assert meta["workflow_status"] == "success"


# 4. Partially-dereferenced dumps (<<LOOP: n>> markers) degrade, never crash.

class TestPartiallyDereferencedDumps:
    def test_run_data_behind_unresolved_ref_degrades_to_no_turns(self):
        # Seen in the wild: a real top-level resultData.error with runData left as an
        # unresolvable ref string. Keep the error verdict, skip the unreadable turns.
        doc = _data_column("<<LOOP: 4>>", error={"message": "workflow died"})
        turns, meta = execution_to_turns_and_metadata(doc)
        assert turns == []
        assert meta["workflow_status"] == "error"

    def test_leaf_loop_markers_inside_runs_are_just_strings(self):
        run = _run(output=[{"json": {"method": "<<LOOP: 48>>", "url": "<<LOOP: 49>>"}}])
        turns, meta = execution_to_turns_and_metadata(_data_column({"Request": [run]}))
        (turn,) = turns
        assert turn.turn_metadata["has_error"] is False
        assert "<<LOOP: 48>>" in turn.content
        assert meta["workflow_status"] == "success"

    def test_marker_strings_inside_run_lists_are_dropped(self):
        doc = _data_column({"Mixed": ["<<LOOP: 7>>", _run(time_ms=9)],
                            "Gone": "<<LOOP: 8>>"})
        turns, _ = execution_to_turns_and_metadata(doc)
        (turn,) = turns
        assert turn.participant_id == "Mixed"
        assert turn.turn_metadata["execution_time_ms"] == 9

    def test_top_level_error_only_dump_reports_error_status(self):
        doc = _data_column({}, error={"message": "Missing value for input variable"})
        turns, meta = execution_to_turns_and_metadata(doc)
        assert turns == []
        assert meta["workflow_status"] == "error"
