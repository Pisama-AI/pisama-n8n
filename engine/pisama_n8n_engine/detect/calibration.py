# VENDORED from the pisama monorepo by scripts/extract_from_monorepo.py — do not edit here.
"""Apply per-detector confidence calibration at inference time.

Detectors emit a raw heuristic confidence in [0, 1] that varies per
detector. This module wraps that raw value with a monotonic calibration
fit on the labeled eval set, so the calibrated confidence is
interpretable as empirical P(true_positive).

Coefficients are loaded once from `data/confidence_calibration.json`,
which is fit by `benchmarks/in_app_traces/scripts/calibrate_confidence.py`.
Fall back to the identity mapping (raw == calibrated) when no
calibration is present for the detector.

Usage:

    from pisama_n8n_engine.detect.calibration import calibrate
    detected, raw_conf = runner(entry)
    calibrated_conf = calibrate("derailment", raw_conf)
    # calibrated_conf now means "empirical P(TP)" for raw_conf seen on
    # the labeled eval set.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default location relative to backend/.
_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "confidence_calibration.json"


@lru_cache(maxsize=1)
def _load_calibration(path_str: Optional[str] = None) -> Dict[str, Any]:
    """Load calibration JSON. Cached so the file is parsed once per process.

    Returns the inner "detectors" dict mapping detector_name to coeffs.
    Returns an empty dict if the file is missing or malformed.
    """
    path = Path(path_str) if path_str else _DEFAULT_PATH
    if not path.exists():
        return {}
    try:
        content = path.read_text()
        if content.startswith("version https://git-lfs"):
            # Shipped LFS pointer stub instead of the real file: fail loud (ERROR)
            # so the silent calibration-disable becomes an actionable deploy bug.
            logger.error(
                "confidence_calibration.json at %s is an unresolved Git LFS pointer "
                "(run `git lfs pull`); per-detector calibration disabled. Deploy bug.",
                path,
            )
            return {}
        data = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load confidence_calibration: %s", exc)
        return {}
    return data.get("detectors") or {}


def _apply_isotonic(raw: float, x_breaks: List[float], y_breaks: List[float]) -> float:
    """Apply a piecewise-monotonic mapping (isotonic-regression style).

    np.interp would be a one-liner but we avoid the import to keep this
    module dependency-light (it ships in the inference hot path).

    Given monotonic-increasing x_breaks and corresponding y_breaks, find
    the bracketing pair for `raw` and linearly interpolate. Clip at the
    endpoints when raw is outside the observed range.
    """
    if not x_breaks or not y_breaks or len(x_breaks) != len(y_breaks):
        return raw
    n = len(x_breaks)
    if raw <= x_breaks[0]:
        return y_breaks[0]
    if raw >= x_breaks[-1]:
        return y_breaks[-1]
    # Linear search — break-point lists are short (typically <20).
    for i in range(n - 1):
        xa, xb = x_breaks[i], x_breaks[i + 1]
        if xa <= raw <= xb:
            ya, yb = y_breaks[i], y_breaks[i + 1]
            if xb == xa:
                return yb
            t = (raw - xa) / (xb - xa)
            return ya + t * (yb - ya)
    return raw


def calibrate(
    detector_name: str,
    raw_conf: float,
    *,
    calibration_path: Optional[str] = None,
) -> float:
    """Return calibrated confidence for `detector_name`.

    Falls back to `raw_conf` unchanged if the detector has no
    calibration entry. Output is clamped to [0, 1].

    Args:
      detector_name: DetectionType value (e.g., "derailment").
      raw_conf: Raw heuristic confidence from the detector runner.
      calibration_path: Override path for testing.
    """
    if raw_conf <= 0.0:
        return 0.0
    detectors = _load_calibration(calibration_path)
    coeffs = detectors.get(detector_name)
    if not coeffs:
        return float(raw_conf)
    x_breaks = coeffs.get("x_thresholds") or []
    y_breaks = coeffs.get("y_thresholds") or []
    calibrated = _apply_isotonic(float(raw_conf), x_breaks, y_breaks)
    if calibrated < 0.0:
        return 0.0
    if calibrated > 1.0:
        return 1.0
    return calibrated


def calibration_status(detector_name: str) -> Dict[str, Any]:
    """Return calibration metadata for `detector_name` (or empty)."""
    return dict(_load_calibration().get(detector_name) or {})


def reset_cache() -> None:
    """Drop the cached calibration. Useful for tests that mutate the file."""
    _load_calibration.cache_clear()
