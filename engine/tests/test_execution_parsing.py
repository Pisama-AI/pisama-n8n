"""execution_to_turns_and_metadata: the parse contract the runtime lane stands on.

Locks in the fidelity fixes: the swallowed continue-on-fail error surface (gated on the
node's own ``onError`` config) and the honest workflow-status fallback for executions the
n8n public API returns with ``status: null``.
"""
from __future__ import annotations

from pisama_n8n_engine.trace.execution import execution_to_turns_and_metadata

from conftest import execution_doc, make_node


def _run(status="success", error=None, output=None, time_ms=5, **extra):
    # Real n8n runData items are {"json": {...}} wrappers.
    run = {
        "executionTime": time_ms,
        "executionStatus": status,
        "source": [{"previousNode": "Prev"}],
        "data": {"main": [output if output is not None else [{"json": {"ok": True}}]]},
    }
    if error is not None:
        run["error"] = error
    run.update(extra)
    return run


def test_turn_shape_and_metadata_contract():
    raw = execution_doc(
        {"Fetch": [_run(time_ms=120)], "Transform": [_run(time_ms=30)]},
        workflowId="wf-9",
        mode="webhook",
        status="success",
    )
    turns, metadata = execution_to_turns_and_metadata(raw)
    assert [t.participant_id for t in turns] == ["Fetch", "Transform"]
    assert all(t.participant_type == "node" for t in turns)
    assert [t.turn_metadata["execution_time_ms"] for t in turns] == [120, 30]
    assert metadata == {
        "workflow_id": "wf-9",
        "workflow_duration_ms": 150,
        "workflow_mode": "webhook",
        "workflow_status": "success",
    }


def test_empty_run_data_yields_no_turns():
    turns, metadata = execution_to_turns_and_metadata(execution_doc({}))
    assert turns == []
    assert metadata["workflow_duration_ms"] == 0


def test_explicit_run_error_marks_turn():
    raw = execution_doc({"Boom": [_run(status="error", error={"message": "exploded"})]})
    turns, _ = execution_to_turns_and_metadata(raw)
    (turn,) = turns
    assert turn.turn_metadata["has_error"] is True
    assert "ERROR: exploded" in turn.content


class TestSwallowedContinueOnFail:
    """continue-on-fail leaves executionStatus=success and no run.error; the failure is
    only visible in the item payload. Surfacing it is gated on the node's OWN onError
    config so a healthy node whose data merely contains an "error" field stays clean."""

    def _doc(self, on_error=None, output=None):
        node = make_node("Careful", "n8n-nodes-base.httpRequest")
        if on_error:
            node["onError"] = on_error
        return execution_doc(
            {"Careful": [_run(output=output)]},
            nodes=[node],
        )

    def test_continue_regular_output_surfaces_item_error(self):
        # The errored item flows through the regular output with a truthy STRING
        # `error` in its json.
        raw = self._doc(
            on_error="continueRegularOutput",
            output=[{"json": {"error": "upstream 500"}}],
        )
        turns, _ = execution_to_turns_and_metadata(raw)
        (turn,) = turns
        assert turn.turn_metadata["has_error"] is True
        assert "swallowed" in turn.content

    def test_continue_regular_output_surfaces_structured_error_object(self):
        # n8n also records the swallowed failure as an error OBJECT with a message
        # ({message, name, description, ...}) — the shape found on real wild
        # production executions (olavofranzin corpus).
        raw = self._doc(
            on_error="continueRegularOutput",
            output=[{"json": {"error": {"message": "The service was not able to "
                                                   "process your request",
                              "name": "NodeApiError"}}}],
        )
        turns, _ = execution_to_turns_and_metadata(raw)
        (turn,) = turns
        assert turn.turn_metadata["has_error"] is True

    def test_legacy_continue_on_fail_bool_maps_to_regular_output(self):
        # Legacy top-level `continueOnFail: true` (no onError field) behaves like
        # continueRegularOutput. Regression for a REAL community workflow whose
        # Code node crashed, was continued, and n8n marked the run successful —
        # invisible until this mapping (eval corpus rw_d7be75a953).
        node = make_node("Careful", "n8n-nodes-base.code")
        node["continueOnFail"] = True
        raw = execution_doc(
            {"Careful": [_run(output=[{"json": {"error": "Cannot read properties "
                                                          "of undefined"}}])]},
            nodes=[node],
        )
        turns, _ = execution_to_turns_and_metadata(raw)
        (turn,) = turns
        assert turn.turn_metadata["continue_on_fail"] is True
        assert turn.turn_metadata["has_error"] is True

    def test_continue_error_output_surfaces_error_branch(self):
        # continueErrorOutput routes failed items to the SECOND main branch; a
        # non-empty error branch means the node failed.
        raw = self._doc(on_error="continueErrorOutput")
        run = raw["data"]["resultData"]["runData"]["Careful"][0]
        run["data"]["main"] = [[], [{"json": {"error": "timed out"}}]]
        turns, _ = execution_to_turns_and_metadata(raw)
        (turn,) = turns
        assert turn.turn_metadata["has_error"] is True

    def test_without_on_error_config_an_error_shaped_field_stays_clean(self):
        # The FP guard: same payload, but the node never opted into continue-on-fail,
        # so a data field named "error" is just data.
        raw = self._doc(on_error=None, output=[{"json": {"error": "upstream 500"}}])
        turns, _ = execution_to_turns_and_metadata(raw)
        (turn,) = turns
        assert turn.turn_metadata["has_error"] is False


class TestWorkflowStatusFallback:
    def test_explicit_status_wins(self):
        _, meta = execution_to_turns_and_metadata(execution_doc({}, status="crashed"))
        assert meta["workflow_status"] == "crashed"

    def test_null_status_with_top_level_error_is_error(self):
        raw = execution_doc({}, status=None)
        raw["data"]["resultData"]["error"] = {"message": "workflow died"}
        _, meta = execution_to_turns_and_metadata(raw)
        assert meta["workflow_status"] == "error"

    def test_null_status_unfinished_is_error(self):
        _, meta = execution_to_turns_and_metadata(
            execution_doc({}, status=None, finished=False)
        )
        assert meta["workflow_status"] == "error"

    def test_null_status_finished_clean_is_success(self):
        _, meta = execution_to_turns_and_metadata(
            execution_doc({}, status=None, finished=True)
        )
        assert meta["workflow_status"] == "success"


class TestDegenerateRunShapes:
    """Real n8n emits these on errored/edge runs; ingest must parse, not crash.

    Regression for a verified crash: ``data.main = []`` raised IndexError and
    ``data = null`` / ``main = null`` raised TypeError, killing the whole
    execution's ingest (silent skip in the poller, 500 on the webhook path).
    """

    def _doc(self, run_patch):
        run = _run()
        run.update(run_patch)
        return execution_doc({"Edge": [run]})

    def test_main_empty_list_parses(self):
        turns, _ = execution_to_turns_and_metadata(self._doc({"data": {"main": []}}))
        (turn,) = turns
        assert turn.participant_id == "Edge"
        assert "Node: Edge" in turn.content

    def test_data_null_parses(self):
        turns, _ = execution_to_turns_and_metadata(self._doc({"data": None}))
        assert len(turns) == 1

    def test_main_null_parses(self):
        turns, _ = execution_to_turns_and_metadata(self._doc({"data": {"main": None}}))
        assert len(turns) == 1

    def test_main_null_branch_placeholder_parses(self):
        turns, _ = execution_to_turns_and_metadata(self._doc({"data": {"main": [None]}}))
        (turn,) = turns
        assert turn.turn_metadata["has_error"] is False

    def test_degenerate_shape_with_error_still_marks_error(self):
        turns, _ = execution_to_turns_and_metadata(
            self._doc({"data": None, "error": {"message": "died"}, "executionStatus": "error"})
        )
        (turn,) = turns
        assert turn.turn_metadata["has_error"] is True
        assert "ERROR: died" in turn.content
