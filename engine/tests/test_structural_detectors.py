"""Structural-lane behavior, including the real-world precision fixes.

These tests freeze the guards derived from the 2,348-workflow community validation:
- cycle: a graph cycle through a bounded n8n loop construct (Loop Over Items /
  SplitInBatches) is an intentional batch loop, NOT an infinite-loop risk.
- complexity: sticky notes are annotations, not executing nodes; the node-count
  threshold applies to executing nodes only.
- schema: the static workflow-JSON path is disabled by design (n8n's dynamic JSON
  carries no static type contract), so it must never fire on this lane.
"""
from __future__ import annotations

import pytest

from pisama_n8n_engine.orchestrator import analyze

from conftest import chain_workflow, cycle_workflow, fired_names


class TestCycle:
    def test_unbounded_cycle_fires(self):
        report = analyze(workflow_json=cycle_workflow())
        assert "cycle" in fired_names(report)

    @pytest.mark.parametrize(
        "loop_type",
        ["n8n-nodes-base.splitInBatches", "n8n-nodes-base.loopOverItems"],
    )
    def test_bounded_loop_construct_does_not_fire(self, loop_type):
        # The precision guard: 237/238 community "cycles" were these intentional
        # bounded loops. A regression here re-opens catastrophic over-firing.
        report = analyze(workflow_json=cycle_workflow(loop_type))
        assert "cycle" not in fired_names(report)

    def test_linear_dag_does_not_fire(self):
        report = analyze(workflow_json=chain_workflow(10))
        assert "cycle" not in fired_names(report)


class TestComplexity:
    def test_fires_above_node_count_threshold(self):
        assert "complexity" in fired_names(analyze(workflow_json=chain_workflow(41)))

    def test_silent_at_or_below_threshold(self):
        assert "complexity" not in fired_names(analyze(workflow_json=chain_workflow(39)))

    def test_sticky_notes_are_not_executing_nodes(self):
        # 30 executing + 25 sticky = 55 total nodes; only executing nodes count.
        report = analyze(workflow_json=chain_workflow(30, sticky=25))
        assert "complexity" not in fired_names(report)

    def test_sticky_notes_do_not_shield_a_genuinely_large_workflow(self):
        report = analyze(workflow_json=chain_workflow(41, sticky=20))
        assert "complexity" in fired_names(report)


class TestSchema:
    def test_static_path_is_disabled_by_design(self):
        # Was 31.5% fire rate at ~0 precision on real workflows; the workflow-JSON
        # path is deliberately disabled. It must not fire even on a large chain.
        for wf in (chain_workflow(3), chain_workflow(60), cycle_workflow()):
            assert "schema" not in fired_names(analyze(workflow_json=wf))
