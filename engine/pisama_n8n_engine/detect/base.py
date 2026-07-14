# VENDORED from the pisama monorepo by scripts/extract_from_monorepo.py — do not edit here.
"""
Turn-Aware Detection Base Classes
=================================

Core classes for turn-aware detection:
- TurnAwareSeverity: Severity levels
- TurnSnapshot: Single turn data
- TurnAwareDetectionResult: Detection output
- TurnAwareDetector: Abstract base class
"""

import hashlib
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# Maximum turns before triggering summarization
MAX_TURNS_BEFORE_SUMMARIZATION = 50
MAX_TOKENS_BEFORE_SUMMARIZATION = 8000

# --- Episode-keyed loop suppression (PISAMA_EPISODE_KEY) --------------------
# Long dogfood sessions span many unrelated tasks. The loop detectors count
# repeated actions across the whole session, so identical actions from
# *different* tasks chain into one false "loop". An episode key (stamped on
# events/spans by ``framework_metadata``) lets a detector require that a run
# stay within a single task episode before it counts.
#
# The flag is read at detect time so it can be flipped without redeploying,
# and the whole mechanism degrades to current behavior when the ``episode``
# key is absent (e.g. the calibration harness, which bypasses
# ``framework_metadata`` and feeds detectors raw golden ``input_data``):
# ``None == None`` is True, so an unstamped run is always "same episode".
EPISODE_MODE_OFF = "off"
EPISODE_MODE_SHADOW = "shadow"
EPISODE_MODE_ON = "on"


def episode_mode() -> str:
    """Return the episode-keying mode: ``off`` | ``shadow`` | ``on``.

    - ``off`` (default): detectors ignore the episode key — current behavior.
    - ``shadow``: detectors compute both the unkeyed and episode-keyed result,
      return the unkeyed (current) result, and log would-be-suppressed fires.
    - ``on``: detectors return the episode-keyed (suppressed) result.
    """
    val = os.environ.get("PISAMA_EPISODE_KEY", EPISODE_MODE_OFF).strip().lower()
    if val in (EPISODE_MODE_SHADOW, EPISODE_MODE_ON):
        return val
    return EPISODE_MODE_OFF

# Module version
MODULE_VERSION = "1.1"  # Updated for semantic enhancements

# Embedding configuration
EMBEDDING_SIMILARITY_THRESHOLD = 0.7  # Below this = significant drift


class TurnAwareSeverity(str, Enum):
    """Severity levels for turn-aware detections."""
    NONE = "none"
    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"


@dataclass
class TurnSnapshot:
    """Snapshot of a single turn in a conversation.

    Similar to StateSnapshot but designed for conversation analysis,
    capturing the context flow between participants.
    """
    turn_number: int
    participant_type: str  # user, agent, system, tool
    participant_id: str
    content: str
    content_hash: Optional[str] = None
    accumulated_context: Optional[str] = None
    accumulated_tokens: int = 0
    turn_metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.content_hash is None:
            self.content_hash = hashlib.sha256(
                self.content.encode()
            ).hexdigest()[:16]


@dataclass
class TurnAwareDetectionResult:
    """Result from a turn-aware detector.

    Confidence contract:
        - When ``detected=True``: ``confidence`` MUST be P(failure) ∈ [0,1].
          Higher = more certain the detector found a real failure. The
          calibration sweep at
          ``backend/app/detection_enterprise/calibrate.py:505`` uses this
          value to find the optimal threshold:
          ``predicted_positive = detected and confidence >= threshold``.
        - When ``detected=False``: ``confidence`` is detector-specific and
          NOT consumed by calibration. Some detectors return 0.0 (clean
          signal), others return 1.0 - drift_score (their internal score).
          Either is fine; do not rely on a uniform meaning across
          detectors here. If you need to compare confidence across
          detectors on negatives, normalize at the call site.
    """
    detected: bool
    severity: TurnAwareSeverity
    confidence: float
    failure_mode: Optional[str]  # F1-F14 mapping
    explanation: str
    affected_turns: List[int] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    suggested_fix: Optional[str] = None
    detector_name: str = ""
    detector_version: str = MODULE_VERSION


class TurnAwareDetector(ABC):
    """Abstract base class for turn-aware detectors.

    Turn-aware detectors analyze entire conversation traces,
    looking for patterns that emerge across multiple turns.
    """

    name: str = "TurnAwareDetector"
    version: str = MODULE_VERSION
    supported_failure_modes: List[str] = []

    @abstractmethod
    def detect(
        self,
        turns: List[TurnSnapshot],
        conversation_metadata: Optional[Dict[str, Any]] = None,
    ) -> TurnAwareDetectionResult:
        """Analyze conversation turns for failures.

        Args:
            turns: List of conversation turns in order
            conversation_metadata: Optional metadata about the conversation

        Returns:
            Detection result with findings
        """
        pass

    def get_config(self) -> Dict[str, Any]:
        """Return detector configuration for versioning."""
        return {
            "name": self.name,
            "version": self.version,
            "supported_failure_modes": self.supported_failure_modes,
        }
