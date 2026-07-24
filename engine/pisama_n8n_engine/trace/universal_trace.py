"""Universal trace abstraction for Agent Forensics.

This module provides a framework-agnostic trace representation that works across:
- LangSmith/LangChain traces
- OpenTelemetry spans
- LangFuse observations
- n8n workflow logs
- Raw JSON agent logs
- CrewAI task logs
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import hashlib
import json


class SpanType(Enum):
    """Type of span in the trace."""
    AGENT = "agent"           # Agent reasoning/orchestration
    TOOL_CALL = "tool_call"   # Tool/function invocation
    LLM_CALL = "llm_call"     # Raw LLM API call
    HANDOFF = "handoff"       # Agent-to-agent transfer
    CHAIN = "chain"           # LangChain chain execution
    RETRIEVAL = "retrieval"   # RAG retrieval step
    UNKNOWN = "unknown"


class SpanStatus(Enum):
    """Execution status of a span."""
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class StateSnapshot:
    """Dependency-free compatibility shape consumed by state-based detectors."""

    agent_id: str
    state_delta: Dict[str, Any]
    content: str
    sequence_num: int = 0


@dataclass
class UniversalSpan:
    """Framework-agnostic span representation for Agent Forensics.

    This abstraction unifies traces from different sources into a common format
    that can be used by all detection algorithms.
    """
    # Core identifiers
    id: str
    trace_id: str
    name: str

    # Type and status
    span_type: SpanType
    status: SpanStatus = SpanStatus.OK

    # Timing
    start_time: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    end_time: Optional[datetime] = None
    duration_ms: int = 0

    # Hierarchy
    parent_id: Optional[str] = None
    children: List["UniversalSpan"] = field(default_factory=list)

    # Agent context (for multi-agent)
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None

    # Input/Output data
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)

    # LLM-specific fields
    prompt: Optional[str] = None
    response: Optional[str] = None
    model: Optional[str] = None
    tokens_input: int = 0
    tokens_output: int = 0
    tokens_total: int = 0

    # Tool-specific fields
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[Any] = None

    # Error handling
    error: Optional[str] = None
    error_type: Optional[str] = None
    stack_trace: Optional[str] = None

    # Source metadata
    source_format: str = "unknown"  # langsmith, otel, langfuse, n8n, raw
    raw_data: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Calculate derived fields after initialization."""
        if self.end_time and self.start_time:
            delta = (self.end_time - self.start_time).total_seconds()
            self.duration_ms = int(delta * 1000)
        if self.tokens_input or self.tokens_output:
            self.tokens_total = self.tokens_input + self.tokens_output

    @property
    def is_single_agent(self) -> bool:
        """Check if this span is from a single-agent system."""
        return self.span_type in [SpanType.TOOL_CALL, SpanType.LLM_CALL, SpanType.CHAIN]

    @property
    def is_multi_agent(self) -> bool:
        """Check if this span involves multi-agent coordination."""
        return self.span_type in [SpanType.AGENT, SpanType.HANDOFF]

    @property
    def has_error(self) -> bool:
        """Check if this span has an error."""
        return self.status == SpanStatus.ERROR or self.error is not None

    @property
    def content_hash(self) -> str:
        """Generate a hash of the span content for deduplication."""
        content = json.dumps({
            "input": self.input_data,
            "output": self.output_data,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
        }, sort_keys=True, default=str)
        return hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()[:16]  # nosec B324

    def to_state_snapshot(self) -> StateSnapshot:
        """Convert to StateSnapshot format for detection algorithms.

        This provides compatibility with existing detection modules that
        expect the StateSnapshot dataclass.
        """
        # Build content string from available data
        content_parts = []
        if self.prompt:
            content_parts.append(f"Prompt: {self.prompt}")
        if self.response:
            content_parts.append(f"Response: {self.response}")
        if self.tool_name:
            content_parts.append(f"Tool: {self.tool_name}")
        if self.tool_args:
            content_parts.append(f"Args: {json.dumps(self.tool_args)}")
        if self.tool_result:
            content_parts.append(f"Result: {json.dumps(self.tool_result)}")
        if self.input_data:
            content_parts.append(f"Input: {json.dumps(self.input_data)}")
        if self.output_data:
            content_parts.append(f"Output: {json.dumps(self.output_data)}")

        content = "\n".join(content_parts) if content_parts else str(self.raw_data)

        return StateSnapshot(
            agent_id=self.agent_id or self.agent_name or "default_agent",
            state_delta=self.output_data or {},
            content=content,
            sequence_num=0,  # Will be set by caller
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert span to dictionary for serialization."""
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "name": self.name,
            "span_type": self.span_type.value,
            "status": self.status.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "parent_id": self.parent_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "prompt": self.prompt,
            "response": self.response,
            "model": self.model,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "tokens_total": self.tokens_total,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_result": self.tool_result,
            "error": self.error,
            "error_type": self.error_type,
            "source_format": self.source_format,
            "metadata": self.metadata,
        }


@dataclass
class UniversalTrace:
    """A complete trace containing multiple spans."""

    trace_id: str
    spans: List[UniversalSpan] = field(default_factory=list)

    # Trace-level metadata
    source_format: str = "unknown"
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_duration_ms: int = 0
    total_tokens: int = 0

    # Error summary
    has_errors: bool = False
    error_count: int = 0

    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Calculate derived fields from spans."""
        if self.spans:
            self._calculate_summary()

    def _calculate_summary(self):
        """Calculate summary statistics from spans."""
        if not self.spans:
            return

        start_times = [s.start_time for s in self.spans if s.start_time]
        end_times = [s.end_time for s in self.spans if s.end_time]

        if start_times:
            self.start_time = min(start_times)
        if end_times:
            self.end_time = max(end_times)

        if self.start_time and self.end_time:
            delta = (self.end_time - self.start_time).total_seconds()
            self.total_duration_ms = int(delta * 1000)

        self.total_tokens = sum(s.tokens_total for s in self.spans)
        self.error_count = sum(1 for s in self.spans if s.has_error)
        self.has_errors = self.error_count > 0

    def add_span(self, span: UniversalSpan):
        """Add a span to the trace and recalculate summary."""
        self.spans.append(span)
        self._calculate_summary()

    def get_root_spans(self) -> List[UniversalSpan]:
        """Get top-level spans (no parent)."""
        return [s for s in self.spans if s.parent_id is None]

    def get_span_by_id(self, span_id: str) -> Optional[UniversalSpan]:
        """Find a span by its ID."""
        for span in self.spans:
            if span.id == span_id:
                return span
        return None

    def get_children(self, parent_id: str) -> List[UniversalSpan]:
        """Get all child spans of a parent."""
        return [s for s in self.spans if s.parent_id == parent_id]

    def get_tool_calls(self) -> List[UniversalSpan]:
        """Get all tool call spans."""
        return [s for s in self.spans if s.span_type == SpanType.TOOL_CALL]

    def get_llm_calls(self) -> List[UniversalSpan]:
        """Get all LLM call spans."""
        return [s for s in self.spans if s.span_type == SpanType.LLM_CALL]

    def get_errors(self) -> List[UniversalSpan]:
        """Get all spans with errors."""
        return [s for s in self.spans if s.has_error]

    def to_state_snapshots(self) -> List[StateSnapshot]:
        """Convert all spans to StateSnapshot format for detection."""
        snapshots = []
        for i, span in enumerate(self.spans):
            snapshot = span.to_state_snapshot()
            # Update sequence number based on position
            snapshot.sequence_num = i
            snapshots.append(snapshot)
        return snapshots

    def to_dict(self) -> Dict[str, Any]:
        """Convert trace to dictionary for serialization."""
        return {
            "trace_id": self.trace_id,
            "spans": [s.to_dict() for s in self.spans],
            "source_format": self.source_format,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "total_duration_ms": self.total_duration_ms,
            "total_tokens": self.total_tokens,
            "has_errors": self.has_errors,
            "error_count": self.error_count,
            "metadata": self.metadata,
        }


def is_single_root_delegation(spans: "list[UniversalSpan]") -> bool:
    """True when every span's agent forms a single-root delegation hierarchy.

    The ATIF parser scopes a sub-agent's ``agent_id`` as a dotted descendant of
    its parent (``root.child`` — see the atif_parser agent_path scoping), so a
    conversational agent that delegates to worker sub-agents yields agent_ids
    that are all one root agent or ``root.*`` descendants of that single root.
    That is structurally distinct from peer / lateral multi-agent orchestration,
    whose agents have independent, un-nested ids.

    In the single-root-delegation shape the generic structural detectors
    (workflow / loop / tool_provision, which assume DAG or peer topology)
    false-fire exactly as they do on single-agent chat — the reason
    ``claude_code`` is special-cased in :func:`is_conversational_single_agent_trace`.
    Treating this shape as conversational gates those out. The sub-agent-boundary
    detectors (synthesis_failure / silent_cascade / redundant_conflict), gated on
    ``DetectionOrchestrator._has_subagent_hierarchy`` (NOT on this predicate),
    stay eligible.

    KNOWN LIMITATION (verified 2026-07-10): this ALSO gates out the generic
    ``communication`` detector, currently the only detector that fires on a
    genuine "parent misreports / contradicts the sub-agent's result" faithfulness
    failure, and the boundary detectors above do NOT yet backstop it — so that
    class is presently undetected on single-root delegation traces. Keeping the
    communication detector on is worse (loud topology FPs at conf 1.0 on every
    benign delegation session). The fix is a dedicated delegation-aware
    faithfulness detector; tracked in ``docs/plans/omnigent-step3.md``.

    Uses ``agent_id`` (the dotted hierarchy encoding), NOT ``agent_name`` (which
    may be a bare worker name like ``researcher``).
    """
    ids = {(s.agent_id or s.agent_name or "") for s in spans}
    ids.discard("")
    if len(ids) <= 1:
        return True
    for root in ids:
        prefix = root + "."
        if all(a == root or a.startswith(prefix) for a in ids):
            return True
    return False


def is_conversational_single_agent_trace(trace: UniversalTrace) -> bool:
    """True when the trace is a single-agent conversational log (user ↔ assistant + tools).

    Shared topology predicate. Two callers depend on it and MUST agree:

    * ``DetectionOrchestrator._is_conversational_single_agent_trace`` gates the
      workflow / communication / information_withholding detectors, which
      otherwise fire at ~100% on Claude Code-style chat traces because they
      assume DAG or multi-agent structure the trace does not have
      (see data/real_data_detector_review.md).
    * The background metric-series convergence path
      (``app.detection_enterprise.background_detect``) skips the per-step
      resource series (tokens/latency/tool-call counts) on these traces, since
      per-step token size just reflects whether a step read a big file or ran a
      one-line grep — it oscillates and has no reason to converge downward.

    Kept as a free function (not a method) so both callers reuse one definition
    instead of duplicating the logic.
    """
    spans = trace.spans or []
    if not spans:
        return False

    if (trace.source_format or "").lower() == "claude_code":
        # Claude Code defaults to single-agent chat, but the CC ingest emits a
        # span_kind="agent" boundary span (SpanType.AGENT) for each subagent
        # the forwarder reports, and marks sidechain tool spans with
        # is_sidechain in state_delta. Either signal means a genuine
        # multi-agent fan-out — fall through to the topology checks so the
        # delegation/coordination detector family can run.
        has_subagent = any(
            (s.span_type == SpanType.AGENT
             and (s.agent_id or "").lower() not in ("", "user"))
            or (s.metadata or {}).get("is_sidechain") is True
            for s in spans
        )
        if not has_subagent:
            return True

    non_user_spans = [
        s
        for s in spans
        if s.span_type != SpanType.AGENT or (s.agent_id or "").lower() != "user"
    ]
    non_user_agents = {(s.agent_name or s.agent_id or "") for s in non_user_spans}
    non_user_agents.discard("")
    if len(non_user_agents) > 1 and not is_single_root_delegation(non_user_spans):
        # Multiple distinct agents that do NOT form a single-root delegation
        # hierarchy → genuine peer / lateral multi-agent orchestration, where
        # the structural detectors are meant to run.
        return False

    # HANDOFF spans normally signal multi-agent dispatch, but the ATIF parser
    # also emits one for any system step that carries SubagentTrajectoryRefs —
    # including degenerate cases where the "subagent" is the same agent.
    # Disqualify on HANDOFF only when it actually targets a different agent than
    # the one producing the rest of the trace; otherwise it's a structural
    # artifact, not a multi-agent signal.
    handoff_targets = {
        (s.agent_name or s.agent_id or "")
        for s in spans
        if s.span_type == SpanType.HANDOFF
    }
    handoff_targets.discard("")
    if handoff_targets and handoff_targets - non_user_agents:
        # Handoff points to an agent not otherwise present → real dispatch.
        return False

    has_user_turn = any(
        s.span_type == SpanType.AGENT and (s.agent_id or "").lower() == "user"
        for s in spans
    )
    has_assistant_turn = any(s.span_type == SpanType.LLM_CALL for s in spans)
    return has_user_turn and has_assistant_turn


# Channels whose sessions are inherently LINEAR SINGLE-AGENT STREAMS: one
# agent, no DAG and no genuine multi-agent handoff topology. Both the Claude
# Code ingest and the OpenClaw gateway (a single-agent session gateway —
# sessions are append-only linear event logs) produce these. Keyed on the
# CHANNEL (source_format), deliberately NOT on trace shape: OpenClaw sessions
# are single-agent linear streams but not user↔assistant chats, so the
# ``is_conversational_single_agent_trace`` topology heuristic (which requires a
# user turn + an assistant LLM_CALL) returns False on them and would let the
# structural artifacts through.
LINEAR_STREAM_SOURCE_FORMATS = frozenset({"claude_code", "openclaw"})


def is_linear_single_agent_stream(trace: UniversalTrace) -> bool:
    """True when the trace's CHANNEL is an inherently linear single-agent stream.

    Structural-artifact gate predicate. Linearizing such a stream into
    nodes/states manufactures the same shape artifacts on every session,
    regardless of whether the session had a real problem:

    * the workflow node builder always yields the artifact trio (the last span
      has no outgoing edge → dead_end, no node is terminal →
      missing_termination, depth grows past the threshold → excessive_depth),
    * the state-tier loop matcher (MultiLevelLoopDetector) sees a near-constant
      ~20-key state_delta shape and reads distinct productive steps as a loop,
    * the per-step resource series (tokens/latency/tool-call counts) oscillate
      with no reason to converge downward and fire regression/plateau at ~100%.

    All three are gated on these channels (``_detect_workflow`` artifact-only
    drop, ``_detect_loops`` early return, and the background convergence path's
    ``eligible_convergence_series`` filter). Genuine failures still fire through
    channel-agnostic paths that compare VALUES rather than shape — the
    args-keyed "Repeated Tool Calls" loop, the framework's native detectors
    (e.g. ``openclaw_session_loop``), real workflow design issues
    (infinite_loop_risk / unreachable_node / bottleneck / orphan_node /
    missing_error_handling), and convergence on genuine quality metrics.

    Safe with respect to calibration: the golden corpora feed the detectors
    directly through ``detector_adapters`` (raw nodes/states/metric series),
    never constructing a source_format-tagged ``UniversalTrace`` nor passing
    through these orchestrator gates, so F1 is untouched on every channel.
    """
    return (getattr(trace, "source_format", "") or "").strip().lower() in (
        LINEAR_STREAM_SOURCE_FORMATS
    )
