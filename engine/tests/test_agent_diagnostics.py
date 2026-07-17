"""Regression contract derived from real n8n Claude Messages protocol captures.

The shapes below are reduced, secret-free copies of dogfood executions: Claude
``tool_use`` output, n8n Code-node ``tool_result``, and the direct source links and
``executionIndex`` values n8n retained. They deliberately contain no model content,
tool arguments, credential values, or invented provider traces.
"""

from pisama_n8n_engine.detect.base import TurnSnapshot
from pisama_n8n_engine.detect.runtime import N8NAgentDiagnosticsDetector


def _turn(number, name, **metadata):
    return TurnSnapshot(number, "node", name, "real n8n capture contract", turn_metadata=metadata)


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
        tool_results=[{"type": "tool_result", "tool_use_id": tool_id, "is_error": True}],
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
    result = N8NAgentDiagnosticsDetector().detect([_tool_use(), _failed_result(tool_id="other")])
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
