"""The MCP tool surface: pins, shaping, and dispatch through the REAL app.

No mocks: dispatch runs against the actual FastAPI app + engine + SQLite via
httpx.ASGITransport. Two things here are load-bearing:

  1. the tool-surface pin — read + propose ONLY. The deliberate ABSENCE of
     apply/rollback/outcome/verification tools is the product boundary (operators
     apply in the dashboard), so a tool that would write to live n8n failing to
     exist is asserted, not assumed;
  2. the shaping invariant — truncation never drops an id or enum a follow-up
     tool call needs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("mcp")

import httpx  # noqa: E402

from pisama_n8n_server.mcp import TOOLS, dispatch  # noqa: E402
from pisama_n8n_server.mcp.server import (  # noqa: E402
    PisamaN8nMCPClient,
    create_server,
    shape_repair,
    shape_trace,
)

FIXTURES = Path(__file__).parent / "fixtures"
H = {"Authorization": "Bearer k"}

EXPECTED_TOOLS = [
    "pisama_n8n_choose_error_route_target",
    "pisama_n8n_choose_guardrail_destination",
    "pisama_n8n_get_detection",
    "pisama_n8n_get_detection_trace",
    "pisama_n8n_list_detections",
    "pisama_n8n_list_error_route_targets",
    "pisama_n8n_list_reliability_cases",
    "pisama_n8n_operations_summary",
    "pisama_n8n_propose_error_route",
    "pisama_n8n_propose_guardrail",
]


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("PISAMA_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'mcp.db'}")
    monkeypatch.delenv("PISAMA_CLOUD_KEY", raising=False)
    import pisama_n8n_server.app as appmod
    from pisama_n8n_server.storage import Storage

    appmod._storage = Storage()
    return appmod


def _mcp_client(appmod, api_key="k"):
    return PisamaN8nMCPClient(
        base_url="http://mcp-test",
        api_key=api_key,
        transport=httpx.ASGITransport(app=appmod.app),
    )


def _seed_data_contract(appmod) -> int:
    from fastapi.testclient import TestClient

    c = TestClient(appmod.app)
    fx = json.loads(
        (FIXTURES / "executions/data_contract/CLOUD-112117-missing-required-value.json").read_text()
    )
    c.post("/api/v1/n8n/webhook", headers=H, json=fx)
    rows = c.get("/api/v1/detections", headers=H).json()
    return next(
        r["id"] for r in rows
        if r["detector"] == "schema" and r["failure_mode"] == "n8n_data_contract"
    )


# -- the tool-surface pin -----------------------------------------------------


def test_tool_surface_is_exactly_read_plus_propose():
    assert sorted(t.name for t in TOOLS) == EXPECTED_TOOLS
    # The boundary: nothing that writes to live n8n or records operator judgments.
    banned = ("apply", "rollback", "outcome", "verification", "feedback",
              "seen", "sync", "webhook")
    for tool in TOOLS:
        for word in banned:
            assert word not in tool.name, f"{tool.name} crosses the propose boundary"


def test_annotations_and_schemas_are_pinned():
    reads = {n for n in EXPECTED_TOOLS
             if n.startswith(("pisama_n8n_list", "pisama_n8n_get", "pisama_n8n_operations"))}
    for tool in TOOLS:
        assert tool.annotations is not None
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.readOnlyHint is (tool.name in reads)
        assert tool.inputSchema["type"] == "object"
        assert tool.inputSchema["additionalProperties"] is False
        for prop in ("detection_id", "repair_id"):
            if prop in tool.inputSchema["properties"]:
                assert tool.inputSchema["properties"][prop]["type"] == "integer"
    # Every propose description states where applying actually happens.
    for tool in TOOLS:
        if tool.annotations.readOnlyHint is False:
            assert "dashboard" in tool.description


# -- dispatch through the real app -------------------------------------------


async def test_list_and_get_detections_shape(tmp_path, monkeypatch):
    appmod = _app(tmp_path, monkeypatch)
    det = _seed_data_contract(appmod)
    client = _mcp_client(appmod)

    listing = await dispatch(client, "pisama_n8n_list_detections", {})
    assert listing["returned"] >= 1
    row = next(r for r in listing["detections"] if r["id"] == det)
    assert "evidence" not in row  # list rows are summaries
    assert row["failure_mode"] == "n8n_data_contract"

    detail = await dispatch(client, "pisama_n8n_get_detection", {"detection_id": det})
    assert detail["id"] == det and isinstance(detail["evidence"], dict)

    trace = await dispatch(
        client, "pisama_n8n_get_detection_trace", {"detection_id": det}
    )
    assert trace["node_count"] >= 1

    summary = await dispatch(client, "pisama_n8n_operations_summary", {})
    assert summary["executions_analyzed"] >= 1


async def test_propose_guardrail_keeps_decision_surface_drops_workflows(
    tmp_path, monkeypatch
):
    appmod = _app(tmp_path, monkeypatch)
    det = _seed_data_contract(appmod)
    client = _mcp_client(appmod)

    result = await dispatch(
        client, "pisama_n8n_propose_guardrail", {"detection_id": det}
    )
    # Same oracle as test_guardrail.py: the evidence-derived confirmed path.
    assert result["path_options"]["confirmed"] == ["required.value"]
    repair = result["repair"]
    assert isinstance(repair["id"], int)
    assert repair["guard_config"]["paths"] == ["required.value"]
    # The shaping invariant: no raw workflow bodies, but their summaries exist.
    assert "baseline_workflow" not in repair
    assert repair["baseline_workflow_summary"]["node_count"] >= 1
    assert {d["kind"] for d in result["destinations"]} == {
        "error_workflow", "alert", "respond_422"
    }

    chosen = await dispatch(
        client,
        "pisama_n8n_choose_guardrail_destination",
        {"repair_id": repair["id"], "destination": "error_workflow"},
    )
    assert chosen["repair"]["guard_config"]["destination"] == "error_workflow"
    assert "proposed_workflow" not in chosen["repair"]


async def test_error_mapping(tmp_path, monkeypatch):
    appmod = _app(tmp_path, monkeypatch)
    _seed_data_contract(appmod)
    server = create_server(_mcp_client(appmod))
    handler = server.request_handlers[type(_call_tool_request("x", {}))]

    # 404 from the real app -> isError with upstream status + FastAPI detail.
    res = await handler(_call_tool_request("pisama_n8n_get_detection", {"detection_id": 99999}))
    tool_result = res.root
    assert tool_result.isError is True
    assert tool_result.structuredContent["error"]["status_code"] == 404
    assert "Unknown detection id." in str(tool_result.structuredContent["error"]["detail"])

    # Wrong bearer -> 401 with the actionable key hint.
    server_bad = create_server(_mcp_client(appmod, api_key="wrong"))
    handler_bad = server_bad.request_handlers[type(_call_tool_request("x", {}))]
    res = await handler_bad(_call_tool_request("pisama_n8n_list_detections", {}))
    assert res.root.isError is True
    assert "PISAMA_API_KEY" in res.root.content[0].text

    # Missing required arg -> the SDK's schema validation rejects it before our
    # dispatch runs; either way the caller sees isError, never a crash.
    res = await handler(_call_tool_request("pisama_n8n_get_detection", {}))
    assert res.root.isError is True

    # Unknown tool name -> error result, not a crash.
    res = await handler(_call_tool_request("pisama_n8n_apply", {}))
    assert res.root.isError is True


async def test_dispatch_validates_before_any_http_call(tmp_path, monkeypatch):
    # dispatch()-level validation is ours (not the SDK's): a client with no
    # transport would explode on any HTTP call, so a clean ValueError proves the
    # request never left the process.
    client = PisamaN8nMCPClient(base_url="http://127.0.0.1:9")
    with pytest.raises(ValueError, match="positive integer"):
        await dispatch(client, "pisama_n8n_get_detection", {})
    with pytest.raises(ValueError, match="destination"):
        await dispatch(
            client, "pisama_n8n_choose_guardrail_destination",
            {"repair_id": 1, "destination": "nope"},
        )
    with pytest.raises(ValueError, match="alert_url"):
        await dispatch(
            client, "pisama_n8n_choose_guardrail_destination",
            {"repair_id": 1, "destination": "alert"},
        )
    with pytest.raises(ValueError, match="Unknown tool"):
        await dispatch(client, "pisama_n8n_apply", {})


async def test_unreachable_server_maps_cleanly():
    client = PisamaN8nMCPClient(base_url="http://127.0.0.1:9")  # nothing listens
    server = create_server(client)
    handler = server.request_handlers[type(_call_tool_request("x", {}))]
    res = await handler(_call_tool_request("pisama_n8n_operations_summary", {}))
    assert res.root.isError is True
    assert res.root.structuredContent["error"]["code"] == "upstream_unreachable"
    await client.aclose()


def _call_tool_request(name, arguments):
    from mcp.types import CallToolRequest, CallToolRequestParams

    return CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments),
    )


# -- shaping units ------------------------------------------------------------


def test_shape_trace_keeps_error_and_last_nodes():
    nodes = [{"name": f"n{i}", "status": "success"} for i in range(50)]
    nodes[40] = {"name": "n40", "status": "error"}
    trace = {"status": "error", "last_node": "n49", "node_count": 50, "nodes": nodes}
    shaped = shape_trace(trace, max_nodes=10)
    names = [n["name"] for n in shaped["nodes"]]
    assert "n40" in names and "n49" in names
    assert shaped["nodes_omitted"] == 50 - len(names)
    # Under the cap: untouched, no omission marker.
    assert "nodes_omitted" not in shape_trace(trace, max_nodes=100)


def test_shape_repair_summarizes_workflows_keeps_ids():
    repair = {
        "id": 7, "detection_id": 3, "status": "proposed",
        "guard_config": {"kind": "input_schema", "paths": ["a.b"]},
        "baseline_workflow": {"nodes": [{"name": "A"}, {"name": "B"}]},
        "proposed_workflow": {"nodes": [{"name": "A"}, {"name": "B"}, {"name": "Guard"}]},
        "patch_ops": [{"op": "x"}],
    }
    shaped = shape_repair(repair)
    assert shaped["id"] == 7 and shaped["detection_id"] == 3
    assert shaped["guard_config"]["paths"] == ["a.b"]
    assert "baseline_workflow" not in shaped and "patch_ops" not in shaped
    assert shaped["proposed_workflow_summary"] == {
        "node_count": 3, "node_names": ["A", "B", "Guard"]
    }
