"""Stdio MCP server: a REST proxy over this Pisama server's read + propose surface.

Lets an MCP client (Claude Code, Cursor, ...) interrogate detections, traces, and
reliability evidence, and stage repair PROPOSALS. The boundary is deliberate: apply,
rollback, outcomes, and verifications are operator actions in the dashboard —
proposing creates a repair row server-side and never writes to the live n8n.

Config is env-only so it drops into an mcpServers JSON block:
  PISAMA_SERVER_URL  base URL of a running Pisama-for-n8n server (default
                     http://localhost:8000)
  PISAMA_API_KEY     optional bearer; omit against a dev-mode server or a
                     PISAMA_PUBLIC_READ demo (reads work, proposes 401 clearly)

stdout is the JSON-RPC transport, so ALL logging goes to stderr.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

from .tools import TOOLS

logger = logging.getLogger("pisama_n8n_server.mcp")

DEFAULT_SERVER_URL = "http://localhost:8000"
# Evidence string leaves can embed full stack traces; repairs embed whole n8n
# workflow JSON. Caps keep tool results LLM-sized without dropping any id or enum a
# follow-up call needs (pinned by tests).
EVIDENCE_STR_CAP = 2000
NODE_NAMES_CAP = 30
ERROR_TARGETS_CAP = 100
DEFAULT_LIST_LIMIT = 20
DEFAULT_TRACE_NODES = 30
# Listing error targets does one live-n8n GET per candidate workflow.
ERROR_TARGETS_TIMEOUT = 60.0


class PisamaN8nMCPClient:
    """Async HTTP client for a Pisama-for-n8n server (OSS or SaaS).

    ``transport`` is the test seam: pass httpx.ASGITransport(app=...) to run the
    real FastAPI app in-process instead of mocking anything.
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._transport = transport
        self._client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"User-Agent": "pisama-n8n-mcp/0.1"}
            # No key -> no auth header: works against dev-mode servers and public-read
            # demos; an authenticated route then 401s with an actionable message.
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(30.0, connect=5.0),
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def get(self, path: str, timeout: Optional[float] = None) -> Any:
        client = await self._ensure_client()
        resp = await client.get(path, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    async def post(self, path: str, body: Dict[str, Any]) -> Any:
        client = await self._ensure_client()
        resp = await client.post(path, json=body)
        resp.raise_for_status()
        return resp.json()


# -- response shaping (pure; unit-tested) -------------------------------------


def _cap_strings(value: Any, cap: int = EVIDENCE_STR_CAP) -> Any:
    if isinstance(value, str) and len(value) > cap:
        return value[:cap] + "…[truncated]"
    if isinstance(value, dict):
        return {k: _cap_strings(v, cap) for k, v in value.items()}
    if isinstance(value, list):
        return [_cap_strings(v, cap) for v in value]
    return value


def shape_detection_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in row.items() if k not in ("evidence", "detector_version")}


def shape_detection_detail(row: Dict[str, Any]) -> Dict[str, Any]:
    return _cap_strings(row)


def shape_trace(trace: Dict[str, Any], max_nodes: int) -> Dict[str, Any]:
    nodes = trace.get("nodes") or []
    if len(nodes) <= max_nodes:
        return trace
    last_node = trace.get("last_node")
    # Keep every error node and the last-executed node; fill the remainder in
    # recorded order so the shape stays chronological.
    must_keep = {
        i for i, n in enumerate(nodes)
        if n.get("status") == "error" or n.get("name") == last_node
    }
    kept: List[int] = sorted(must_keep)
    for i in range(len(nodes)):
        if len(kept) >= max(max_nodes, len(must_keep)):
            break
        if i not in must_keep:
            kept.append(i)
    kept = sorted(set(kept))
    shaped = dict(trace)
    shaped["nodes"] = [nodes[i] for i in kept]
    shaped["nodes_omitted"] = len(nodes) - len(kept)
    return shaped


def _workflow_summary(workflow: Any) -> Dict[str, Any]:
    nodes = (workflow or {}).get("nodes") or []
    names = [n.get("name") for n in nodes][:NODE_NAMES_CAP]
    return {"node_count": len(nodes), "node_names": names}


def shape_repair(repair: Dict[str, Any]) -> Dict[str, Any]:
    """Replace embedded n8n workflow bodies (tens of KB) with summaries.

    Everything a follow-up tool call needs — the repair id, detection_id, status,
    and guard_config (paths, destination, target ids) — passes through untouched.
    """
    shaped = {
        k: v
        for k, v in repair.items()
        if k not in ("baseline_workflow", "proposed_workflow", "snapshot",
                     "applied_workflow", "patch_ops")
    }
    if "baseline_workflow" in repair:
        shaped["baseline_workflow_summary"] = _workflow_summary(repair["baseline_workflow"])
    if "proposed_workflow" in repair:
        shaped["proposed_workflow_summary"] = _workflow_summary(repair["proposed_workflow"])
    return shaped


# -- dispatch -----------------------------------------------------------------


def _require_int(args: Dict[str, Any], key: str) -> int:
    value = args.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"'{key}' must be a positive integer.")
    return value


def _optional_limit(args: Dict[str, Any], default: int) -> int:
    value = args.get("limit", default)
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 100:
        raise ValueError("'limit' must be an integer between 1 and 100.")
    return value


async def dispatch(client: PisamaN8nMCPClient, name: str, args: Dict[str, Any]) -> Any:
    if name == "pisama_n8n_list_detections":
        limit = _optional_limit(args, DEFAULT_LIST_LIMIT)
        rows = await client.get("/api/v1/detections")
        # The route has no query params; filters are client-side by design (v1).
        if args.get("detected_only", True):
            rows = [r for r in rows if r.get("detected")]
        for key in ("detector", "failure_mode", "workflow_id"):
            if args.get(key) is not None:
                rows = [r for r in rows if r.get(key) == args[key]]
        newest_first = sorted(rows, key=lambda r: r.get("id", 0), reverse=True)
        return {
            "total_matching": len(newest_first),
            "returned": min(limit, len(newest_first)),
            "detections": [shape_detection_summary(r) for r in newest_first[:limit]],
        }

    if name == "pisama_n8n_get_detection":
        det_id = _require_int(args, "detection_id")
        return shape_detection_detail(await client.get(f"/api/v1/detections/{det_id}"))

    if name == "pisama_n8n_get_detection_trace":
        det_id = _require_int(args, "detection_id")
        max_nodes = args.get("max_nodes", DEFAULT_TRACE_NODES)
        if not isinstance(max_nodes, int) or isinstance(max_nodes, bool) or not 1 <= max_nodes <= 200:
            raise ValueError("'max_nodes' must be an integer between 1 and 200.")
        return shape_trace(await client.get(f"/api/v1/detections/{det_id}/trace"), max_nodes)

    if name == "pisama_n8n_operations_summary":
        return await client.get("/api/v1/operations/summary")

    if name == "pisama_n8n_list_reliability_cases":
        limit = _optional_limit(args, DEFAULT_LIST_LIMIT)
        cases = await client.get("/api/v1/reliability-cases")
        if args.get("status") is not None:
            cases = [c for c in cases if c.get("status") == args["status"]]
        return {
            "total_matching": len(cases),
            "returned": min(limit, len(cases)),
            "cases": cases[:limit],
        }

    if name == "pisama_n8n_list_error_route_targets":
        repair_id = _require_int(args, "repair_id")
        result = await client.get(
            f"/api/v1/n8n/repairs/{repair_id}/error-targets",
            timeout=ERROR_TARGETS_TIMEOUT,
        )
        targets = result.get("targets") or []
        if len(targets) > ERROR_TARGETS_CAP:
            result = dict(result)
            result["targets"] = targets[:ERROR_TARGETS_CAP]
            result["targets_omitted"] = len(targets) - ERROR_TARGETS_CAP
        return result

    if name == "pisama_n8n_propose_guardrail":
        det_id = _require_int(args, "detection_id")
        body: Dict[str, Any] = {"detection_id": det_id}
        if args.get("paths") is not None:
            paths = args["paths"]
            if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
                raise ValueError("'paths' must be an array of strings.")
            body["paths"] = paths
        result = await client.post("/api/v1/n8n/guardrail", body)
        return {
            "repair": shape_repair(result.get("repair") or {}),
            # The decision surface for the next step — passed through verbatim.
            "path_options": result.get("path_options"),
            "destinations": result.get("destinations"),
        }

    if name == "pisama_n8n_choose_guardrail_destination":
        repair_id = _require_int(args, "repair_id")
        destination = args.get("destination")
        if destination not in ("error_workflow", "alert", "respond_422"):
            raise ValueError(
                "'destination' must be one of: error_workflow, alert, respond_422."
            )
        body = {"destination": destination}
        if destination == "alert":
            alert_url = args.get("alert_url")
            if not isinstance(alert_url, str) or not alert_url.startswith(("http://", "https://")):
                raise ValueError("'alert_url' (http/https URL) is required when destination is 'alert'.")
            body["alert_url"] = alert_url
        result = await client.post(f"/api/v1/n8n/repairs/{repair_id}/destination", body)
        return {"repair": shape_repair(result.get("repair") or {})}

    if name == "pisama_n8n_propose_error_route":
        det_id = _require_int(args, "detection_id")
        result = await client.post("/api/v1/n8n/error-route", {"detection_id": det_id})
        return {
            "repair": shape_repair(result.get("repair") or {}),
            "next_step": "pisama_n8n_list_error_route_targets with this repair id",
        }

    if name == "pisama_n8n_choose_error_route_target":
        repair_id = _require_int(args, "repair_id")
        target = args.get("target_workflow_id")
        if not isinstance(target, str) or not target:
            raise ValueError("'target_workflow_id' must be a non-empty string.")
        result = await client.post(
            f"/api/v1/n8n/repairs/{repair_id}/error-target",
            {"target_workflow_id": target},
        )
        return {"repair": shape_repair(result.get("repair") or {})}

    raise ValueError(f"Unknown tool: {name!r}")


# -- MCP wiring ---------------------------------------------------------------


def _success(result: Any) -> CallToolResult:
    text = json.dumps(result, indent=2, default=str) if isinstance(result, (dict, list)) else str(result)
    structured = result if isinstance(result, dict) else (
        {"items": result} if isinstance(result, list) else None
    )
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structuredContent=structured,
        isError=False,
    )


def _error(code: str, message: str, *, detail: Any = None,
           status_code: Optional[int] = None) -> CallToolResult:
    structured: Dict[str, Any] = {"error": {"code": code, "message": message}}
    if detail is not None:
        structured["error"]["detail"] = detail
    if status_code is not None:
        structured["error"]["status_code"] = status_code
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        structuredContent=structured,
        isError=True,
    )


def create_server(client: PisamaN8nMCPClient) -> Server:
    server: Server = Server("pisama-n8n")

    @server.list_tools()
    async def list_tools() -> List[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: Dict[str, Any]) -> CallToolResult:
        # Tool-execution failures return isError=true (not JSON-RPC errors) so the
        # calling LLM sees the failure and can react.
        try:
            return _success(await dispatch(client, name, arguments or {}))
        except ValueError as exc:
            return _error("validation_error", f"Validation error: {exc}", detail=str(exc))
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            try:
                detail = exc.response.json().get("detail")
            except Exception:
                detail = exc.response.text
            message = f"Pisama server returned {status}: {detail}"
            if status == 401:
                message += " (set PISAMA_API_KEY to match the server's key)"
            return _error("upstream_http_error", message, detail=detail, status_code=status)
        except httpx.RequestError as exc:
            return _error(
                "upstream_unreachable",
                f"Could not reach the Pisama server at {client.base_url} — is it running?",
                detail=str(exc),
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected error in tool %s", name)
            return _error("internal_error", "Internal MCP server error", detail=str(exc))

    return server


async def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Pisama-for-n8n MCP server (stdio)")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)
    logging.basicConfig(stream=sys.stderr, level=args.log_level.upper())

    client = PisamaN8nMCPClient(
        base_url=os.environ.get("PISAMA_SERVER_URL", DEFAULT_SERVER_URL),
        api_key=os.environ.get("PISAMA_API_KEY") or None,
    )
    server = create_server(client)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
