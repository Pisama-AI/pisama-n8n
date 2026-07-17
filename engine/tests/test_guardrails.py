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
