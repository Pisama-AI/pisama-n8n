"""Live e2e for the API-polling ingestion channel — real n8n, no mocks.

Gated on PISAMA_HARNESS_N8N=1 + a reachable n8n at PISAMA_TEST_N8N_URL (default
http://127.0.0.1:5679, the docker-compose.healing-harness.yml instance), because it
provisions a key, creates + runs a real failing workflow, then polls it back. Skipped by
default so the normal test run needs no docker.
"""

import os
import time
import uuid
from asyncio import run
from copy import deepcopy
from typing import Any, Dict, List, Tuple

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PISAMA_HARNESS_N8N") != "1",
    reason="set PISAMA_HARNESS_N8N=1 with a live n8n to run the polling e2e",
)

N8N_URL = os.environ.get("PISAMA_TEST_N8N_URL", "http://127.0.0.1:5679")
OWNER = ("harness@pisama.test", "PisamaHarness123!")
_PROVISIONED_KEY: str | None = None


def _provision_key() -> str:
    """Provision one scoped harness key per test process, never one per test.

    Creating a fresh REST session and API key for every case eventually rate-limits
    n8n's login endpoint. Reusing this short-lived key keeps the live suite an
    accurate product test rather than a test of the harness rate limiter.
    """
    global _PROVISIONED_KEY
    configured_key = os.environ.get("PISAMA_TEST_N8N_API_KEY")
    if configured_key:
        return configured_key
    if _PROVISIONED_KEY:
        return _PROVISIONED_KEY
    with httpx.Client(base_url=N8N_URL, timeout=30) as c:
        c.post(
            "/rest/owner/setup",
            json={
                "email": OWNER[0],
                "firstName": "P",
                "lastName": "H",
                "password": OWNER[1],
            },
        )
        login = c.post(
            "/rest/login", json={"emailOrLdapLoginId": OWNER[0], "password": OWNER[1]}
        )
        login.raise_for_status()
        tok = c.cookies.get("n8n-auth")
        h = {"Cookie": f"n8n-auth={tok}"}
        scopes_response = c.get("/rest/api-keys/scopes", headers=h)
        scopes_response.raise_for_status()
        sc = scopes_response.json().get("data", [])
        scopes = [s for s in sc if s.startswith(("workflow:", "execution:"))]
        r = c.post(
            "/rest/api-keys",
            json={
                "label": f"poll-test-{uuid.uuid4().hex}",
                "expiresAt": int(time.time()) + 3600,
                "scopes": scopes,
            },
            headers=h,
        )
        r.raise_for_status()
        _PROVISIONED_KEY = r.json()["data"]["rawApiKey"]
        return _PROVISIONED_KEY


def _create_active_workflow(
    key: str,
    name: str,
    nodes: List[Dict[str, Any]],
    connections: Dict[str, Any],
    settings: Dict[str, Any] | None = None,
) -> str:
    """Create one disposable real n8n workflow and return its API id."""
    wf = {
        "name": name,
        "settings": settings or {},
        "nodes": nodes,
        "connections": connections,
    }
    h = {"X-N8N-API-KEY": key}
    with httpx.Client(base_url=N8N_URL + "/api/v1", headers=h, timeout=30) as c:
        body = c.post("/workflows", json=wf).json()
        wid = (body.get("data", body))["id"]
        c.post(f"/workflows/{wid}/activate")
    return wid


def _webhook_node(path: str) -> Dict[str, Any]:
    return {
        "id": "w",
        "name": "Webhook",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 2,
        "position": [0, 0],
        "parameters": {"path": path, "httpMethod": "POST", "responseMode": "lastNode"},
        "webhookId": path,
    }


def _create_active_webhook_workflow(
    key: str, path: str, name: str, node: Dict[str, Any]
) -> str:
    return _create_active_workflow(
        key,
        name,
        [_webhook_node(path), node],
        {"Webhook": {"main": [[{"node": node["name"], "type": "main", "index": 0}]]}},
    )


def _trigger_webhook(path: str) -> httpx.Response:
    return httpx.post(f"{N8N_URL}/webhook/{path}", json={}, timeout=15)


def _run_failing_workflow(key: str) -> str:
    path = f"polltest-{uuid.uuid4().hex[:8]}"
    wid = _create_active_webhook_workflow(
        key,
        path,
        f"poll-{path}",
        {
            "id": "c",
            "name": "Boom",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [220, 0],
            "parameters": {"jsCode": "throw new Error('poll test');"},
        },
    )
    _trigger_webhook(path)
    time.sleep(2)
    return wid


def _run_failing_workflow_with_invalid_error_route(key: str) -> Tuple[str, str]:
    """Capture n8n silently skipping a configured target without Error Trigger."""
    suffix = uuid.uuid4().hex[:8]
    target_path = f"error-route-target-{suffix}"
    source_path = f"error-route-source-{suffix}"
    target = _create_active_webhook_workflow(
        key,
        target_path,
        f"poll-{target_path}",
        {
            "id": "target-code",
            "name": "Ordinary target node",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [220, 0],
            "parameters": {"jsCode": "return [{ json: { target: true } }];"},
        },
    )
    source = _create_active_workflow(
        key,
        f"poll-{source_path}",
        [
            _webhook_node(source_path),
            {
                "id": "source-boom",
                "name": "Source failure",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [220, 0],
                "parameters": {
                    "jsCode": "throw new Error('controlled invalid error route');"
                },
            },
        ],
        {
            "Webhook": {
                "main": [[{"node": "Source failure", "type": "main", "index": 0}]]
            }
        },
        settings={"errorWorkflow": target},
    )
    response = _trigger_webhook(source_path)
    assert response.status_code == 500, response.text
    time.sleep(2)
    return source, target


def _run_failing_workflow_with_missing_error_target(key: str) -> str:
    """Capture an accepted n8n error-workflow ID that no longer exists."""
    suffix = uuid.uuid4().hex[:8]
    source_path = f"error-route-missing-{suffix}"
    source = _create_active_workflow(
        key,
        f"poll-{source_path}",
        [
            _webhook_node(source_path),
            {
                "id": "source-boom",
                "name": "Source failure",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [220, 0],
                "parameters": {
                    "jsCode": "throw new Error('controlled missing error route');"
                },
            },
        ],
        {
            "Webhook": {
                "main": [[{"node": "Source failure", "type": "main", "index": 0}]]
            }
        },
        settings={"errorWorkflow": f"missing-{suffix}"},
    )
    response = _trigger_webhook(source_path)
    assert response.status_code == 500, response.text
    time.sleep(2)
    return source


def _run_timeout_workflow(key: str) -> str:
    """Run an actual delayed external request through n8n's configured timeout."""
    path = f"timeout-{uuid.uuid4().hex[:8]}"
    wid = _create_active_webhook_workflow(
        key,
        path,
        f"poll-{path}",
        {
            "id": "slow-request",
            "name": "Delayed provider",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [220, 0],
            "parameters": {
                "method": "GET",
                "url": "https://httpbin.org/delay/5",
                "options": {"timeout": 500},
            },
        },
    )
    response = _trigger_webhook(path)
    assert response.status_code == 500, response.text
    time.sleep(2)
    return wid


def _run_payload_growth_workflow(key: str) -> str:
    """Produce a bounded, real n8n data amplification execution."""
    path = f"payload-{uuid.uuid4().hex[:8]}"
    seed = {
        "id": "seed",
        "name": "Seed payload",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [220, 0],
        "parameters": {"jsCode": 'return [{ json: { source: "dogfood" } }];'},
    }
    expand = {
        "id": "expand",
        "name": "Expand payload",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [440, 0],
        "parameters": {
            "jsCode": (
                "return Array.from({ length: 10 }, (_, index) => "
                '({ json: { index, payload: "x".repeat(1500) } }));'
            )
        },
    }
    wid = _create_active_workflow(
        key,
        f"poll-{path}",
        [_webhook_node(path), seed, expand],
        {
            "Webhook": {
                "main": [[{"node": "Seed payload", "type": "main", "index": 0}]]
            },
            "Seed payload": {
                "main": [[{"node": "Expand payload", "type": "main", "index": 0}]]
            },
        },
    )
    response = _trigger_webhook(path)
    assert response.status_code == 200, response.text
    time.sleep(2)
    return wid


def _run_retrying_post_to_disposable_sink(key: str) -> Tuple[str, str]:
    """Use two real n8n workflows to observe retry metadata without side effects."""
    suffix = uuid.uuid4().hex[:8]
    sink_path = f"retry-sink-{suffix}"
    caller_path = f"retry-caller-{suffix}"
    sink = _create_active_webhook_workflow(
        key,
        sink_path,
        f"poll-{sink_path}",
        {
            "id": "sink-failure",
            "name": "Disposable sink failure",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [220, 0],
            "parameters": {
                "jsCode": "throw new Error('disposable retry sink failure');"
            },
        },
    )
    caller = _create_active_webhook_workflow(
        key,
        caller_path,
        f"poll-{caller_path}",
        {
            "id": "unsafe-post",
            "name": "Unsafe retrying POST",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [220, 0],
            "retryOnFail": True,
            "maxTries": 2,
            "waitBetweenTries": 100,
            "parameters": {
                "method": "POST",
                "url": f"http://127.0.0.1:5678/webhook/{sink_path}",
                "options": {},
            },
        },
    )
    response = _trigger_webhook(caller_path)
    assert response.status_code == 500, response.text
    time.sleep(3)
    return sink, caller


def _run_two_item_loop(
    key: str, path: str, work: Dict[str, Any], expected_status: int
) -> str:
    """Run a real bounded n8n loop with two distinct input items."""
    seed = {
        "id": "seed",
        "name": "Seed items",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [220, 0],
        "parameters": {
            "jsCode": (
                "return [{ json: { index: 0, event: 'first' } }, "
                "{ json: { index: 1, event: 'second' } }];"
            )
        },
    }
    loop = {
        "id": "loop",
        "name": "Loop Over Items",
        "type": "n8n-nodes-base.splitInBatches",
        "typeVersion": 3,
        "position": [440, 0],
        "parameters": {"batchSize": 1, "options": {}},
    }
    work_name = work["name"]
    workflow_id = _create_active_workflow(
        key,
        f"poll-{path}",
        [_webhook_node(path), seed, loop, work],
        {
            "Webhook": {
                "main": [[{"node": "Seed items", "type": "main", "index": 0}]]
            },
            "Seed items": {
                "main": [
                    [{"node": "Loop Over Items", "type": "main", "index": 0}]
                ]
            },
            "Loop Over Items": {
                "main": [
                    [],
                    [{"node": work_name, "type": "main", "index": 0}],
                ]
            },
            work_name: {
                "main": [
                    [{"node": "Loop Over Items", "type": "main", "index": 0}]
                ]
            },
        },
    )
    response = _trigger_webhook(path)
    assert response.status_code == expected_status, response.text
    time.sleep(3)
    return workflow_id


def _run_looped_retry_failure(key: str) -> str:
    """Record two normal loop runs on a retry-enabled node, then fail the second."""
    path = f"retry-loop-{uuid.uuid4().hex[:8]}"
    work = {
        "id": "work",
        "name": "Retrying loop work",
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [660, 0],
        "retryOnFail": True,
        "maxTries": 2,
        "waitBetweenTries": 100,
        "parameters": {
            "jsCode": (
                "if ($json.index === 1) { "
                "throw new Error('controlled loop retry failure'); "
                "} return [{ json: $json }];"
            )
        },
    }
    return _run_two_item_loop(key, path, work, expected_status=500)


def _run_looped_posts_to_disposable_sink(key: str) -> Tuple[str, str]:
    """Run two intentional, distinct POST loop iterations without an idempotency key."""
    suffix = uuid.uuid4().hex[:8]
    sink_path = f"idempotency-sink-{suffix}"
    caller_path = f"idempotency-loop-{suffix}"
    sink = _create_active_webhook_workflow(
        key,
        sink_path,
        f"poll-{sink_path}",
        {
            "id": "sink",
            "name": "Record intentional event",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [220, 0],
            "parameters": {"jsCode": "return [{ json: { received: true } }];"},
        },
    )
    post = {
        "id": "post",
        "name": "Post distinct event",
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [660, 0],
        "parameters": {
            "method": "POST",
            "url": f"http://127.0.0.1:5678/webhook/{sink_path}",
            "options": {},
        },
    }
    caller = _run_two_item_loop(key, caller_path, post, expected_status=200)
    return sink, caller


def _recorded_node_run_count(key: str, workflow_id: str, node_name: str) -> int:
    """Read the retained count for one node from a real n8n execution."""
    headers = {"X-N8N-API-KEY": key}
    with httpx.Client(
        base_url=N8N_URL + "/api/v1", headers=headers, timeout=30
    ) as client:
        response = client.get(
            "/executions", params={"workflowId": workflow_id, "includeData": "true"}
        )
        response.raise_for_status()
    executions = response.json().get("data", [])
    assert len(executions) == 1
    run_data = (
        (executions[0].get("data") or {}).get("resultData", {}).get("runData", {})
    )
    return len(run_data.get(node_name, []))


def _delete_workflows(key: str, workflow_ids: List[str]) -> None:
    headers = {"X-N8N-API-KEY": key}
    with httpx.Client(
        base_url=N8N_URL + "/api/v1", headers=headers, timeout=30
    ) as client:
        for workflow_id in workflow_ids:
            client.post(f"/workflows/{workflow_id}/deactivate")
            client.delete(f"/workflows/{workflow_id}")


def _polling_client(tmp_path, monkeypatch, key: str, database_name: str):
    """Create a real temporary SQLite Pisama server against the live n8n harness."""
    monkeypatch.setenv("PISAMA_N8N_URL", N8N_URL)
    monkeypatch.setenv("PISAMA_N8N_API_KEY", key)
    monkeypatch.setenv("PISAMA_API_KEY", "srv-key")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / database_name}")
    import pisama_n8n_server.app as appmod
    from pisama_n8n_server.storage import Storage
    from fastapi.testclient import TestClient

    appmod._storage = Storage()
    return TestClient(appmod.app), {"Authorization": "Bearer srv-key"}, appmod._storage


def _fired_for_workflow(detections: List[Dict[str, Any]], workflow_id: str) -> set:
    return {
        (row["detector"], row["failure_mode"])
        for row in detections
        if row["workflow_id"] == workflow_id and row["detected"]
    }


def _detector_results_for_workflow(
    detections: List[Dict[str, Any]], workflow_id: str, detector: str
) -> List[Dict[str, Any]]:
    """Return every result from one detector retained for one workflow."""
    return [
        row
        for row in detections
        if row["workflow_id"] == workflow_id
        and row["detector"] == detector
    ]


def _retry_results_for_workflow(
    detections: List[Dict[str, Any]], workflow_id: str
) -> List[Dict[str, Any]]:
    return _detector_results_for_workflow(detections, workflow_id, "retry_recovery")


def _execution_ids_for_workflow(
    detections: List[Dict[str, Any]], workflow_id: str
) -> set:
    return {
        row["n8n_execution_id"]
        for row in detections
        if row["workflow_id"] == workflow_id and row["n8n_execution_id"]
    }


def test_poll_ingests_and_dedups(tmp_path, monkeypatch):
    key = _provision_key()
    wid = _run_failing_workflow(key)
    try:
        client, hb, _ = _polling_client(tmp_path, monkeypatch, key, "poll.db")

        r1 = client.post("/api/v1/n8n/sync", headers=hb)
        assert r1.status_code == 200, r1.text
        assert r1.json()["new"] >= 1

        dets = client.get("/api/v1/detections", headers=hb).json()
        assert any(d["detector"] == "error" and d["detected"] for d in dets)

        # Re-poll: nothing new (dedup on the upstream execution id).
        r2 = client.post("/api/v1/n8n/sync", headers=hb)
        assert r2.json()["new"] == 0
    finally:
        _delete_workflows(key, [wid])


def test_poll_detects_real_invalid_error_workflow_route(tmp_path, monkeypatch):
    """An actual failed execution reveals a configured target without Error Trigger.

    n8n accepts the target but does not execute it. The detector must name that
    configuration defect rather than treating every nonempty errorWorkflow id as safe.
    """
    key = _provision_key()
    source_id, target_id = _run_failing_workflow_with_invalid_error_route(key)
    try:
        client, headers, _ = _polling_client(
            tmp_path, monkeypatch, key, "broken-error-route.db"
        )
        sync = client.post("/api/v1/n8n/sync", headers=headers)
        assert sync.status_code == 200, sync.text
        detections = client.get("/api/v1/detections", headers=headers).json()
        source_fired = _fired_for_workflow(detections, source_id)
        assert (
            "error_workflow",
            "n8n_error_workflow_missing_trigger",
        ) in source_fired
        assert ("error_workflow", "n8n_missing_error_workflow") not in source_fired
        assert not _execution_ids_for_workflow(detections, target_id)
        route = next(
            row
            for row in detections
            if row["workflow_id"] == source_id
            and row["failure_mode"] == "n8n_error_workflow_missing_trigger"
        )
        assert route["evidence"] == {
            "error_trigger_count": 0,
            "error_workflow_id": target_id,
            "failed_nodes": ["Source failure"],
            "resolver_status": "available",
            "source_execution_id": route["n8n_execution_id"],
            "source_mode": "webhook",
        }
    finally:
        _delete_workflows(key, [source_id, target_id])


def test_poll_detects_real_missing_error_workflow_target(tmp_path, monkeypatch):
    """n8n accepts a stale error-workflow ID and only exposes it at poll time."""
    key = _provision_key()
    source_id = _run_failing_workflow_with_missing_error_target(key)
    try:
        client, headers, _ = _polling_client(
            tmp_path, monkeypatch, key, "missing-error-target.db"
        )
        sync = client.post("/api/v1/n8n/sync", headers=headers)
        assert sync.status_code == 200, sync.text
        detections = client.get("/api/v1/detections", headers=headers).json()
        source_fired = _fired_for_workflow(detections, source_id)
        assert (
            "error_workflow",
            "n8n_error_workflow_target_missing",
        ) in source_fired
        route = next(
            row
            for row in detections
            if row["workflow_id"] == source_id
            and row["failure_mode"] == "n8n_error_workflow_target_missing"
        )
        assert route["evidence"].get("resolver_status") == "missing"
        assert route["evidence"].get("error_workflow_id", "").startswith("missing-")
    finally:
        _delete_workflows(key, [source_id])


def test_poll_classifies_a_real_n8n_request_timeout(tmp_path, monkeypatch):
    """A configured n8n HTTP timeout may be recorded as a connection abort.

    This regression uses a real delayed external response and the n8n execution API,
    never a constructed trace. It protects the exact behavior captured in dogfood.
    """
    key = _provision_key()
    wid = _run_timeout_workflow(key)
    try:
        client, headers, _ = _polling_client(tmp_path, monkeypatch, key, "timeout.db")
        sync = client.post("/api/v1/n8n/sync", headers=headers)
        assert sync.status_code == 200, sync.text
        detections = client.get("/api/v1/detections", headers=headers).json()
        fired = _fired_for_workflow(detections, wid)
        assert {("timeout", "F13"), ("error", "n8n_timeout")} <= fired
    finally:
        _delete_workflows(key, [wid])


def test_poll_detects_real_runtime_payload_growth(tmp_path, monkeypatch):
    """A bounded n8n expansion must retain runtime evidence for resource F6."""
    key = _provision_key()
    wid = _run_payload_growth_workflow(key)
    try:
        client, headers, _ = _polling_client(tmp_path, monkeypatch, key, "payload.db")
        sync = client.post("/api/v1/n8n/sync", headers=headers)
        assert sync.status_code == 200, sync.text
        detections = client.get("/api/v1/detections", headers=headers).json()
        fired = _fired_for_workflow(detections, wid)
        assert ("resource", "F6") in fired
    finally:
        _delete_workflows(key, [wid])


def test_poll_records_when_n8n_hides_retry_attempts(tmp_path, monkeypatch):
    """n8n 1.91 retries the request but retains one caller runData record.

    Because the caller exports exactly one node run, retry_recovery cannot tell a
    non-retry from an observed retry, so the whole detector is withheld: it must not
    invent a retry-not-observed, exhausted-retry, or duplicate-side-effect claim from
    the two sink executions.
    """
    key = _provision_key()
    sink_id, caller_id = _run_retrying_post_to_disposable_sink(key)
    try:
        client, headers, _ = _polling_client(tmp_path, monkeypatch, key, "retry.db")
        sync = client.post("/api/v1/n8n/sync", headers=headers)
        assert sync.status_code == 200, sync.text
        detections = client.get("/api/v1/detections", headers=headers).json()
        caller_fired = _fired_for_workflow(detections, caller_id)
        sink_executions = _execution_ids_for_workflow(detections, sink_id)
        retry_findings = _retry_results_for_workflow(detections, caller_id)
        assert ("retry_recovery", "n8n_retry_not_observed") not in caller_fired
        assert ("retry_recovery", "n8n_retry_exhausted") not in caller_fired
        assert ("idempotency", "n8n_duplicate_side_effect_risk") not in caller_fired
        assert len(sink_executions) >= 2
        assert len(retry_findings) == 1
        retry_result = retry_findings[0]
        assert retry_result["detected"] is False
        assert retry_result["failure_mode"] is None
        assert retry_result["detector_version"] == "1.2"
        assert "withheld" in retry_result["explanation"]
    finally:
        _delete_workflows(key, [caller_id, sink_id])


def test_poll_withholds_retry_claim_for_repeated_loop_runs(tmp_path, monkeypatch):
    """Two real loop runs are not evidence that a node exhausted its retry budget."""
    key = _provision_key()
    workflow_id = _run_looped_retry_failure(key)
    try:
        assert _recorded_node_run_count(key, workflow_id, "Retrying loop work") == 2
        client, headers, _ = _polling_client(
            tmp_path, monkeypatch, key, "looped-retry.db"
        )
        sync = client.post("/api/v1/n8n/sync", headers=headers)
        assert sync.status_code == 200, sync.text
        detections = client.get("/api/v1/detections", headers=headers).json()
        fired = _fired_for_workflow(detections, workflow_id)
        retry_results = _retry_results_for_workflow(detections, workflow_id)
        assert ("retry_recovery", "n8n_retry_not_observed") not in fired
        assert ("retry_recovery", "n8n_retry_exhausted") not in fired
        assert len(retry_results) == 1
        retry_result = retry_results[0]
        assert retry_result["detected"] is False
        assert retry_result["failure_mode"] is None
        assert retry_result["detector_version"] == "1.2"
        assert "withheld" in retry_result["explanation"]
    finally:
        _delete_workflows(key, [workflow_id])


def test_poll_withholds_duplicate_side_effect_claim_for_looped_posts(
    tmp_path, monkeypatch
):
    """Two intended POST loop iterations cannot prove a duplicated business event."""
    key = _provision_key()
    sink_id, caller_id = _run_looped_posts_to_disposable_sink(key)
    try:
        assert _recorded_node_run_count(key, caller_id, "Post distinct event") == 2
        client, headers, _ = _polling_client(
            tmp_path, monkeypatch, key, "looped-posts.db"
        )
        sync = client.post("/api/v1/n8n/sync", headers=headers)
        assert sync.status_code == 200, sync.text
        detections = client.get("/api/v1/detections", headers=headers).json()
        fired = _fired_for_workflow(detections, caller_id)
        sink_executions = _execution_ids_for_workflow(detections, sink_id)
        idempotency_results = _detector_results_for_workflow(
            detections, caller_id, "idempotency"
        )
        assert len(sink_executions) >= 2
        assert ("idempotency", "n8n_duplicate_side_effect_risk") not in fired
        assert idempotency_results == []
    finally:
        _delete_workflows(key, [caller_id, sink_id])


def test_repair_verification_observes_a_real_post_apply_execution(
    tmp_path, monkeypatch
):
    """A disposable n8n workflow fails, is safely changed, then produces real
    post-apply evidence. No replayed fixture or fabricated execution participates."""
    key = _provision_key()
    wid = _run_failing_workflow(key)
    repair_ids = []
    storage = None
    try:
        monkeypatch.setenv("PISAMA_COMPARISON_MIN_EXECUTIONS", "1")
        from pisama_n8n_server.fixes import apply_fix, rollback
        from pisama_n8n_server.n8n_client import N8nClient

        client, headers, storage = _polling_client(
            tmp_path, monkeypatch, key, "verification.db"
        )
        first_sync = client.post("/api/v1/n8n/sync", headers=headers)
        assert first_sync.status_code == 200, first_sync.text
        source = next(
            row
            for row in client.get("/api/v1/detections", headers=headers).json()
            if row["detector"] == "error"
            and row["detected"]
            and row["workflow_id"] == wid
        )

        async def apply_reviewed_change(baseline, proposed):
            n8n = N8nClient(N8N_URL, key)
            try:
                applied = await apply_fix(n8n, wid, baseline, proposed)
                workflow = await n8n.get_workflow(wid)
                return applied, workflow
            finally:
                await n8n.aclose()

        async def fetch_workflow():
            n8n = N8nClient(N8N_URL, key)
            try:
                return await n8n.get_workflow(wid)
            finally:
                await n8n.aclose()

        try:
            # The storage proposal is the reviewed record. The actual PUT below
            # still uses the production stale guard, on real n8n state.
            baseline = run(fetch_workflow())
            proposed = deepcopy(baseline)
            boom = next(node for node in proposed["nodes"] if node["name"] == "Boom")
            boom["parameters"]["jsCode"] = "return [{ json: { repaired: true } }];"
            proposal = storage.create_repair_proposal(
                detection_id=source["id"],
                workflow_id=wid,
                baseline_workflow=baseline,
                suggestion={
                    "explanation": "Replace the controlled throw with a successful result.",
                    "patch_ops": [],
                    "mutated_workflow": proposed,
                },
            )
            repair_ids.append(proposal["id"])
            assert storage.claim_repair_apply(repair_ids[-1])
            # Construct a fresh client inside the coroutine because httpx clients
            # are bound to the event loop that owns them.
            applied, workflow = run(apply_reviewed_change(baseline, proposed))
            storage.mark_repair_applied(repair_ids[-1], **applied)

            # A second real workflow control can be applied to the same source
            # detection. Its later execution must update both open cases.
            second_baseline = workflow
            second_proposed = deepcopy(second_baseline)
            boom = next(
                node for node in second_proposed["nodes"] if node["name"] == "Boom"
            )
            boom["parameters"]["jsCode"] = (
                "return [{ json: { repaired: true, revision: 2 } }];"
            )
            second_proposal = storage.create_repair_proposal(
                detection_id=source["id"],
                workflow_id=wid,
                baseline_workflow=second_baseline,
                suggestion={
                    "explanation": "Add a durable revision marker to the repaired control.",
                    "patch_ops": [],
                    "mutated_workflow": second_proposed,
                },
            )
            repair_ids.append(second_proposal["id"])
            assert storage.claim_repair_apply(repair_ids[-1])
            second_applied, workflow = run(
                apply_reviewed_change(second_baseline, second_proposed)
            )
            storage.mark_repair_applied(repair_ids[-1], **second_applied)

            # The same real webhook now creates a later successful n8n execution.
            webhook = next(
                node for node in workflow["nodes"] if node["name"] == "Webhook"
            )
            path = webhook["parameters"]["path"]
            response = httpx.post(f"{N8N_URL}/webhook/{path}", json={}, timeout=15)
            assert response.status_code == 200, response.text
            time.sleep(2)
            second_sync = client.post("/api/v1/n8n/sync", headers=headers)
            assert second_sync.status_code == 200, second_sync.text

            cases = {
                case["repair_id"]: case
                for case in storage.list_reliability_cases()
                if case["repair_id"] in repair_ids
            }
            assert set(cases) == set(repair_ids)
            assert all(case["status"] == "observing" for case in cases.values())
            assert all(
                case["successful_execution_count"] >= 1 for case in cases.values()
            )
            assert all(case["recurrence_count"] == 0 for case in cases.values())
            assert all(case["comparison_ready"] for case in cases.values())
            assert all(case["recurrence_reduction"] == 1.0 for case in cases.values())
            metrics = client.get("/api/v1/reliability/metrics", headers=headers)
            assert metrics.status_code == 200, metrics.text
            assert metrics.json()["remediation"]["recurrence_reduction"] == 1.0
            # One execution is useful exposure evidence, never enough to assert prevention.
            early = client.post(
                f"/api/v1/reliability-cases/{cases[repair_ids[-1]]['id']}/outcome",
                headers=headers,
                json={"outcome": "prevented"},
            )
            assert early.status_code == 409
        finally:
            for repair_id in reversed(repair_ids):
                repair = storage.get_repair(repair_id, include_workflows=True)
                if repair and repair["status"] == "applied":
                    assert storage.claim_repair_rollback(repair_id)

                    async def restore_snapshot(repair_to_restore):
                        n8n = N8nClient(N8N_URL, key)
                        try:
                            return await rollback(
                                n8n,
                                wid,
                                repair_to_restore["snapshot"],
                                repair_to_restore["applied_workflow"],
                            )
                        finally:
                            await n8n.aclose()

                    restored = run(restore_snapshot(repair))
                    assert restored
                    storage.mark_repair_rolled_back(repair_id)
    finally:
        _delete_workflows(key, [wid])
