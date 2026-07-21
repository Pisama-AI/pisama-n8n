"""The error-route repair: propose -> pick a target -> apply -> routed-incident probe.

The second deterministic prevention primitive, and the self-host half of the parity the
SaaS server ships. No mocks: the whole flow runs through the real app, engine, and SQLite;
the live n8n write is a FakeClient holding a MULTI-workflow store so the target picker and
the apply PUT are real state transitions.

Two things here are load-bearing rather than incidental:

  1. the mutation is bounded by ``assert_safe_settings_diff``, so a repair that re-points a
     route leaves nodes and connections byte-identical, and
  2. ``prevented`` needs a real routed-incident probe. The apply-time static check (target
     resolves, has an Error Trigger, source points at it) proves the route is WELL-FORMED;
     it does not prove an incident was ever delivered.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"
H = {"Authorization": "Bearer k"}
SOURCE_WF = "go0usyYHRYoqrhCR"
TARGET_ID = "error-handler-wf"
TRIGGERLESS_ID = "no-trigger-wf"


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("PISAMA_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'er.db'}")
    monkeypatch.delenv("PISAMA_CLOUD_KEY", raising=False)  # deterministic = FREE repair
    import pisama_n8n_server.app as appmod
    from pisama_n8n_server.storage import Storage

    appmod._storage = Storage()
    return appmod, TestClient(appmod.app)


def _error_handler_workflow(wid, name, *, with_trigger):
    nodes = [{"name": "Notify", "type": "n8n-nodes-base.noOp", "typeVersion": 1,
              "position": [400, 200], "parameters": {}}]
    if with_trigger:
        nodes.insert(0, {"name": "Error Trigger", "type": "n8n-nodes-base.errorTrigger",
                         "typeVersion": 1, "position": [200, 200], "parameters": {}})
    return {"id": wid, "name": name, "nodes": nodes, "connections": {}, "settings": {}}


class _FakeN8n:
    """A multi-workflow store. n8n's LIST response carries no node arrays — mirrored
    deliberately, so eligibility is forced through the per-candidate fetch."""

    def __init__(self, source_workflow):
        source = copy.deepcopy(source_workflow)
        source.setdefault("settings", {}).pop("errorWorkflow", None)
        self.workflows = {
            SOURCE_WF: source,
            TARGET_ID: _error_handler_workflow(TARGET_ID, "Ops Alerting", with_trigger=True),
            TRIGGERLESS_ID: _error_handler_workflow(
                TRIGGERLESS_ID, "Just A Workflow", with_trigger=False
            ),
        }

    async def list_workflows(self, limit=250):
        return [{"id": wid, "name": wf.get("name")} for wid, wf in self.workflows.items()]

    async def get_workflow(self, wid):
        if wid not in self.workflows:
            raise RuntimeError(f"404 workflow {wid}")
        return copy.deepcopy(self.workflows[wid])

    async def update_workflow(self, wid, workflow):
        self.workflows[wid] = {**self.workflows.get(wid, {}), **copy.deepcopy(workflow)}
        return copy.deepcopy(self.workflows[wid])

    async def aclose(self):
        return None


def _seed_error_detection(c) -> int:
    """Ingest a failed execution whose workflow has no error route, and return the
    detection id for the missing-error-workflow finding."""
    fx = json.loads((FIXTURES / "executions/error/ERROR-01-throw.json").read_text())
    fx["workflowData"].setdefault("settings", {}).pop("errorWorkflow", None)
    c.post("/api/v1/n8n/webhook", headers=H, json=fx)
    rows = c.get("/api/v1/detections", headers=H).json()
    det = next(
        (r["id"] for r in rows
         if r["detected"] and r["failure_mode"] == "n8n_missing_error_workflow"),
        None,
    )
    assert det is not None, f"no error-workflow detection in {[r['failure_mode'] for r in rows]}"
    return det


def _proposed(appmod, c, monkeypatch):
    """Seed a detection and propose an error-route repair. Returns (repair_id, fake)."""
    det = _seed_error_detection(c)
    fx = json.loads((FIXTURES / "executions/error/ERROR-01-throw.json").read_text())
    fake = _FakeN8n(fx["workflowData"])
    monkeypatch.setattr(appmod, "client_from_env", lambda: fake)
    r = c.post("/api/v1/n8n/error-route", headers=H, json={"detection_id": det})
    assert r.status_code == 200, r.text
    return r.json()["repair"]["id"], fake


def _applied(appmod, c, monkeypatch, target=TARGET_ID):
    rid, fake = _proposed(appmod, c, monkeypatch)
    r = c.post(f"/api/v1/n8n/repairs/{rid}/error-target", headers=H,
               json={"target_workflow_id": target})
    assert r.status_code == 200, r.text
    r = c.post("/api/v1/n8n/apply", headers=H, json={"repair_id": rid})
    assert r.status_code == 200, r.text
    case = c.get("/api/v1/reliability-cases", headers=H).json()[0]
    return rid, case["id"], fake


# ── the target picker ────────────────────────────────────────────────────────

def test_target_picker_marks_eligibility_and_excludes_self(tmp_path, monkeypatch):
    appmod, c = _client(tmp_path, monkeypatch)
    rid, _fake = _proposed(appmod, c, monkeypatch)

    targets = c.get(f"/api/v1/n8n/repairs/{rid}/error-targets", headers=H).json()["targets"]
    by_id = {t["id"]: t for t in targets}

    assert SOURCE_WF not in by_id  # a workflow cannot be its own error handler
    assert by_id[TARGET_ID]["eligible"] is True
    # Newer n8n only invokes ACTIVE error workflows; an eligible-but-inactive
    # target must carry the activation warning so the route cannot silently die.
    assert by_id[TARGET_ID]["active"] is False
    assert "Activate" in by_id[TARGET_ID]["reason"]
    # Ineligible candidates are RETURNED with a reason, not filtered out: an operator who
    # sees "No Error Trigger node" learns what to add; a short list just looks broken.
    assert by_id[TRIGGERLESS_ID]["eligible"] is False
    assert "Error Trigger" in by_id[TRIGGERLESS_ID]["reason"]


def test_target_without_error_trigger_is_refused(tmp_path, monkeypatch):
    appmod, c = _client(tmp_path, monkeypatch)
    rid, _fake = _proposed(appmod, c, monkeypatch)
    r = c.post(f"/api/v1/n8n/repairs/{rid}/error-target", headers=H,
               json={"target_workflow_id": TRIGGERLESS_ID})
    assert r.status_code == 422 and "Error Trigger" in r.json()["detail"]


def test_unknown_target_is_refused(tmp_path, monkeypatch):
    appmod, c = _client(tmp_path, monkeypatch)
    rid, _fake = _proposed(appmod, c, monkeypatch)
    r = c.post(f"/api/v1/n8n/repairs/{rid}/error-target", headers=H,
               json={"target_workflow_id": "nope"})
    assert r.status_code == 422


# ── apply is bounded to settings ─────────────────────────────────────────────

def test_apply_repoints_route_and_leaves_nodes_byte_identical(tmp_path, monkeypatch):
    appmod, c = _client(tmp_path, monkeypatch)
    rid, _case_id, fake = _applied(appmod, c, monkeypatch)

    live = fake.workflows[SOURCE_WF]
    assert live["settings"]["errorWorkflow"] == TARGET_ID
    # The safety claim of this primitive, asserted after a real PUT: a route repair
    # touches the route and nothing else.
    baseline = appmod.get_storage().get_repair(rid, include_workflows=True)["baseline_workflow"]
    assert live["nodes"] == baseline["nodes"]
    assert live["connections"] == baseline["connections"]


def test_apply_without_a_target_is_refused_before_claiming(tmp_path, monkeypatch):
    appmod, c = _client(tmp_path, monkeypatch)
    rid, _fake = _proposed(appmod, c, monkeypatch)

    r = c.post("/api/v1/n8n/apply", headers=H, json={"repair_id": rid})
    assert r.status_code == 409 and "target error workflow" in r.json()["detail"]
    # Refused BEFORE the claim, so the repair is never stranded in 'applying'.
    assert appmod.get_storage().get_repair(rid)["status"] == "proposed"


# ── the routed-incident probe ────────────────────────────────────────────────

def _ingest_execution(c, wf_id, *, started_at=None) -> int:
    payload = {
        "id": None, "workflowId": wf_id, "finished": True, "mode": "manual",
        "workflowData": {"id": wf_id, "nodes": [], "connections": {}},
        "data": {"resultData": {"runData": {
            "Notify": [{"executionStatus": "success", "executionTime": 1,
                        "data": {"main": [[{"json": {"ok": True}}]]}}]
        }}},
    }
    if started_at:
        payload["startedAt"] = started_at
    c.post("/api/v1/n8n/webhook", headers=H, json=payload)
    rows = c.get("/api/v1/detections", headers=H).json()
    return max(r["execution_id"] for r in rows)


def test_prevented_requires_a_routed_incident_probe(tmp_path, monkeypatch):
    appmod, c = _client(tmp_path, monkeypatch)
    _rid, case_id, _fake = _applied(appmod, c, monkeypatch)

    # The apply-time static check already passed. That proves the route is WELL-FORMED,
    # not that it delivered — so 'prevented' is still refused.
    r = c.post(f"/api/v1/reliability-cases/{case_id}/outcome", headers=H,
               json={"outcome": "prevented"})
    assert r.status_code == 409

    exec_id = _ingest_execution(c, TARGET_ID)
    r = c.post(f"/api/v1/reliability-cases/{case_id}/route-verification", headers=H,
               json={"execution_id": exec_id})
    assert r.status_code == 200, r.text
    assert r.json()["guard_route_delivered_execution_id"] == exec_id

    # The probe gate has now CLEARED — what still blocks is the self-host server's own
    # post-repair success-count gate, which is a different bar and not this track's.
    # Asserting the message is what proves the probe requirement was satisfied rather
    # than merely swapped for another refusal.
    r = c.post(f"/api/v1/reliability-cases/{case_id}/outcome", headers=H,
               json={"outcome": "prevented"})
    assert r.status_code == 409
    assert "successful post-repair executions" in r.json()["detail"]


def test_probe_from_a_different_workflow_is_refused(tmp_path, monkeypatch):
    appmod, c = _client(tmp_path, monkeypatch)
    _rid, case_id, _fake = _applied(appmod, c, monkeypatch)

    # An execution of the SOURCE workflow is not evidence that the ERROR ROUTE delivered.
    exec_id = _ingest_execution(c, SOURCE_WF)
    r = c.post(f"/api/v1/reliability-cases/{case_id}/route-verification", headers=H,
               json={"execution_id": exec_id})
    assert r.status_code == 409 and "different workflow" in r.json()["detail"]


def test_probe_predating_the_apply_is_refused(tmp_path, monkeypatch):
    appmod, c = _client(tmp_path, monkeypatch)
    _rid, case_id, _fake = _applied(appmod, c, monkeypatch)

    exec_id = _ingest_execution(c, TARGET_ID, started_at="2000-01-01T00:00:00+00:00")
    r = c.post(f"/api/v1/reliability-cases/{case_id}/route-verification", headers=H,
               json={"execution_id": exec_id})
    assert r.status_code == 409 and "predates" in r.json()["detail"]


def test_route_probe_and_guard_probes_are_not_interchangeable(tmp_path, monkeypatch):
    """Each primitive is verified by its OWN probe. Letting one satisfy the other would
    quietly downgrade the guardrail's two-probe bar to a single unrelated execution."""
    appmod, c = _client(tmp_path, monkeypatch)
    _rid, case_id, _fake = _applied(appmod, c, monkeypatch)
    exec_id = _ingest_execution(c, TARGET_ID)

    r = c.post(f"/api/v1/reliability-cases/{case_id}/guard-verification", headers=H,
               json={"kind": "malformed_rejected", "execution_id": exec_id})
    assert r.status_code == 409 and "error_route" in r.json()["detail"]
