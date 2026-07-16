# VENDORED from the pisama monorepo by scripts/extract_from_monorepo.py — do not edit here.
"""Silent-truncation detection across LLM providers.

When an LLM call hits its output-token budget it returns HTTP 200 with a
provider-specific "stopped early" marker, so n8n (and most harnesses) record
the node as SUCCESS while the answer is cut off mid-sentence. This is a QUALITY
failure the run status never reveals -- the opposite of a loud API error -- and
it is the one Layer-1 signal worth surfacing in the n8n product.

    Anthropic  stop_reason   = "max_tokens"
    OpenAI     finish_reason = "length"
    Gemini     finishReason  = "MAX_TOKENS"

The three markers were captured live on 2026-07-15 (see
tests/detection/test_api_error_taxonomy.py). Because n8n / LangChain wrap the
raw provider response at varying depths (agent vs bound chat-model vs chainLlm
nodes), the reason is located by a bounded recursive search for the known keys
rather than a fixed path -- the key NAMES are stable even when the nesting is
not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

DETECTOR_VERSION = "1.0"

# Stop-reason values that mean "cut off at the token budget" (compared lower-cased).
TRUNCATION_VALUES = {"max_tokens", "length", "max_output_tokens", "model_length"}

# Keys that carry a stop/finish reason across providers (compared lower-cased).
_STOP_KEYS = {"stop_reason", "finish_reason", "finishreason", "stopreason"}

_MAX_DEPTH = 8


def _iter_stop_reasons(obj: Any, _depth: int = 0) -> Iterator[str]:
    """Yield every stop/finish-reason value found anywhere in ``obj``.

    Handles the raw provider shapes (Anthropic ``stop_reason``, OpenAI
    ``choices[].finish_reason``, Gemini ``candidates[].finishReason``) and any
    n8n / LangChain wrapper around them, bounded to avoid pathological nesting.
    """
    if _depth > _MAX_DEPTH or obj is None or isinstance(obj, (str, int, float, bool)):
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in _STOP_KEYS and isinstance(v, str) and v.strip():
                yield v.lower()
        for v in obj.values():
            if isinstance(v, (dict, list)):
                yield from _iter_stop_reasons(v, _depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_stop_reasons(v, _depth + 1)


def extract_stop_reason(obj: Any) -> Optional[str]:
    """First stop/finish reason found in ``obj`` (lower-cased), or None."""
    for r in _iter_stop_reasons(obj):
        return r
    return None


def is_truncated(obj: Any = None, stop_reason: Optional[str] = None) -> bool:
    """True if an explicit reason or anything inside ``obj`` marks truncation."""
    if stop_reason and stop_reason.lower() in TRUNCATION_VALUES:
        return True
    return any(r in TRUNCATION_VALUES for r in _iter_stop_reasons(obj))


@dataclass
class TruncatedCall:
    index: int
    name: str
    stop_reason: str
    provider: Optional[str] = None


@dataclass
class TruncationResult:
    detected: bool
    count: int
    total_llm_calls: int
    truncated: List[TruncatedCall] = field(default_factory=list)
    confidence: float = 0.0
    remediation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detected": self.detected,
            "count": self.count,
            "total_llm_calls": self.total_llm_calls,
            "truncated": [vars(t) for t in self.truncated],
            "confidence": round(self.confidence, 3),
            "remediation": self.remediation,
        }


def _remediation(calls: List[TruncatedCall]) -> str:
    names = ", ".join(dict.fromkeys(c.name for c in calls)) or "the affected call(s)"
    return (
        f"{len(calls)} LLM call(s) hit the output-token limit and returned truncated "
        f"content that the run recorded as success. Raise max_tokens (or continue the "
        f"turn) on: {names}."
    )


def _finalize(truncated: List[TruncatedCall], total: int) -> TruncationResult:
    detected = bool(truncated)
    return TruncationResult(
        detected=detected,
        count=len(truncated),
        total_llm_calls=total,
        truncated=truncated,
        confidence=0.95 if detected else 0.0,   # the marker is explicit, not inferred
        remediation=_remediation(truncated) if detected else "",
    )


class TruncationDetector:
    """Flags LLM calls whose output was silently cut at the token budget."""

    def detect(self, spans: Any) -> TruncationResult:
        """Scan UniversalSpan LLM_CALL spans for a truncation marker.

        Reads the stop reason from wherever an importer left it: ``output_data``,
        ``raw_data``, ``metadata``, or the ``response`` payload.
        """
        from pisama_n8n_engine.trace.universal_trace import SpanType

        truncated: List[TruncatedCall] = []
        total = 0
        for i, span in enumerate(spans or []):
            if getattr(span, "span_type", None) != SpanType.LLM_CALL:
                continue
            total += 1
            haystack = [
                getattr(span, "output_data", None),
                getattr(span, "raw_data", None),
                getattr(span, "metadata", None),
            ]
            reason = next(
                (r for h in haystack for r in _iter_stop_reasons(h) if r in TRUNCATION_VALUES),
                None,
            )
            if reason:
                truncated.append(TruncatedCall(
                    index=i,
                    name=getattr(span, "name", None) or getattr(span, "agent_name", None) or f"llm_call[{i}]",
                    stop_reason=reason,
                    provider=(getattr(span, "model", None) or "").split("-")[0] or None,
                ))
        return _finalize(truncated, total)

    def detect_n8n_execution(self, raw_execution: Dict[str, Any]) -> TruncationResult:
        """Scan a raw n8n execution's ``runData`` for truncated AI-node output.

        Uses the same shape ``N8nExecutionParser`` reads
        (``data.resultData.runData[node][run].data.main[0]``). Non-AI nodes carry
        no stop-reason key, so they self-exclude.
        """
        run_data = (
            (raw_execution or {}).get("data", {}).get("resultData", {}).get("runData", {})
        )
        truncated: List[TruncatedCall] = []
        total = 0
        idx = 0
        for node_name, runs in (run_data or {}).items():
            for run in runs or []:
                output = (run.get("data") or {}).get("main")
                if output is None:
                    continue
                total += 1
                reason = next(
                    (r for r in _iter_stop_reasons(output) if r in TRUNCATION_VALUES), None
                )
                if reason:
                    truncated.append(TruncatedCall(index=idx, name=node_name, stop_reason=reason))
                idx += 1
        return _finalize(truncated, total)
