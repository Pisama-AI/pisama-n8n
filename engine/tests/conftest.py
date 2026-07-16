"""Shared builders for the engine unit tests.

No mocks: tests feed the engine real n8n workflow/execution JSON — either inline
minimal documents or the captured fixtures committed under ``benchmarks/fixtures/``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# engine/tests/conftest.py -> parents[2] == repo root. The benchmarks corpus is
# committed in the same repo; tests are not shipped in the wheel, so the layout
# coupling is safe. Skip (not fail) if run from an isolated engine checkout.
REPO_ROOT = Path(__file__).resolve().parents[2]
BENCH_FIXTURES = REPO_ROOT / "benchmarks" / "fixtures"


@pytest.fixture(scope="session")
def bench_fixtures() -> Path:
    if not BENCH_FIXTURES.is_dir():
        pytest.skip(f"benchmarks fixtures not found at {BENCH_FIXTURES}")
    return BENCH_FIXTURES


def load_execution(bench_fixtures: Path, name: str) -> Dict[str, Any]:
    return json.loads((bench_fixtures / "executions" / name).read_text())


def make_node(
    name: str,
    node_type: str = "n8n-nodes-base.set",
    **extra: Any,
) -> Dict[str, Any]:
    node = {
        "name": name,
        "type": node_type,
        "typeVersion": 1,
        "position": [0, 0],
        "parameters": {},
    }
    node.update(extra)
    return node


def chain_workflow(executing: int, sticky: int = 0) -> Dict[str, Any]:
    """A linear chain of `executing` Set nodes plus `sticky` annotation-only notes."""
    nodes: List[Dict[str, Any]] = [make_node(f"N{i}") for i in range(executing)]
    nodes += [
        make_node(f"S{i}", "n8n-nodes-base.stickyNote") for i in range(sticky)
    ]
    connections = {
        f"N{i}": {"main": [[{"node": f"N{i + 1}", "type": "main", "index": 0}]]}
        for i in range(executing - 1)
    }
    return {"name": "chain", "nodes": nodes, "connections": connections}


def cycle_workflow(loop_node_type: Optional[str] = None) -> Dict[str, Any]:
    """Start -> Loop -> Work -> Loop. A graph cycle; bounded iff the loop node is a
    bounded n8n construct (Loop Over Items / SplitInBatches)."""
    nodes = [
        make_node("Start", "n8n-nodes-base.manualTrigger"),
        make_node("Loop", loop_node_type or "n8n-nodes-base.set"),
        make_node("Work"),
    ]
    connections = {
        "Start": {"main": [[{"node": "Loop", "type": "main", "index": 0}]]},
        "Loop": {"main": [[{"node": "Work", "type": "main", "index": 0}]]},
        "Work": {"main": [[{"node": "Loop", "type": "main", "index": 0}]]},
    }
    return {"name": "cycle", "nodes": nodes, "connections": connections}


def execution_doc(
    run_data: Dict[str, Any],
    nodes: Optional[List[Dict[str, Any]]] = None,
    **top: Any,
) -> Dict[str, Any]:
    """A minimal n8n execution record in the public-API shape the parser consumes."""
    doc: Dict[str, Any] = {
        "executionId": "exec-test",
        "workflowId": "wf-test",
        "mode": "webhook",
        "data": {"resultData": {"runData": run_data}},
    }
    if nodes is not None:
        doc["workflowData"] = {"nodes": nodes, "connections": {}}
    doc.update(top)
    return doc


def fired_names(report: Any) -> List[str]:
    return sorted(d.detector for d in report.detections if d.detected)
