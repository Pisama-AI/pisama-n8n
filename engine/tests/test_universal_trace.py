"""Contract tests for the standalone universal trace types.

These exercise the real in-memory representation used by the truncation detector.
No external framework types or test doubles are involved.
"""

from datetime import datetime, timedelta

from pisama_n8n_engine.trace.universal_trace import (
    SpanStatus,
    SpanType,
    UniversalSpan,
    UniversalTrace,
    is_conversational_single_agent_trace,
    is_linear_single_agent_stream,
    is_single_root_delegation,
)


def _span(
    name: str,
    span_type: SpanType,
    *,
    agent_id: str | None = None,
    agent_name: str | None = None,
    parent_id: str | None = None,
    status: SpanStatus = SpanStatus.OK,
    **values,
) -> UniversalSpan:
    return UniversalSpan(
        id=f"span-{name}",
        trace_id="trace-1",
        name=name,
        span_type=span_type,
        agent_id=agent_id,
        agent_name=agent_name,
        parent_id=parent_id,
        status=status,
        **values,
    )


def test_span_derives_duration_tokens_and_error_state():
    started = datetime(2026, 7, 17, 14, 42, 33)
    span = _span(
        "Observed missing field",
        SpanType.LLM_CALL,
        start_time=started,
        end_time=started + timedelta(milliseconds=1250),
        tokens_input=11,
        tokens_output=7,
        status=SpanStatus.ERROR,
    )

    assert span.duration_ms == 1250
    assert span.tokens_total == 18
    assert span.is_single_agent is True
    assert span.is_multi_agent is False
    assert span.has_error is True
    assert span.to_dict()["status"] == "error"


def test_agent_and_handoff_spans_are_multi_agent():
    assert _span("agent", SpanType.AGENT).is_multi_agent is True
    assert _span("handoff", SpanType.HANDOFF).is_multi_agent is True
    assert _span("unknown", SpanType.UNKNOWN).is_single_agent is False


def test_content_hash_is_stable_for_equivalent_recorded_content():
    first = _span(
        "first",
        SpanType.TOOL_CALL,
        input_data={"path": "/api/v1/detections"},
        output_data={"status": 200},
        tool_name="http",
        tool_args={"method": "GET"},
    )
    second = _span(
        "second",
        SpanType.TOOL_CALL,
        input_data={"path": "/api/v1/detections"},
        output_data={"status": 200},
        tool_name="http",
        tool_args={"method": "GET"},
    )

    assert first.content_hash == second.content_hash
    assert len(first.content_hash) == 16


def test_state_snapshot_preserves_all_available_evidence():
    span = _span(
        "API call",
        SpanType.TOOL_CALL,
        agent_name="operator",
        prompt="Inspect the failure",
        response="The input field is missing",
        tool_name="http",
        tool_args={"method": "GET"},
        tool_result={"status": 200},
        input_data={"detection_id": 1},
        output_data={"failure_mode": "n8n_data_contract"},
    )

    snapshot = span.to_state_snapshot()

    assert snapshot.agent_id == "operator"
    assert snapshot.state_delta == {"failure_mode": "n8n_data_contract"}
    assert "Prompt: Inspect the failure" in snapshot.content
    assert "Tool: http" in snapshot.content
    assert "Result:" in snapshot.content


def test_state_snapshot_has_dependency_free_fallbacks():
    span = _span(
        "raw",
        SpanType.UNKNOWN,
        raw_data={"source": "n8n"},
    )

    snapshot = span.to_state_snapshot()

    assert snapshot.agent_id == "default_agent"
    assert snapshot.state_delta == {}
    assert snapshot.content == "{'source': 'n8n'}"


def test_trace_summary_queries_serialization_and_snapshots():
    started = datetime(2026, 7, 17, 14, 42, 33)
    root = _span(
        "root",
        SpanType.LLM_CALL,
        agent_id="root",
        start_time=started,
        end_time=started + timedelta(milliseconds=100),
        tokens_input=3,
        tokens_output=2,
    )
    child = _span(
        "child",
        SpanType.TOOL_CALL,
        agent_id="root",
        parent_id=root.id,
        start_time=started + timedelta(milliseconds=25),
        end_time=started + timedelta(milliseconds=250),
        error="upstream failed",
    )
    trace = UniversalTrace(trace_id="trace-1", spans=[root], source_format="n8n")
    trace.add_span(child)

    assert trace.start_time == started
    assert trace.end_time == started + timedelta(milliseconds=250)
    assert trace.total_duration_ms == 250
    assert trace.total_tokens == 5
    assert trace.has_errors is True
    assert trace.error_count == 1
    assert trace.get_root_spans() == [root]
    assert trace.get_span_by_id(child.id) is child
    assert trace.get_span_by_id("missing") is None
    assert trace.get_children(root.id) == [child]
    assert trace.get_tool_calls() == [child]
    assert trace.get_llm_calls() == [root]
    assert trace.get_errors() == [child]
    assert [state.sequence_num for state in trace.to_state_snapshots()] == [0, 1]
    assert trace.to_dict()["spans"][1]["error"] == "upstream failed"


def test_empty_trace_remains_empty():
    trace = UniversalTrace(trace_id="empty")
    trace._calculate_summary()

    assert trace.get_root_spans() == []
    assert trace.to_dict()["start_time"] is None


def test_single_root_delegation_distinguishes_nested_workers_from_peers():
    nested = [
        _span("root", SpanType.AGENT, agent_id="root"),
        _span("worker", SpanType.AGENT, agent_id="root.worker"),
        _span("reviewer", SpanType.AGENT, agent_id="root.worker.reviewer"),
    ]
    peers = [
        _span("research", SpanType.AGENT, agent_id="research"),
        _span("review", SpanType.AGENT, agent_id="review"),
    ]

    assert is_single_root_delegation([]) is True
    assert is_single_root_delegation(nested) is True
    assert is_single_root_delegation(peers) is False


def test_conversational_trace_requires_user_and_assistant_turns():
    user = _span("user", SpanType.AGENT, agent_id="user")
    assistant = _span("assistant", SpanType.LLM_CALL, agent_id="assistant")

    assert is_conversational_single_agent_trace(UniversalTrace("empty")) is False
    assert (
        is_conversational_single_agent_trace(
            UniversalTrace("chat", spans=[user, assistant])
        )
        is True
    )


def test_claude_code_without_subagent_is_conversational():
    tool = _span("read", SpanType.TOOL_CALL, agent_id="assistant")
    trace = UniversalTrace(
        "claude",
        spans=[tool],
        source_format="claude_code",
    )

    assert is_conversational_single_agent_trace(trace) is True


def test_peer_agents_and_external_handoff_are_not_single_agent_chat():
    user = _span("user", SpanType.AGENT, agent_id="user")
    first = _span("research", SpanType.LLM_CALL, agent_name="research")
    second = _span("review", SpanType.LLM_CALL, agent_name="review")
    peer_trace = UniversalTrace("peers", spans=[user, first, second])
    assert is_conversational_single_agent_trace(peer_trace) is False

    assistant = _span("assistant", SpanType.LLM_CALL, agent_name="assistant")
    handoff = _span("handoff", SpanType.HANDOFF, agent_name="worker")
    handoff_trace = UniversalTrace("handoff", spans=[user, assistant, handoff])
    assert is_conversational_single_agent_trace(handoff_trace) is False


def test_linear_stream_source_format_is_normalized():
    assert is_linear_single_agent_stream(UniversalTrace("one", source_format=" OpenClaw ")) is True
    assert is_linear_single_agent_stream(UniversalTrace("two", source_format="n8n")) is False
