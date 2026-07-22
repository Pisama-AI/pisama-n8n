"""End-to-end MCP smoke: real uvicorn + real SQLite + real stdio JSON-RPC.

No mocks anywhere in the chain: a genuine Pisama server subprocess analyzes a real
recorded n8n execution, and the MCP server subprocess is driven over its actual
stdio transport exactly as Claude Code/Cursor would. This is the test that catches
SDK serialization drift (e.g. CallToolResult wrapping changes) that in-process
handler tests cannot see.
"""

from __future__ import annotations

import json
import os
import select
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

pytest.importorskip("mcp")
import httpx  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
API_KEY = "smoke-key"

_ID = 0


def _next_id() -> int:
    global _ID
    _ID += 1
    return _ID


def _jsonrpc(method: str, params: Optional[Dict[str, Any]] = None) -> bytes:
    msg: Dict[str, Any] = {"jsonrpc": "2.0", "id": _next_id(), "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg).encode() + b"\n"


def _read_responses(proc: subprocess.Popen, timeout: float = 15.0) -> List[dict]:
    """Read newline-delimited JSON-RPC responses from the child's stdout."""
    responses: List[dict] = []
    deadline = time.monotonic() + timeout
    buf = b""
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        ready, _, _ = select.select([proc.stdout], [], [], min(max(remaining, 0), 0.5))
        if not ready:
            if responses:
                break
            continue
        chunk = proc.stdout.read1(65536)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if line:
                responses.append(json.loads(line))
        if responses and not buf:
            break
    return responses


class McpStdioClient:
    def __init__(self, env: Dict[str, str]) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "pisama_n8n_server.mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,  # read only on failure; keeps stdout clean
            env=env,
        )
        self._send(_jsonrpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pisama-n8n-smoke", "version": "0"},
        }))
        assert self._recv(), self._stderr_tail()
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode() + b"\n"
        )
        self.proc.stdin.flush()
        time.sleep(0.2)

    def _send(self, data: bytes) -> None:
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def _recv(self, timeout: float = 15.0) -> List[dict]:
        return _read_responses(self.proc, timeout=timeout)

    def _stderr_tail(self) -> str:
        if self.proc.poll() is None:
            return "child alive but silent"
        return (self.proc.stderr.read() or b"").decode(errors="replace")[-2000:]

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> dict:
        self._send(_jsonrpc(method, params))
        for resp in reversed(self._recv()):
            if "result" in resp or "error" in resp:
                return resp
        raise TimeoutError(f"No response for {method}; stderr: {self._stderr_tail()}")

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    """A real Pisama server (uvicorn subprocess, SQLite) seeded with one detection,
    plus an MCP stdio subprocess pointed at it."""
    tmp = tmp_path_factory.mktemp("mcp-smoke")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    env = {**os.environ,
           "DATABASE_URL": f"sqlite:///{tmp}/smoke.db",
           "PISAMA_API_KEY": API_KEY}
    env.pop("PISAMA_POLL_INTERVAL", None)  # single writer; no background poller
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "pisama_n8n_server.app:app",
         "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env,
    )
    try:
        for _ in range(50):
            try:
                if httpx.get(f"{base}/healthz", timeout=1).status_code == 200:
                    break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError(
                "server never became healthy: "
                + (server.stderr.read() or b"").decode(errors="replace")[-2000:]
            )

        fx = json.loads(
            (FIXTURES / "executions/data_contract/CLOUD-112117-missing-required-value.json").read_text()
        )
        headers = {"Authorization": f"Bearer {API_KEY}"}
        httpx.post(f"{base}/api/v1/n8n/webhook", headers=headers, json=fx, timeout=30)
        rows = httpx.get(f"{base}/api/v1/detections", headers=headers, timeout=10).json()
        det_id = next(
            r["id"] for r in rows
            if r["detector"] == "schema" and r["failure_mode"] == "n8n_data_contract"
        )

        mcp_client = McpStdioClient(
            {**os.environ, "PISAMA_SERVER_URL": base, "PISAMA_API_KEY": API_KEY}
        )
        yield mcp_client, det_id
        mcp_client.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


def test_tools_list_is_the_ten_tool_surface(stack):
    mcp_client, _ = stack
    resp = mcp_client.call("tools/list")
    names = sorted(t["name"] for t in resp["result"]["tools"])
    assert len(names) == 10
    assert names[0].startswith("pisama_n8n_")
    assert not any("apply" in n or "rollback" in n for n in names)


def test_list_detections_sees_the_seeded_row(stack):
    mcp_client, det_id = stack
    resp = mcp_client.call(
        "tools/call",
        {"name": "pisama_n8n_list_detections", "arguments": {"failure_mode": "n8n_data_contract"}},
    )
    result = resp["result"]
    assert result.get("isError") is not True, result
    detections = result["structuredContent"]["detections"]
    assert any(d["id"] == det_id for d in detections)
    assert all("evidence" not in d for d in detections)


def test_propose_guardrail_end_to_end(stack):
    mcp_client, det_id = stack
    resp = mcp_client.call(
        "tools/call",
        {"name": "pisama_n8n_propose_guardrail", "arguments": {"detection_id": det_id}},
    )
    result = resp["result"]
    assert result.get("isError") is not True, result
    body = result["structuredContent"]
    assert body["path_options"]["confirmed"] == ["required.value"]
    assert isinstance(body["repair"]["id"], int)
    # Workflow bodies must not cross the MCP boundary (token economy invariant).
    assert "baseline_workflow" not in body["repair"]
    assert "nodes" not in json.dumps(body["repair"].get("baseline_workflow_summary", {}))


def test_unknown_tool_yields_error_result_not_crash(stack):
    mcp_client, _ = stack
    resp = mcp_client.call(
        "tools/call", {"name": "pisama_n8n_apply", "arguments": {}}
    )
    # Either an isError tool result or a JSON-RPC error is acceptable; a hung or
    # dead child is not — and a follow-up call must still work.
    assert ("error" in resp) or resp["result"].get("isError") is True
    again = mcp_client.call("tools/list")
    assert len(again["result"]["tools"]) == 10
