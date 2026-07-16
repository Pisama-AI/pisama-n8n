#!/usr/bin/env python3
"""Report aggregate evidence currently retained by a Pisama dogfood lane.

The report deliberately reads only health, operations summary, and detection metadata.
It never downloads execution traces, workflow JSON, node output, or credentials.  A
present fingerprint means Pisama retained at least one real n8n execution that fired
that detector.  It does not establish recall, repair efficacy, or customer value.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_SERVER_URL = "http://127.0.0.1:8401"


@dataclass(frozen=True)
class EvidenceTarget:
    """One detector outcome that needs a captured n8n execution before rollout."""

    priority: str
    family: str
    detector: str
    failure_mode: str

    @property
    def fingerprint(self) -> str:
        return f"{self.detector}:{self.failure_mode}"


# This catalog mirrors the runtime detector entry points. It is a coverage ledger,
# not a claim that every target is already ready for external use.
EVIDENCE_CATALOG: Tuple[EvidenceTarget, ...] = (
    EvidenceTarget("P0", "Silent LLM truncation", "truncation", "n8n_truncation"),
    EvidenceTarget("P1", "Runtime data-contract drift", "schema", "n8n_data_contract"),
    EvidenceTarget("P1", "Rate-limit classification", "error", "n8n_rate_limit"),
    EvidenceTarget("P1", "Credential classification", "error", "n8n_credential"),
    EvidenceTarget("P1", "Provider classification", "error", "n8n_provider"),
    EvidenceTarget("P1", "Expression classification", "error", "n8n_expression"),
    EvidenceTarget("P1", "Timeout classification", "error", "n8n_timeout"),
    EvidenceTarget("P1", "Retry recovery", "retry_recovery", "n8n_retry_exhausted"),
    EvidenceTarget(
        "P1", "Retry configuration gap", "retry_recovery", "n8n_retry_not_observed"
    ),
    EvidenceTarget(
        "P2", "Missing error workflow", "error_workflow", "n8n_missing_error_workflow"
    ),
    EvidenceTarget(
        "P2",
        "Duplicate side-effect risk",
        "idempotency",
        "n8n_duplicate_side_effect_risk",
    ),
    EvidenceTarget("P2", "Runtime payload growth", "resource", "F6"),
    EvidenceTarget("P2", "Oversized resource pressure", "resource", "F3"),
    # The current n8n orchestrator runs cycle analysis against workflow structure.
    # This target must not be read as evidence for a runtime loop detector.
    EvidenceTarget("P3", "Workflow cycle configuration (static)", "cycle", "F11"),
    EvidenceTarget(
        "P3", "Agent tool recovery", "agent_diagnostics", "n8n_agent_tool_recovery"
    ),
    EvidenceTarget(
        "P3",
        "Agent output validation",
        "agent_diagnostics",
        "n8n_agent_output_validation",
    ),
)


def parse_fingerprint(value: str) -> Tuple[str, str]:
    """Parse the public ``detector:failure_mode`` CLI form."""
    detector, separator, failure_mode = value.partition(":")
    if not separator or not detector or not failure_mode:
        raise argparse.ArgumentTypeError(
            "fingerprints must use detector:failure_mode, for example error:n8n_rate_limit"
        )
    return detector, failure_mode


def fetch_json(url: str, api_key: Optional[str] = None) -> Any:
    """Fetch one read-only JSON endpoint without putting a key in the URL."""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"{url} returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach {url}: {exc.reason}") from exc


def fingerprint(row: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Return only a fired detector fingerprint, never a trace or execution payload."""
    detector = row.get("detector")
    failure_mode = row.get("failure_mode")
    if not row.get("detected") or not isinstance(detector, str) or not detector:
        return None
    if not isinstance(failure_mode, str) or not failure_mode:
        return detector, "<none>"
    return detector, failure_mode


def provenance_value(row: Dict[str, Any], field: str) -> str:
    """Return a non-empty provenance value without treating absent data as current."""
    value = row.get(field)
    return value if isinstance(value, str) and value else "unknown"


def record_observation(
    aggregate: Dict[Tuple[str, str], Dict[str, Any]], row: Dict[str, Any]
) -> None:
    """Add one metadata-only fired observation to the aggregate report."""
    key = fingerprint(row)
    if key is None:
        return
    observation = aggregate[key]
    observation["count"] += 1
    observation["detector_versions"].add(provenance_value(row, "detector_version"))
    observation["build_revisions"].add(provenance_value(row, "build_revision"))
    received_at = row.get("received_at")
    if not isinstance(received_at, str) or not received_at:
        return
    if observation["first_seen"] is None or received_at < observation["first_seen"]:
        observation["first_seen"] = received_at
    if observation["last_seen"] is None or received_at > observation["last_seen"]:
        observation["last_seen"] = received_at


def observed_fingerprints(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate fired rows by fingerprint while retaining no execution identifiers."""
    aggregate: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "first_seen": None,
            "last_seen": None,
            "detector_versions": set(),
            "build_revisions": set(),
        }
    )
    for row in rows:
        record_observation(aggregate, row)
    return [
        {
            "fingerprint": f"{detector}:{failure_mode}",
            "detector": detector,
            "failure_mode": failure_mode,
            "count": aggregate[(detector, failure_mode)]["count"],
            "first_seen": aggregate[(detector, failure_mode)]["first_seen"],
            "last_seen": aggregate[(detector, failure_mode)]["last_seen"],
            "detector_versions": sorted(
                aggregate[(detector, failure_mode)]["detector_versions"]
            ),
            "build_revisions": sorted(
                aggregate[(detector, failure_mode)]["build_revisions"]
            ),
        }
        for detector, failure_mode in sorted(aggregate)
    ]


def catalog_status(observed: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Join the source-controlled coverage catalog with current aggregate evidence."""
    counts = {entry["fingerprint"]: entry["count"] for entry in observed}
    return [
        {
            **asdict(target),
            "fingerprint": target.fingerprint,
            "status": "present" if counts.get(target.fingerprint, 0) else "missing",
            "observation_count": counts.get(target.fingerprint, 0),
        }
        for target in EVIDENCE_CATALOG
    ]


def build_report(server_url: str, api_key: Optional[str]) -> Dict[str, Any]:
    """Build a privacy-preserving, current-state report from a running lane."""
    base_url = server_url.rstrip("/")
    health = fetch_json(f"{base_url}/healthz")
    summary = fetch_json(f"{base_url}/api/v1/operations/summary", api_key)
    detections = fetch_json(f"{base_url}/api/v1/detections", api_key)
    if not isinstance(detections, list):
        raise RuntimeError("The detections endpoint did not return a JSON list.")
    rows = [row for row in detections if isinstance(row, dict)]
    observed = observed_fingerprints(rows)
    catalog = catalog_status(observed)
    known = {target.fingerprint for target in EVIDENCE_CATALOG}
    uncatalogued = [entry for entry in observed if entry["fingerprint"] not in known]
    return {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "server_url": base_url,
        "health": health,
        "operations": {
            key: summary.get(key)
            for key in (
                "executions_analyzed",
                "detections_fired",
                "fired_by_detector",
                "last_ingested_at",
                "repairs_by_status",
                "feedback_by_verdict",
            )
        }
        if isinstance(summary, dict)
        else {"unexpected_response": type(summary).__name__},
        "fired_fingerprints": observed,
        "catalog": catalog,
        "uncatalogued_fired_fingerprints": uncatalogued,
    }


def required_fingerprints(
    required: Sequence[Tuple[str, str]], profile: Optional[str]
) -> List[str]:
    """Combine explicit requirements with one source-controlled priority profile."""
    selected = {f"{detector}:{failure_mode}" for detector, failure_mode in required}
    if profile:
        priorities = {"P0", "P1"} if profile == "core" else {"P0", "P1", "P2", "P3"}
        selected.update(
            target.fingerprint
            for target in EVIDENCE_CATALOG
            if target.priority in priorities
        )
    return sorted(selected)


def apply_gate(report: Dict[str, Any], required: Sequence[str]) -> bool:
    """Attach an explicit, reproducible pass/fail result to the aggregate report."""
    present = {entry["fingerprint"] for entry in report["fired_fingerprints"]}
    missing = [entry for entry in required if entry not in present]
    report["gate"] = {
        "required_fingerprints": list(required),
        "missing_fingerprints": missing,
        "passed": not missing,
    }
    return not missing


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server-url",
        default=os.environ.get("PISAMA_DOGFOOD_SERVER_URL", DEFAULT_SERVER_URL),
        help="Pisama dogfood server URL (default: %(default)s or PISAMA_DOGFOOD_SERVER_URL)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("PISAMA_DOGFOOD_API_KEY"),
        help="Read API key (prefer PISAMA_DOGFOOD_API_KEY over a shell argument)",
    )
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        type=parse_fingerprint,
        metavar="DETECTOR:FAILURE_MODE",
        help="Require a fingerprint; repeat for multiple release gates.",
    )
    parser.add_argument(
        "--require-profile",
        choices=("core", "full"),
        help="Gate on P0/P1 (core) or the entire source-controlled catalog (full).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the aggregate-only JSON report to this path as well as stdout.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if not args.api_key:
        print(
            "PISAMA_DOGFOOD_API_KEY or --api-key is required for the read-only API.",
            file=sys.stderr,
        )
        return 2
    try:
        report = build_report(args.server_url, args.api_key)
    except RuntimeError as exc:
        print(f"Dogfood corpus audit failed: {exc}", file=sys.stderr)
        return 2
    required = required_fingerprints(args.require, args.require_profile)
    passed = apply_gate(report, required)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
