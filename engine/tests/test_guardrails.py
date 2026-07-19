"""Tests for n8n-native reusable guardrail templates."""

from __future__ import annotations

import pytest

from pisama_n8n_engine.guardrails import input_schema_guardrail


def test_input_schema_guardrail_is_a_portable_n8n_subgraph():
    fragment = input_schema_guardrail(["body.required.value"], position=(120, 40))

    assert fragment["entry_node"] == "Pisama input schema inspection"
    assert fragment["validated_node"] == "Pisama validated input"
    assert fragment["rejected_node"] == "Pisama rejected input"
    nodes = {node["name"]: node for node in fragment["nodes"]}
    assert len({node["id"] for node in fragment["nodes"]}) == 4
    assert nodes[fragment["entry_node"]]["type"] == "n8n-nodes-base.code"
    assert nodes["Pisama input schema valid?"]["type"] == "n8n-nodes-base.if"
    assert nodes["Pisama input schema valid?"]["typeVersion"] == 2.2
    assert nodes[fragment["entry_node"]]["position"] == [120, 40]
    code = nodes[fragment["entry_node"]]["parameters"]["jsCode"]
    assert 'const requiredPaths = ["body.required.value"];' in code
    assert "_pisama_input_schema" in code
    route = fragment["connections"]["Pisama input schema valid?"]["main"]
    assert route[0][0]["node"] == fragment["validated_node"]
    assert route[1][0]["node"] == fragment["rejected_node"]


@pytest.mark.parametrize("paths", [[], [""], ["required..value"], ["required."]])
def test_input_schema_guardrail_rejects_ambiguous_path_configuration(paths):
    with pytest.raises(ValueError, match="required_paths"):
        input_schema_guardrail(paths)


# ── first-class repair layer: extraction, destinations, insertion ────────────

from pisama_n8n_engine.guardrails import (  # noqa: E402
    GuardrailDestinationError,
    GuardrailInsertionError,
    assert_guard_still_wired,
    insert_guard_into_workflow,
    observed_required_paths,
    property_read_leaf,
    rejection_destination,
    validate_destination_compatibility,
)

_CONSUMER_CODE = "return [{ json: { value: $json.required.value } }];"
_ERROR = "Cannot read properties of undefined (reading 'value') [line 1]"


def _workflow():
    return {
        "name": "wf",
        "nodes": [
            {"name": "Webhook", "type": "n8n-nodes-base.webhook", "typeVersion": 2,
             "position": [0, 0],
             "parameters": {"path": "x", "responseMode": "responseNode"}},
            {"name": "Consumer", "type": "n8n-nodes-base.code", "typeVersion": 2,
             "position": [660, 0],
             "parameters": {"mode": "runOnceForAllItems", "jsCode": _CONSUMER_CODE}},
        ],
        "connections": {
            "Webhook": {"main": [[{"node": "Consumer", "type": "main", "index": 0}]]}
        },
        "settings": {"executionOrder": "v1"},
    }


class TestObservedPaths:
    def test_confirmed_against_recorded_input(self):
        # The consumer read $json.required.value; the observed input lacks `required`.
        out = observed_required_paths(_CONSUMER_CODE, _ERROR, {"body": {"x": 1}})
        assert out == {"confirmed": ["required.value"], "candidates": []}

    def test_unverifiable_input_yields_candidates_only(self):
        out = observed_required_paths(_CONSUMER_CODE, _ERROR, None)
        assert out == {"confirmed": [], "candidates": ["required.value"]}

    def test_no_property_read_error_yields_nothing(self):
        out = observed_required_paths(_CONSUMER_CODE, "consol is not defined", {"a": 1})
        assert out == {"confirmed": [], "candidates": []}

    def test_leaf_not_in_code_yields_nothing(self):
        out = observed_required_paths(
            "return [{json: {a: $json.other.field}}];", _ERROR, {}
        )
        assert out == {"confirmed": [], "candidates": []}

    def test_path_present_in_input_is_not_confirmed(self):
        # Input actually HAS the path -> the guard would not have rejected it, so it
        # cannot be claimed as the confirmed cause.
        out = observed_required_paths(
            _CONSUMER_CODE, _ERROR, {"required": {"value": 7}}
        )
        assert out == {"confirmed": [], "candidates": ["required.value"]}

    def test_leaf_parsing_variants(self):
        assert property_read_leaf(_ERROR) == "value"
        assert property_read_leaf("Cannot read property 'id' of undefined") == "id"
        assert property_read_leaf("something unrelated") is None
        assert property_read_leaf(None) is None


class TestDestinations:
    def test_error_workflow_is_stop_and_error(self):
        node = rejection_destination("error_workflow")
        assert node["type"] == "n8n-nodes-base.stopAndError"

    def test_alert_requires_http_url(self):
        with pytest.raises(GuardrailDestinationError):
            rejection_destination("alert")
        node = rejection_destination("alert", alert_url="https://ops.example/hook")
        assert node["type"] == "n8n-nodes-base.httpRequest"
        # Alert body carries ONLY the rejection record, never payload values.
        assert "_pisama_input_schema" in node["parameters"]["jsonBody"]

    def test_respond_422_requires_response_node_mode(self):
        wf = _workflow()
        validate_destination_compatibility(wf, "respond_422")  # ok as configured
        wf["nodes"][0]["parameters"]["responseMode"] = "onReceived"
        with pytest.raises(GuardrailDestinationError):
            validate_destination_compatibility(wf, "respond_422")

    def test_unknown_kind_rejected(self):
        with pytest.raises(GuardrailDestinationError):
            rejection_destination("carrier_pigeon")


class TestInsertion:
    def test_inserts_guard_upstream_of_consumer(self):
        out = insert_guard_into_workflow(
            _workflow(), ["required.value"], "Consumer", "error_workflow"
        )
        wf = out["workflow"]
        names = {n["name"] for n in wf["nodes"]}
        assert "Pisama input schema inspection" in names
        assert "Pisama rejected: stop and error" in names
        # Webhook now feeds the guard entry, not the consumer.
        assert wf["connections"]["Webhook"]["main"][0][0]["node"] == out["entry_node"]
        # Validated branch feeds the original consumer; rejected feeds the destination.
        assert wf["connections"][out["validated_node"]]["main"][0][0]["node"] == "Consumer"
        assert (
            wf["connections"][out["rejected_node"]]["main"][0][0]["node"]
            == out["destination_node_name"]
        )
        # The input workflow is untouched (deep copy).
        assert "Pisama input schema inspection" not in {
            n["name"] for n in _workflow()["nodes"]
        }

    def test_second_guard_gets_a_collision_free_prefix(self):
        first = insert_guard_into_workflow(
            _workflow(), ["required.value"], "Consumer", "error_workflow"
        )
        wf = first["workflow"]
        # Give the guarded workflow a second consumer downstream to guard.
        wf["nodes"].append(
            {"name": "Consumer2", "type": "n8n-nodes-base.code", "typeVersion": 2,
             "position": [900, 0],
             "parameters": {"mode": "runOnceForAllItems", "jsCode": _CONSUMER_CODE}}
        )
        wf["connections"]["Consumer"] = {
            "main": [[{"node": "Consumer2", "type": "main", "index": 0}]]
        }
        second = insert_guard_into_workflow(
            wf, ["required.value"], "Consumer2", "error_workflow"
        )
        assert "Pisama (2) input schema inspection" in {
            n["name"] for n in second["workflow"]["nodes"]
        }

    def test_refuses_unknown_node_and_multi_input(self):
        with pytest.raises(GuardrailInsertionError):
            insert_guard_into_workflow(_workflow(), ["p"], "Ghost", "error_workflow")
        wf = _workflow()
        # Second inbound edge into Consumer -> refuse rather than guess.
        wf["nodes"].append(
            {"name": "Other", "type": "n8n-nodes-base.noOp", "typeVersion": 1,
             "position": [0, 200], "parameters": {}}
        )
        wf["connections"]["Other"] = {
            "main": [[{"node": "Consumer", "type": "main", "index": 0}]]
        }
        with pytest.raises(GuardrailInsertionError):
            insert_guard_into_workflow(wf, ["p"], "Consumer", "error_workflow")


def test_generated_validator_ignores_prototype_chain_members():
    # Regression: a required segment named __proto__ must be treated as MISSING when not
    # an own property, not silently satisfied via the prototype chain.
    fragment = input_schema_guardrail(["body.__proto__"])
    code = fragment["nodes"][0]["parameters"]["jsCode"]
    assert "Object.hasOwn" in code


class TestGuardDriftDetection:
    """An APPLIED guard can be deleted or rewired in the n8n editor at any time. The
    apply-time checks only run when an operator clicks something, so these assertions
    are what stand between "applied" and "actually still protecting the workflow"."""

    def _applied(self):
        """A workflow with the guard spliced in, plus its guard_config."""
        out = insert_guard_into_workflow(
            _workflow(), ["required.value"], "Consumer", "error_workflow"
        )
        guard_config = {
            "failing_node": "Consumer",
            "fragment_node_names": out["fragment_node_names"],
            "destination_node_name": out["destination_node_name"],
            "entry_node": out["entry_node"],
            "validated_node": out["validated_node"],
            "rejected_node": out["rejected_node"],
        }
        return out["workflow"], guard_config

    def test_intact_guard_reports_no_drift(self):
        wf, guard = self._applied()
        assert assert_guard_still_wired(wf, guard) == []

    def test_deleted_fragment_node_is_detected(self):
        wf, guard = self._applied()
        wf["nodes"] = [n for n in wf["nodes"] if n["name"] != guard["entry_node"]]
        kinds = {d["kind"] for d in assert_guard_still_wired(wf, guard)}
        assert "guard_deleted" in kinds

    def test_detached_validated_branch_is_detected(self):
        wf, guard = self._applied()
        # Validated output rewired to nothing (someone repointed it elsewhere).
        wf["connections"][guard["validated_node"]] = {"main": [[]]}
        kinds = {d["kind"] for d in assert_guard_still_wired(wf, guard)}
        assert "guard_detached" in kinds

    def test_broken_rejection_path_is_detected(self):
        wf, guard = self._applied()
        wf["connections"][guard["rejected_node"]] = {"main": [[]]}
        kinds = {d["kind"] for d in assert_guard_still_wired(wf, guard)}
        assert "rejection_path_broken" in kinds

    def test_bypassed_guard_is_detected_though_every_node_survives(self):
        """THE case a node-set diff cannot see: all guard nodes still present and the
        validated branch still wired, but the source now ALSO feeds the consumer
        directly, so malformed input can skip the guard entirely."""
        wf, guard = self._applied()
        wf["connections"]["Webhook"]["main"][0].append(
            {"node": "Consumer", "type": "main", "index": 0}
        )
        # Every fragment node still exists and the validated path is intact...
        names = {n["name"] for n in wf["nodes"]}
        assert all(n in names for n in guard["fragment_node_names"])
        drifts = assert_guard_still_wired(wf, guard)
        kinds = {d["kind"] for d in drifts}
        assert kinds == {"guard_bypassed"}, drifts
        assert "Webhook" in drifts[0]["detail"]

    def test_bypass_check_ignores_the_validated_node_itself(self):
        """The validated node feeding the consumer is the guard working correctly —
        it must never be reported as a bypass."""
        wf, guard = self._applied()
        assert not [
            d for d in assert_guard_still_wired(wf, guard) if d["kind"] == "guard_bypassed"
        ]
