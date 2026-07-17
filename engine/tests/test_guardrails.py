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
