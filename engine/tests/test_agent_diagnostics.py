"""Regression contract derived from real n8n Claude Messages protocol captures.

The shapes below are reduced, secret-free copies of dogfood executions: Claude
``tool_use`` output, n8n Code-node ``tool_result``, and the direct source links and
``executionIndex`` values n8n retained. They deliberately contain no model content,
tool arguments, credential values, or invented provider traces.
"""

from pisama_n8n_engine.detect.base import TurnSnapshot
from pisama_n8n_engine.detect.runtime import N8NAgentDiagnosticsDetector
from pisama_n8n_engine.orchestrator import analyze
from pisama_n8n_engine.trace.execution import execution_to_turns_and_metadata

from conftest import execution_doc, make_node


def _turn(number, name, **metadata):
    return TurnSnapshot(
        number, "node", name, "real n8n capture contract", turn_metadata=metadata
    )


def _tool_use(index=1, tool_id="toolu-real"):
    return _turn(
        index,
        "Claude tool request",
        execution_order_tier=0,
        execution_index=index,
        is_claude_message=True,
        tool_use_ids=[tool_id],
        tool_results=[],
        source_nodes=["Webhook"],
    )


def _failed_result(index=3, tool_id="toolu-real"):
    return _turn(
        index,
        "Recorded failed tool result",
        execution_order_tier=0,
        execution_index=index,
        is_claude_message=False,
        tool_use_ids=[],
        tool_results=[
            {"type": "tool_result", "tool_use_id": tool_id, "is_error": True}
        ],
        source_nodes=["Claude tool request"],
    )


def _real_tool_failure(index=2):
    return _turn(
        index,
        "Real tool HTTP failure",
        execution_order_tier=0,
        execution_index=index,
        is_claude_message=False,
        tool_use_ids=[],
        tool_results=[],
        source_nodes=["Claude tool request"],
    )


def _recovery(index=4):
    return _turn(
        index,
        "Claude recovery response",
        execution_order_tier=0,
        execution_index=index,
        is_claude_message=True,
        tool_use_ids=[],
        tool_results=[],
        source_nodes=["Recorded failed tool result"],
        finish_reason="end_turn",
    )


def test_unhandled_real_tool_failure_is_reported():
    result = N8NAgentDiagnosticsDetector().detect(
        [_tool_use(), _real_tool_failure(), _failed_result()]
    )
    assert result.detected is True
    assert result.failure_mode == "n8n_agent_tool_recovery"
    assert result.evidence["tool_request_execution_index"] == 1
    assert "toolu" not in str(result.evidence)


def test_real_recovery_is_a_negative_control():
    result = N8NAgentDiagnosticsDetector().detect(
        [_tool_use(), _real_tool_failure(), _failed_result(), _recovery()]
    )
    assert result.detected is False


def test_mismatched_tool_id_is_not_attributed():
    result = N8NAgentDiagnosticsDetector().detect(
        [_tool_use(), _failed_result(tool_id="other")]
    )
    assert result.detected is False


def test_missing_recorded_order_is_inconclusive():
    unordered = _tool_use()
    unordered.turn_metadata["execution_order_tier"] = 2
    unordered.turn_metadata["execution_index"] = None
    result = N8NAgentDiagnosticsDetector().detect([unordered, _failed_result()])
    assert result.detected is False


def test_successful_tool_and_unrelated_loop_are_negative_controls():
    successful = _tool_use()
    loop = _turn(
        2,
        "Loop Over Items",
        execution_order_tier=0,
        execution_index=2,
        is_claude_message=False,
        tool_use_ids=[],
        tool_results=[],
        source_nodes=["Claude tool request"],
    )
    result = N8NAgentDiagnosticsDetector().detect([successful, loop])
    assert result.detected is False


def test_real_json_parse_validation_fault_is_reported():
    response = _turn(
        1,
        "Claude prose output",
        execution_order_tier=0,
        execution_index=1,
        is_claude_message=True,
        tool_use_ids=[],
        tool_results=[],
        source_nodes=["Webhook"],
    )
    validator = _turn(
        2,
        "Validate Claude JSON",
        execution_order_tier=0,
        execution_index=2,
        is_claude_message=False,
        tool_use_ids=[],
        tool_results=[],
        source_nodes=["Claude prose output"],
        has_error=True,
        error_message="Unexpected token 'h', is not valid JSON",
        node_type="n8n-nodes-base.code",
        parameters={"jsCode": "return JSON.parse($json.content[0].text);"},
    )
    result = N8NAgentDiagnosticsDetector().detect([response, validator])
    assert result.detected is True
    assert result.failure_mode == "n8n_agent_output_validation"


# These are secret-free reductions of local n8n 1.91.3 executions 90 (healthy tool),
# 91 (tool failure with a later native model recovery), and 92 (tool failure without
# a later model turn). They keep the actual native node types, connection labels,
# execution ordering, ``source: [null]`` child-run shape, and Agent intermediate step.
_NATIVE_AGENT = "@n8n/n8n-nodes-langchain.agent"
_NATIVE_MODEL = "@n8n/n8n-nodes-langchain.lmChatAnthropic"
_NATIVE_TOOL = "@n8n/n8n-nodes-langchain.toolCode"
_NATIVE_OUTPUT_PARSER = "@n8n/n8n-nodes-langchain.outputParserStructured"
_NATIVE_ERROR = "Pisama native controlled tool failure for native-tool-unhandled"
_NATIVE_PARSER_ERROR = "Model output doesn't fit required format"


def _native_run(index, data, status="success", error=None, source=None):
    run = {
        "executionIndex": index,
        "executionStatus": status,
        "data": data,
        "source": [None] if source is None else source,
    }
    if error is not None:
        run["error"] = {"message": error}
    return run


def _native_execution(
    *,
    failed_tool=True,
    model_indexes=(2,),
    action_tool="status_lookup",
    observation=None,
    connections=None,
    extra_runs=None,
):
    """Return a reduced real native-Agent execution shape with no provider content."""
    observation = observation or f'There was an error: "{_NATIVE_ERROR}"'
    run_data = {
        "Native agent webhook": [
            _native_run(0, {"main": [[{"json": {"ok": True}}]]}, source=[])
        ],
        "Native AI Agent": [
            _native_run(
                1,
                {
                    "main": [
                        [
                            {
                                "json": {
                                    "intermediateSteps": [
                                        {
                                            "action": {
                                                "tool": action_tool,
                                                "toolCallId": "redacted-real-tool-call-id",
                                                "toolInput": {"redacted": True},
                                            },
                                            "observation": observation,
                                        }
                                    ],
                                    "output": "redacted",
                                }
                            }
                        ]
                    ]
                },
                source=[{"previousNode": "Native agent webhook"}],
            )
        ],
        "Native Anthropic Chat Model": [
            _native_run(index, {"ai_languageModel": [[{"json": {}}]]})
            for index in model_indexes
        ],
        "status_lookup": [
            _native_run(
                3,
                {"ai_tool": [[{"json": {"query": "redacted"}}]]},
                status="error" if failed_tool else "success",
                error=_NATIVE_ERROR if failed_tool else None,
            )
        ],
    }
    if extra_runs:
        run_data.update(extra_runs)
    nodes = [
        make_node("Native agent webhook", "n8n-nodes-base.webhook"),
        make_node("Native AI Agent", _NATIVE_AGENT),
        make_node("Native Anthropic Chat Model", _NATIVE_MODEL),
        make_node("status_lookup", _NATIVE_TOOL),
    ]
    document = execution_doc(
        run_data,
        nodes=nodes,
        status="success",
        finished=True,
    )
    document["workflowData"]["connections"] = connections or {
        "Native agent webhook": {
            "main": [[{"node": "Native AI Agent", "type": "main", "index": 0}]]
        },
        "Native Anthropic Chat Model": {
            "ai_languageModel": [
                [
                    {
                        "node": "Native AI Agent",
                        "type": "ai_languageModel",
                        "index": 0,
                    }
                ]
            ]
        },
        "status_lookup": {
            "ai_tool": [
                [
                    {
                        "node": "Native AI Agent",
                        "type": "ai_tool",
                        "index": 0,
                    }
                ]
            ]
        },
    }
    return document


def _native_result(document):
    turns, _ = execution_to_turns_and_metadata(document)
    return N8NAgentDiagnosticsDetector().detect(turns), turns


def test_native_agent_unhandled_tool_contract_is_reported():
    result, turns = _native_result(_native_execution())
    assert result.detected is True
    assert result.failure_mode == "n8n_native_agent_tool_recovery"
    assert result.confidence == 0.90
    assert result.evidence == {
        "agent_node": "Native AI Agent",
        "agent_execution_index": 1,
        "tool_node": "status_lookup",
        "tool_execution_index": 3,
        "model_node": "Native Anthropic Chat Model",
        "model_execution_index": 2,
    }
    assert _NATIVE_ERROR not in str(result.evidence)
    assert "toolInput" not in str(result.evidence)
    agent = next(turn for turn in turns if turn.participant_id == "Native AI Agent")
    tool = next(turn for turn in turns if turn.participant_id == "status_lookup")
    model = next(
        turn for turn in turns if turn.participant_id == "Native Anthropic Chat Model"
    )
    assert agent.turn_metadata["native_agent_tool_nodes"] == ["status_lookup"]
    assert agent.turn_metadata["native_agent_model_nodes"] == [
        "Native Anthropic Chat Model"
    ]
    assert tool.turn_metadata["native_ai_tool_target_agents"] == ["Native AI Agent"]
    assert model.turn_metadata["native_ai_model_target_agents"] == ["Native AI Agent"]
    assert tool.turn_metadata["source_nodes"] == []
    assert model.turn_metadata["source_nodes"] == []


def test_native_recovery_and_success_are_negative_controls():
    recovered, _ = _native_result(_native_execution(model_indexes=(2, 4)))
    successful, _ = _native_result(
        _native_execution(failed_tool=False, model_indexes=(2, 4))
    )
    assert recovered.detected is False
    assert successful.detected is False


def test_native_recovered_tool_error_is_not_a_generic_error_incident():
    turns, metadata = execution_to_turns_and_metadata(
        _native_execution(model_indexes=(2, 4))
    )
    report = analyze(turns=turns, metadata=metadata)
    fired = {detection.detector for detection in report.fired}
    assert "error" not in fired
    assert "agent_diagnostics" not in fired

    unhandled_turns, unhandled_metadata = execution_to_turns_and_metadata(
        _native_execution()
    )
    unhandled = analyze(turns=unhandled_turns, metadata=unhandled_metadata)
    assert {detection.detector for detection in unhandled.fired} >= {
        "error",
        "agent_diagnostics",
    }


def test_native_agent_contract_rejects_ambiguous_or_incomplete_telemetry():
    missing_order = _native_execution()
    missing_order["data"]["resultData"]["runData"]["status_lookup"][0].pop(
        "executionIndex"
    )
    mismatched_tool = _native_execution(action_tool="other_tool")
    mismatched_edge = _native_execution(
        connections={
            "Native Anthropic Chat Model": {
                "ai_languageModel": [
                    [
                        {
                            "node": "Native AI Agent",
                            "type": "ai_languageModel",
                            "index": 0,
                        }
                    ]
                ]
            },
            "status_lookup": {
                "main": [[{"node": "Native AI Agent", "type": "main", "index": 0}]]
            },
        }
    )
    missing_error_observation = _native_execution(observation="tool response redacted")
    repeated_tool = _native_execution()
    repeated_tool["data"]["resultData"]["runData"]["status_lookup"].append(
        _native_run(
            5,
            {"ai_tool": [[{"json": {"query": "redacted"}}]]},
            status="error",
            error=_NATIVE_ERROR,
        )
    )
    for document in (
        missing_order,
        mismatched_tool,
        mismatched_edge,
        missing_error_observation,
        repeated_tool,
    ):
        result, _ = _native_result(document)
        assert result.detected is False


def test_native_agent_contract_rejects_unrelated_model_or_agent_loop():
    unrelated_model = _native_execution(
        extra_runs={
            "Unrelated Native Model": [
                _native_run(4, {"ai_languageModel": [[{"json": {}}]]})
            ]
        }
    )
    unrelated_model["workflowData"]["nodes"].append(
        make_node("Unrelated Native Model", _NATIVE_MODEL)
    )
    repeated_agent = _native_execution()
    repeated_agent["data"]["resultData"]["runData"]["Native AI Agent"].append(
        _native_run(
            5,
            {"main": [[{"json": {"intermediateSteps": []}}]]},
            source=[{"previousNode": "Native agent webhook"}],
        )
    )
    for document in (unrelated_model, repeated_agent):
        result, _ = _native_result(document)
        assert result.detected is False


def _native_parser_execution(
    *,
    parser_error=_NATIVE_PARSER_ERROR,
    connections=None,
    extra_runs=None,
):
    """Reduced, secret-free n8n 1.91 structured-parser rejection capture.

    This retains only observed node types, execution ordering, direct AI edges, and
    the exact parser error. It deliberately excludes the model response, schema,
    credential, tool input, and raw parser payload.
    """
    parser_fails = parser_error is not None
    run_data = {
        "Native agent webhook": [
            _native_run(0, {"main": [[{"json": {"ok": True}}]]}, source=[])
        ],
        "Native structured AI Agent": [
            _native_run(
                1,
                {"main": []},
                status="error" if parser_fails else "success",
                error=parser_error,
                source=[{"previousNode": "Native agent webhook"}],
            )
        ],
        "Native Anthropic Chat Model": [
            _native_run(2, {"ai_languageModel": [[{"json": {}}]]})
        ],
        "Native Structured Output Parser": [
            _native_run(
                3,
                {"ai_outputParser": []},
                status="error" if parser_fails else "success",
                error=parser_error,
            )
        ],
    }
    if extra_runs:
        run_data.update(extra_runs)
    nodes = [
        make_node("Native agent webhook", "n8n-nodes-base.webhook"),
        make_node("Native structured AI Agent", _NATIVE_AGENT),
        make_node("Native Anthropic Chat Model", _NATIVE_MODEL),
        make_node("Native Structured Output Parser", _NATIVE_OUTPUT_PARSER),
        make_node("structured_control_tool", _NATIVE_TOOL),
    ]
    document = execution_doc(
        run_data,
        nodes=nodes,
        status="error" if parser_fails else "success",
        finished=not parser_fails,
    )
    document["workflowData"]["connections"] = connections or {
        "Native agent webhook": {
            "main": [
                [{"node": "Native structured AI Agent", "type": "main", "index": 0}]
            ]
        },
        "Native Anthropic Chat Model": {
            "ai_languageModel": [
                [
                    {
                        "node": "Native structured AI Agent",
                        "type": "ai_languageModel",
                        "index": 0,
                    }
                ]
            ]
        },
        "Native Structured Output Parser": {
            "ai_outputParser": [
                [
                    {
                        "node": "Native structured AI Agent",
                        "type": "ai_outputParser",
                        "index": 0,
                    }
                ]
            ]
        },
        "structured_control_tool": {
            "ai_tool": [
                [
                    {
                        "node": "Native structured AI Agent",
                        "type": "ai_tool",
                        "index": 0,
                    }
                ]
            ]
        },
    }
    return document


def test_native_structured_parser_rejection_is_reported():
    result, turns = _native_result(_native_parser_execution())
    assert result.detected is True
    assert result.failure_mode == "n8n_native_structured_parser_rejection"
    assert result.confidence == 0.98
    assert result.evidence == {
        "agent_node": "Native structured AI Agent",
        "agent_execution_index": 1,
        "model_node": "Native Anthropic Chat Model",
        "model_execution_index": 2,
        "parser_node": "Native Structured Output Parser",
        "parser_execution_index": 3,
    }
    assert _NATIVE_PARSER_ERROR not in str(result.evidence)
    agent = next(
        turn for turn in turns if turn.participant_id == "Native structured AI Agent"
    )
    parser = next(
        turn
        for turn in turns
        if turn.participant_id == "Native Structured Output Parser"
    )
    assert agent.turn_metadata["native_agent_output_parser_nodes"] == [
        "Native Structured Output Parser"
    ]
    assert parser.turn_metadata["native_ai_output_parser_target_agents"] == [
        "Native structured AI Agent"
    ]


def test_native_structured_parser_rejection_keeps_the_generic_error():
    turns, metadata = execution_to_turns_and_metadata(_native_parser_execution())
    report = analyze(turns=turns, metadata=metadata)
    assert {detection.detector for detection in report.fired} >= {
        "error",
        "agent_diagnostics",
    }


def test_native_structured_parser_rejects_ambiguous_or_healthy_controls():
    healthy = _native_parser_execution(parser_error=None)
    shared_parser = _native_parser_execution(
        connections={
            "Native Anthropic Chat Model": {
                "ai_languageModel": [
                    [
                        {
                            "node": "Native structured AI Agent",
                            "type": "ai_languageModel",
                            "index": 0,
                        }
                    ]
                ]
            },
            "Native Structured Output Parser": {
                "ai_outputParser": [
                    [
                        {
                            "node": "Native structured AI Agent",
                            "type": "ai_outputParser",
                            "index": 0,
                        },
                        {
                            "node": "Other Native Agent",
                            "type": "ai_outputParser",
                            "index": 1,
                        },
                    ]
                ]
            },
        }
    )
    shared_parser["workflowData"]["nodes"].append(
        make_node("Other Native Agent", _NATIVE_AGENT)
    )
    repeated_parser = _native_parser_execution()
    repeated_parser["data"]["resultData"]["runData"][
        "Native Structured Output Parser"
    ].append(
        _native_run(
            4, {"ai_outputParser": []}, status="error", error=_NATIVE_PARSER_ERROR
        )
    )
    for document in (healthy, shared_parser, repeated_parser):
        result, _ = _native_result(document)
        assert result.detected is False
