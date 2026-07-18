"""The first-class input-schema guardrail repair: propose -> choose destination ->
apply -> verify (malformed rejected + valid passed) -> prevented. No mocks: the whole
flow runs through the real app, engine, and SQLite; the live n8n write is a FakeClient
holding the workflow so apply/rollback are exercised without a real n8n."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"
H = {"Authorization": "Bearer k"}


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("PISAMA_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'g.db'}")
    monkeypatch.delenv("PISAMA_CLOUD_KEY", raising=False)  # guardrail is a FREE repair
    import pisama_n8n_server.app as appmod
    from pisama_n8n_server.storage import Storage

    appmod._storage = Storage()
    return appmod, TestClient(appmod.app)


def _seed_data_contract(client) -> int:
    fx = json.loads(
        (FIXTURES / "executions/data_contract/CLOUD-112117-missing-required-value.json").read_text()
    )
    client.post("/api/v1/n8n/webhook", headers=H, json=fx)
    rows = client.get("/api/v1/detections", headers=H).json()
    return next(
        r["id"] for r in rows
        if r["detector"] == "schema" and r["failure_mode"] == "n8n_data_contract"
    )


class _FakeN8n:
    """Holds the workflow so apply (PUT) and rollback are real state transitions."""

    def __init__(self, workflow):
        self.workflow = copy.deepcopy(workflow)

    async def get_workflow(self, _wid):
        return copy.deepcopy(self.workflow)

    async def update_workflow(self, _wid, workflow):
        self.workflow = copy.deepcopy(workflow)
        return copy.deepcopy(self.workflow)

    async def aclose(self):
        return None


def test_propose_derives_confirmed_paths_and_offers_destinations(tmp_path, monkeypatch):
    _, c = _client(tmp_path, monkeypatch)
    det = _seed_data_contract(c)
    r = c.post("/api/v1/n8n/guardrail", headers=H, json={"detection_id": det})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path_options"]["confirmed"] == ["required.value"]
    assert body["repair"]["guard_config"]["destination"] is None
    kinds = {d["kind"]: d for d in body["destinations"]}
    assert kinds["error_workflow"]["available"] is True
    # No webhook responseNode in the fixture workflow -> respond_422 offered-but-disabled.
    assert kinds["respond_422"]["available"] is False and kinds["respond_422"]["reason"]


def test_non_data_contract_detection_is_rejected(tmp_path, monkeypatch):
    _, c = _client(tmp_path, monkeypatch)
    # A non-schema detection id: reuse whatever fired; but the fixture also fires 'error'
    fx = json.loads(
        (FIXTURES / "executions/data_contract/CLOUD-112117-missing-required-value.json").read_text()
    )
    c.post("/api/v1/n8n/webhook", headers=H, json=fx)
    rows = c.get("/api/v1/detections", headers=H).json()
    other = next((r["id"] for r in rows if r["failure_mode"] != "n8n_data_contract"), None)
    if other is not None:
        r = c.post("/api/v1/n8n/guardrail", headers=H, json={"detection_id": other})
        assert r.status_code == 422


def test_apply_refused_without_destination_then_succeeds(tmp_path, monkeypatch):
    appmod, c = _client(tmp_path, monkeypatch)
    det = _seed_data_contract(c)
    repair = c.post("/api/v1/n8n/guardrail", headers=H, json={"detection_id": det}).json()["repair"]
    rid = repair["id"]

    # Live n8n holds the baseline workflow.
    fake = _FakeN8n(repair["baseline_workflow"])
    monkeypatch.setattr(appmod, "client_from_env", lambda: fake)

    # Apply before choosing a destination -> refused, repair stays proposed.
    r = c.post("/api/v1/n8n/apply", headers=H, json={"repair_id": rid})
    assert r.status_code == 409 and "destination" in r.json()["detail"]
    assert c.get("/api/v1/detections", headers=H)  # server still healthy
    assert appmod.get_storage().get_repair(rid)["status"] == "proposed"

    # Choose the error-workflow destination -> builds the guarded workflow.
    r = c.post(
        f"/api/v1/n8n/repairs/{rid}/destination",
        headers=H,
        json={"destination": "error_workflow"},
    )
    assert r.status_code == 200, r.text
    built = r.json()["repair"]
    names = {n["name"] for n in built["proposed_workflow"]["nodes"]}
    assert "Pisama input schema inspection" in names
    assert "Pisama rejected: stop and error" in names

    # Apply -> guard nodes now live; reliability case opened.
    r = c.post("/api/v1/n8n/apply", headers=H, json={"repair_id": rid})
    assert r.status_code == 200, r.text
    assert r.json()["repair"]["status"] == "applied"
    live_names = {n["name"] for n in fake.workflow["nodes"]}
    assert "Pisama input schema inspection" in live_names
    cases = c.get("/api/v1/reliability-cases", headers=H).json()
    assert cases and cases[0]["repair_id"] == rid


def test_respond_422_requires_response_node_mode(tmp_path, monkeypatch):
    _, c = _client(tmp_path, monkeypatch)
    det = _seed_data_contract(c)
    rid = c.post("/api/v1/n8n/guardrail", headers=H, json={"detection_id": det}).json()["repair"]["id"]
    r = c.post(
        f"/api/v1/n8n/repairs/{rid}/destination", headers=H, json={"destination": "respond_422"}
    )
    assert r.status_code == 422 and "responseMode" in r.json()["detail"]


def _guarded_case(appmod, c, monkeypatch):
    """Drive propose->destination->apply and return (case_id, guard_config, fake)."""
    det = _seed_data_contract(c)
    repair = c.post("/api/v1/n8n/guardrail", headers=H, json={"detection_id": det}).json()["repair"]
    rid = repair["id"]
    fake = _FakeN8n(repair["baseline_workflow"])
    monkeypatch.setattr(appmod, "client_from_env", lambda: fake)
    c.post(f"/api/v1/n8n/repairs/{rid}/destination", headers=H, json={"destination": "error_workflow"})
    c.post("/api/v1/n8n/apply", headers=H, json={"repair_id": rid})
    guard = appmod.get_storage().get_repair(rid, include_workflows=True)["guard_config"]
    case = c.get("/api/v1/reliability-cases", headers=H).json()[0]
    return case["id"], guard, c


def _ingest_execution_running(c, node_names, wf_id="0H6n1fY53bCT6rhX") -> int:
    """Ingest a minimal execution whose runData shows exactly `node_names` running."""
    run_data = {
        name: [{"executionStatus": "success", "executionTime": 1,
                "data": {"main": [[{"json": {"ok": True}}]]}}]
        for name in node_names
    }
    payload = {
        "id": None, "workflowId": wf_id, "finished": True, "mode": "manual",
        "workflowData": {"id": wf_id, "nodes": [], "connections": {}},
        "data": {"resultData": {"runData": run_data}},
    }
    c.post("/api/v1/n8n/webhook", headers=H, json=payload)
    rows = c.get("/api/v1/detections", headers=H).json()
    # execution_id is on the detection rows; grab the most recent execution id
    return max(r["execution_id"] for r in rows)


def test_guard_verification_records_real_routing_and_gates_prevented(tmp_path, monkeypatch):
    appmod, c = _client(tmp_path, monkeypatch)
    case_id, guard, c = _guarded_case(appmod, c, monkeypatch)
    consumer = guard["failing_node"]
    destination = guard["destination_node_name"]

    # Cannot conclude prevented yet: guardrail requires both probes (also needs successes,
    # but the probe gate is what we assert here).
    r = c.post(f"/api/v1/reliability-cases/{case_id}/outcome", headers=H, json={"outcome": "prevented"})
    assert r.status_code == 409

    # A malformed-input probe: the rejection destination ran, the consumer did NOT.
    rejected_exec = _ingest_execution_running(c, [guard["entry_node"], destination])
    r = c.post(
        f"/api/v1/reliability-cases/{case_id}/guard-verification",
        headers=H,
        json={"kind": "malformed_rejected", "execution_id": rejected_exec},
    )
    assert r.status_code == 200, r.text
    assert r.json()["guard_malformed_rejected_execution_id"] == rejected_exec

    # A probe claiming rejection but where the CONSUMER also ran is refused: malformed
    # input reached the business path despite the guard (the real routing check).
    bad_exec = _ingest_execution_running(c, [guard["entry_node"], destination, consumer])
    r = c.post(
        f"/api/v1/reliability-cases/{case_id}/guard-verification",
        headers=H,
        json={"kind": "malformed_rejected", "execution_id": bad_exec},
    )
    assert r.status_code == 409 and "reached the business path" in r.json()["detail"]

    # A valid-input probe: the consumer ran, the destination did NOT.
    valid_exec = _ingest_execution_running(c, [guard["entry_node"], guard["validated_node"], consumer])
    r = c.post(
        f"/api/v1/reliability-cases/{case_id}/guard-verification",
        headers=H,
        json={"kind": "valid_passed", "execution_id": valid_exec},
    )
    assert r.status_code == 200, r.text

    # Unknown execution id is refused.
    r = c.post(
        f"/api/v1/reliability-cases/{case_id}/guard-verification",
        headers=H,
        json={"kind": "valid_passed", "execution_id": 999999},
    )
    assert r.status_code == 409 and "Unknown execution" in r.json()["detail"]


def test_candidate_executions_annotate_routing_for_the_probe_picker(tmp_path, monkeypatch):
    """The picker's data source: recent executions of the guarded workflow, each classified
    by how it actually routed through this guard."""
    appmod, c = _client(tmp_path, monkeypatch)
    case_id, guard, c = _guarded_case(appmod, c, monkeypatch)
    consumer = guard["failing_node"]
    destination = guard["destination_node_name"]

    rejected_exec = _ingest_execution_running(c, [guard["entry_node"], destination])
    valid_exec = _ingest_execution_running(
        c, [guard["entry_node"], guard["validated_node"], consumer]
    )
    both_exec = _ingest_execution_running(c, [guard["entry_node"], destination, consumer])

    r = c.get(f"/api/v1/reliability-cases/{case_id}/candidate-executions", headers=H)
    assert r.status_code == 200, r.text
    by_id = {row["execution_id"]: row for row in r.json()}
    assert by_id[rejected_exec]["matches_kind"] == "malformed_rejected"
    assert by_id[rejected_exec]["destination_ran"] is True
    assert by_id[rejected_exec]["consumer_ran"] is False
    assert by_id[valid_exec]["matches_kind"] == "valid_passed"
    # Destination AND consumer both ran — not a clean probe for either check.
    assert by_id[both_exec]["matches_kind"] is None

    assert (
        c.get("/api/v1/reliability-cases/999999/candidate-executions", headers=H).status_code
        == 404
    )
