# VENDORED from the pisama monorepo by scripts/extract_from_monorepo.py — do not edit here.
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime

from pisama_n8n_engine.trace.base_provider import BaseProviderParser

logger = logging.getLogger(__name__)


@dataclass
class N8nNode:
    name: str
    type: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    execution_time_ms: int = 0
    output: Any = None
    error: Optional[str] = None


@dataclass
class N8nExecution:
    id: str
    workflow_id: str
    workflow_name: str
    mode: str
    started_at: datetime
    finished_at: Optional[datetime]
    status: str
    nodes: List[N8nNode] = field(default_factory=list)


@dataclass
class ParsedN8nState:
    trace_id: str
    sequence_num: int
    agent_id: str
    state_delta: dict
    state_hash: str
    node_type: str
    latency_ms: int
    timestamp: datetime
    is_ai_node: bool = False
    ai_model: Optional[str] = None
    token_count: int = 0
    # Span hierarchy — mirroring the otel.py and langgraph_parser.py pattern.
    # build_universal_trace reads these via getattr to construct HANDOFF chains.
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None


class N8nParser(BaseProviderParser):
    # Substring patterns for identifying AI-relevant nodes during ingestion.
    # Uses `in` matching (not exact lookup) — includes partial type names.
    # For exact-match sets, see pisama_n8n_engine.detect.n8n_constants.
    AI_NODE_TYPES = [
        "n8n-nodes-base.openAi",
        "n8n-nodes-base.anthropic",
        "n8n-nodes-langchain.agent",
        "n8n-nodes-langchain.chainLlm",
        "@n8n/n8n-nodes-langchain.lmChatOpenAi",
        "@n8n/n8n-nodes-langchain.lmChatAnthropic",
        "@n8n/n8n-nodes-langchain.lmChatGoogleGemini",
        "n8n-nodes-base.httpRequest",
    ]

    def parse_raw(self, raw_data: Dict[str, Any]) -> N8nExecution:
        return self.parse_execution(raw_data)

    def extract_states(self, execution: N8nExecution, tenant_id: str, ingestion_mode: str = "full") -> List[ParsedN8nState]:
        return self.parse_to_states(execution, tenant_id, ingestion_mode=ingestion_mode)

    def parse_execution(self, raw_data: Dict[str, Any]) -> N8nExecution:
        started_at = self._parse_datetime(raw_data.get("startedAt"))
        finished_at = self._parse_datetime(raw_data.get("finishedAt"))

        # The execution runData carries runtime output but NOT the static node
        # type / parameters — those live in the workflow definition. When the
        # webhook includes `workflow`, index its nodes by name so we can recover
        # the real node type (the run's `source[0].type` is the *connection*
        # type, not the node type) and the node parameters (where an agent's
        # system message / persona lives). Without this, agent nodes are never
        # identified as AI nodes and their persona is invisible.
        wf_nodes = (raw_data.get("workflow") or {}).get("nodes") or []
        node_defs = {
            n.get("name"): n
            for n in wf_nodes
            if isinstance(n, dict) and n.get("name")
        }

        nodes = []
        run_data = raw_data.get("data", {}).get("resultData", {}).get("runData", {})

        for node_name, node_runs in run_data.items():
            if not node_runs:
                continue

            # Community node sends dict instead of list — normalize
            if isinstance(node_runs, dict):
                node_runs = [node_runs]

            ndef = node_defs.get(node_name, {})
            for run in node_runs:
                if not isinstance(run, dict):
                    continue
                node = N8nNode(
                    name=node_name,
                    type=ndef.get("type")
                    or (run.get("source", [{}])[0].get("type", "unknown") if run.get("source") else "unknown"),
                    parameters=ndef.get("parameters") or run.get("parameters", {}),
                    execution_time_ms=run.get("executionTime", 0),
                    output=run.get("data", {}).get("main", [[]])[0] if run.get("data") else None,
                    error=run.get("error", {}).get("message") if run.get("error") else None,
                )
                nodes.append(node)

        return N8nExecution(
            id=raw_data.get("executionId", raw_data.get("id", "")),
            workflow_id=raw_data.get("workflowId", ""),
            workflow_name=raw_data.get("workflowName", ""),
            mode=raw_data.get("mode", "manual"),
            started_at=started_at,
            finished_at=finished_at,
            status=raw_data.get("status", "unknown"),
            nodes=nodes,
        )

    def parse_to_states(self, execution: N8nExecution, tenant_id: str, ingestion_mode: str = "full") -> List[ParsedN8nState]:
        states = []

        for seq, node in enumerate(execution.nodes):
            # Extract model config before redaction
            model_config = self._extract_model_config(node.parameters)

            # Extract thinking/reasoning from custom Claude node output
            reasoning = self._extract_reasoning(node.output)

            is_ai = self._is_ai_node(node)

            # Promote semantic fields for AI/agent nodes under canonical keys so
            # the orchestrator's content detectors (persona_drift, coordination)
            # and build_universal_trace can read them. Without these every n8n
            # span looks identical and only the structural detectors fire.
            response_text = self._extract_response_text(node.output) if is_ai else None
            persona = self._extract_persona(node.parameters) if is_ai else None
            finish_reason = self._extract_finish_reason(node.output) if is_ai else None

            # Mark Execute Workflow nodes as HANDOFF so build_universal_trace
            # emits SpanType.HANDOFF and the delegation-boundary detectors fire.
            # Child sub-workflow executions arrive as separate webhook payloads;
            # the span_id here gives them an anchor for future correlation.
            is_handoff = (
                "executeWorkflow" in node.type or "ExecuteWorkflow" in node.name
            )

            raw_delta = {
                "node_name": node.name,
                "node_type": node.type,
                "parameters": node.parameters,
                "output": node.output,
                "error": node.error,
                "model_config": model_config,
                "reasoning": reasoning,
                "agent_name": node.name,
            }
            if is_handoff:
                child_wf_id = node.parameters.get("workflowId", "")
                if isinstance(child_wf_id, dict):
                    child_wf_id = child_wf_id.get("value", "")
                raw_delta["span_kind"] = "handoff"
                if child_wf_id:
                    raw_delta["child_workflow_id"] = str(child_wf_id)
            if response_text:
                raw_delta["response"] = response_text
            if persona:
                raw_delta["gen_ai.persona"] = persona
                raw_delta["prompt"] = persona
            if finish_reason:
                # Runtime truncation signal: the provider's stop/finish reason.
                # Carried onto the span so build_n8n_metadata can surface it to
                # the n8n_truncation detector (silent max-token cutoffs).
                raw_delta["finish_reason"] = finish_reason
            elif is_ai:
                # Shape-miss telemetry: an AI node whose output carries NO
                # stop/finish key anywhere. The truncation detector is
                # structurally blind on this span, so mark it (surfaced as
                # ai_node_shape_misses by build_n8n_metadata) and log the
                # output SHAPE -- top-level key names only, never values.
                raw_delta["finish_reason_missing"] = True
                logger.info(
                    "n8n_truncation_shape_miss node=%s node_type=%s output_keys=%s",
                    node.name,
                    node.type,
                    self._output_shape_keys(node.output),
                )

            state_delta = self._redact_and_filter(
                raw_delta,
                skip_keys=[],
                content_keys=["parameters", "output", "reasoning", "response", "prompt", "gen_ai.persona"],
                ingestion_mode=ingestion_mode,
            )

            ai_model = None
            token_count = 0

            if is_ai:
                ai_model = node.parameters.get("model", node.parameters.get("modelId"))
                token_count = self._extract_token_count(node)

            states.append(ParsedN8nState(
                trace_id=execution.id,
                sequence_num=seq,
                agent_id=node.name,
                state_delta=state_delta,
                state_hash=self._compute_hash(state_delta),
                node_type=node.type,
                latency_ms=node.execution_time_ms,
                timestamp=execution.started_at,
                is_ai_node=is_ai,
                ai_model=ai_model,
                token_count=token_count,
                span_id=f"{execution.id}-node-{seq}",
            ))

        return states

    def _is_ai_node(self, node: N8nNode) -> bool:
        if any(ai_type in node.type for ai_type in self.AI_NODE_TYPES):
            return True

        if "openai" in node.name.lower() or "anthropic" in node.name.lower():
            return True
        if "llm" in node.name.lower() or "gpt" in node.name.lower():
            return True
        if "langchain" in node.type.lower():
            return True

        return False

    def _extract_token_count(self, node: N8nNode) -> int:
        if isinstance(node.output, list) and node.output:
            first_output = node.output[0] if node.output else {}
            if isinstance(first_output, dict):
                usage = first_output.get("usage", {})
                return usage.get("total_tokens", 0)
        return 0

    def _extract_model_config(self, parameters: dict) -> dict:
        """Extract model configuration from node parameters."""
        config = {}

        # Common LLM config fields
        if "temperature" in parameters:
            config["temperature"] = parameters["temperature"]
        if "maxTokens" in parameters:
            config["max_tokens"] = parameters["maxTokens"]
        if "topP" in parameters:
            config["top_p"] = parameters["topP"]
        if "topK" in parameters:
            config["top_k"] = parameters["topK"]
        if "frequencyPenalty" in parameters:
            config["frequency_penalty"] = parameters["frequencyPenalty"]
        if "presencePenalty" in parameters:
            config["presence_penalty"] = parameters["presencePenalty"]
        if "stop" in parameters:
            config["stop_sequences"] = parameters["stop"]

        # Extended thinking flag (if present)
        if "extendedThinking" in parameters or "extended_thinking" in parameters:
            config["extended_thinking"] = parameters.get("extendedThinking", parameters.get("extended_thinking"))

        return config

    def _extract_reasoning(self, output: list) -> Optional[str]:
        """Extract thinking/reasoning from node output (custom Claude node)."""
        if not isinstance(output, list) or not output:
            return None

        for item in output:
            if isinstance(item, dict) and "json" in item:
                json_data = item["json"]
                # Check for thinking field from custom Claude node
                if isinstance(json_data, dict) and "thinking" in json_data:
                    thinking = json_data["thinking"]
                    if thinking:
                        return thinking

        return None

    def _extract_response_text(self, output: Any) -> Optional[str]:
        """Pull an agent's response text from an n8n node's main output.

        langchain ``agent`` nodes emit their answer at ``output[0].json.output``;
        some nodes use ``json.text`` / ``json.answer``. Falls back to a bound
        chat-model node's ``response.generations[..].text`` shape.
        """
        if not isinstance(output, list) or not output:
            return None
        for item in output:
            if not isinstance(item, dict):
                continue
            j = item.get("json")
            if not isinstance(j, dict):
                continue
            for key in ("output", "text", "answer"):
                val = j.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
            resp = j.get("response")
            if isinstance(resp, str) and resp.strip():
                return resp.strip()
            if isinstance(resp, dict):
                gens = resp.get("generations")
                if (
                    isinstance(gens, list) and gens
                    and isinstance(gens[0], list) and gens[0]
                    and isinstance(gens[0][0], dict)
                ):
                    txt = gens[0][0].get("text")
                    if isinstance(txt, str) and txt.strip():
                        return txt.strip()
        return None

    def _extract_finish_reason(self, output: Any) -> Optional[str]:
        """Pull the provider stop/finish reason from an AI node's main output.

        The key name (``finish_reason`` / ``stop_reason`` / ``finishReason``) is
        stable across providers even though n8n / LangChain nest it differently
        (agent vs bound chat-model vs chainLlm), so a tolerant recursive search
        is used. See ``pisama_n8n_engine.detect.truncation``.
        """
        from pisama_n8n_engine.detect.truncation import extract_stop_reason

        return extract_stop_reason(output)

    @staticmethod
    def _output_shape_keys(output: Any) -> List[str]:
        """Top-level key NAMES of an AI node's output -- never values.

        Privacy: the shape-miss log must describe the shape we failed to read,
        not the content, so only key names of the output dict (or of the dict
        items in an n8n ``main`` output list) are returned.
        """
        if isinstance(output, dict):
            items = [output]
        elif isinstance(output, list):
            items = [item for item in output if isinstance(item, dict)]
        else:
            return []
        keys = {k for item in items for k in item.keys() if isinstance(k, str)}
        return sorted(keys)

    # Mirrors the orchestrator's persona-prompt prefixes — text whose first
    # line begins with one of these reads like a role spec, not a user task.
    _PERSONA_PREFIXES = (
        "you are ", "you're ", "as a ", "act as", "your role", "you act as",
    )

    def _extract_persona(self, parameters: dict) -> Optional[str]:
        """Extract an agent persona / system message from node parameters.

        langchain agent nodes carry the system prompt in ``options.systemMessage``
        or in ``text`` (promptType 'define'). An explicit system message is taken
        as-is; a ``text`` value is only treated as a persona when its first line
        reads like a role spec ("You are a ...").
        """
        if not isinstance(parameters, dict):
            return None
        opts = parameters.get("options")
        sm = (opts.get("systemMessage") if isinstance(opts, dict) else None) or parameters.get("systemMessage")
        if isinstance(sm, str) and sm.strip():
            return sm.strip().split("\n", 1)[0][:200]
        txt = parameters.get("text")
        if isinstance(txt, str):
            first_line = txt.split("\n", 1)[0].strip()
            if first_line and any(first_line.lower().startswith(p) for p in self._PERSONA_PREFIXES):
                return first_line[:200]
        return None

    def extract_sub_workflow_links(
        self, execution: N8nExecution
    ) -> List[Dict[str, str]]:
        """Extract sub-workflow invocations from Execute Workflow nodes.

        Returns list of dicts with:
            parent_execution_id: this execution's ID
            child_workflow_id: the invoked workflow's ID
            node_name: which node triggered the invocation
        """
        links = []
        for node in execution.nodes:
            # n8n Execute Workflow node type
            if "executeWorkflow" in node.type or "ExecuteWorkflow" in node.name:
                child_wf_id = node.parameters.get("workflowId", "")
                if not child_wf_id:
                    # Try nested value format
                    wf_val = node.parameters.get("workflowId", {})
                    if isinstance(wf_val, dict):
                        child_wf_id = wf_val.get("value", "")
                if child_wf_id:
                    links.append({
                        "parent_execution_id": execution.id,
                        "child_workflow_id": str(child_wf_id),
                        "node_name": node.name,
                    })
        return links


n8n_parser = N8nParser()
