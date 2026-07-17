#!/usr/bin/env python3
"""Exercise a real n8n SQLite upgrade, restore, and Pisama polling gate.

The gate owns uniquely named Docker Compose projects and volumes. It never reads an
operator's n8n instance, accepts no customer payloads, and emits only a redacted JSON
manifest. A successful run proves this exact path with real n8n executions:

1. n8n 1.70.0 creates and runs a controlled failing webhook;
2. its complete SQLite volume is copied to an isolated backup volume;
3. n8n 1.91.3 starts against the original volume and runs the same workflow again;
4. another 1.91.3 project restores the backup and runs the workflow again;
5. the current Pisama server polls both target lanes, persists a finding, and dedups.

Run from the repository root, or invoke it from any directory:

    python scripts/verify_n8n_upgrade_restore.py

Docker, Docker Compose, and the ``busybox:1.36`` image are required. The latter is used
only to copy and hash named Docker volumes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "deploy" / "docker-compose.dogfood.yml"
COPY_IMAGE = "busybox:1.36"
OWNER_PASSWORD = "PisamaUpgradeGate123!"


@dataclass(frozen=True)
class Lane:
    """One isolated n8n/Pisama Compose project used by this gate."""

    project: str
    n8n_port: int
    server_port: int

    @property
    def n8n_url(self) -> str:
        return f"http://127.0.0.1:{self.n8n_port}"

    @property
    def server_url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"

    @property
    def n8n_volume(self) -> str:
        return f"{self.project}_dogfood_n8n_config"


class HttpJson:
    """Small JSON client that keeps n8n's setup/login cookie private in memory."""

    def __init__(self, base_url: str, cookies: bool = False):
        self.base_url = base_url.rstrip("/")
        self._capture_cookies = cookies
        self._session_cookie: Optional[str] = None

    def has_cookie(self, name: str) -> bool:
        return bool(self._session_cookie and self._session_cookie.startswith(f"{name}="))

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        query: Optional[Dict[str, str]] = None,
        api_key: Optional[str] = None,
        expected: Iterable[int] = (200,),
    ) -> Tuple[int, Any]:
        url = self.base_url + path
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        if api_key:
            headers["X-N8N-API-KEY"] = api_key
        if self._session_cookie:
            headers["Cookie"] = self._session_cookie
        request = Request(url, data=data, headers=headers, method=method)
        try:
            response = self._open(request)
            self._capture_session_cookie(response)
            status, body = response.status, response.read()
        except HTTPError as exc:
            status, body = exc.code, exc.read()
        if status not in set(expected):
            detail = body.decode("utf-8", "replace")[:300]
            raise RuntimeError(f"{method} {path} returned HTTP {status}: {detail}")
        return status, _json_or_empty(body)

    def _open(self, request: Request):
        try:
            return urlopen(request, timeout=20)
        except HTTPError:
            raise
        except URLError as exc:
            raise RuntimeError(f"Could not reach {request.full_url}: {exc.reason}") from exc

    def _capture_session_cookie(self, response: Any) -> None:
        if not self._capture_cookies:
            return
        for header in response.headers.get_all("Set-Cookie", []):
            cookie = header.partition(";")[0]
            if cookie.startswith("n8n-auth="):
                self._session_cookie = cookie
                return


def _json_or_empty(body: bytes) -> Any:
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"non_json_response": body.decode("utf-8", "replace")[:300]}


def _unwrap(payload: Any) -> Any:
    return payload.get("data", payload) if isinstance(payload, dict) else payload


def _run(args: Sequence[str], env: Optional[Dict[str, str]] = None) -> str:
    """Run Docker/Git without putting secrets in a command line or error output."""
    process = subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode:
        detail = process.stderr.strip()[-500:]
        raise RuntimeError(f"{' '.join(args)} failed: {detail}")
    return process.stdout.strip()


def _compose(lane: Lane, env: Dict[str, str], *args: str) -> str:
    return _run(
        ["docker", "compose", "-p", lane.project, "-f", str(COMPOSE_FILE), *args],
        env,
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _n8n_environment(version: str, lane: Lane) -> Dict[str, str]:
    """Build an environment for a local lane without Cloud project scoping."""
    environment = os.environ.copy()
    # The Cloud corpus uses an isolated n8n project. Its filter is invalid for
    # this freshly provisioned local n8n instance and must never leak into the
    # upgrade/restore server's polling configuration.
    environment.pop("PISAMA_N8N_PROJECT_ID", None)
    environment.pop("PISAMA_DOGFOOD_N8N_PROJECT_ID", None)
    environment.update(
        {
            "N8N_VERSION": version,
            "PISAMA_DOGFOOD_N8N_PORT": str(lane.n8n_port),
        }
    )
    return environment


def _wait_for_json(url: str, timeout_seconds: int = 90) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=5) as response:
                payload = _json_or_empty(response.read())
            if isinstance(payload, dict):
                return payload
            last_error = f"unexpected payload {type(payload).__name__}"
        except (HTTPError, OSError, URLError, RuntimeError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def _start_n8n(lane: Lane, version: str) -> None:
    environment = _n8n_environment(version, lane)
    _compose(lane, environment, "up", "-d", "n8n")
    health = _wait_for_json(f"{lane.n8n_url}/healthz")
    if health.get("status") != "ok":
        raise RuntimeError(f"n8n health check was not ok: {health}")


def _login(client: HttpJson, email: str) -> None:
    for field in ("email", "emailOrLdapLoginId"):
        status, _ = client.request(
            "POST",
            "/rest/login",
            payload={field: email, "password": OWNER_PASSWORD},
            expected=(200, 400, 401),
        )
        if status == 200 and client.has_cookie("n8n-auth"):
            return
    raise RuntimeError("n8n owner login did not establish an n8n-auth session cookie")


def _setup_owner(client: HttpJson, email: str) -> bool:
    """Wait for n8n's REST controllers after its earlier health endpoint is ready."""
    deadline = time.monotonic() + 30
    payload = {
        "email": email,
        "firstName": "Pisama",
        "lastName": "Upgrade",
        "password": OWNER_PASSWORD,
    }
    while time.monotonic() < deadline:
        status, _ = client.request(
            "POST",
            "/rest/owner/setup",
            payload=payload,
            expected=(200, 201, 400, 404),
        )
        if status == 400:
            return False
        if status != 404 and client.has_cookie("n8n-auth"):
            return True
        time.sleep(1)
    raise RuntimeError("n8n REST owner-setup endpoint did not become ready")


def _provision_api_key(
    lane: Lane, run_id: str, owner_email: Optional[str] = None
) -> str:
    """Create a short-lived n8n key in a fresh, internal n8n instance."""
    client = HttpJson(lane.n8n_url, cookies=True)
    email = owner_email or f"upgrade-{run_id}@pisama.test"
    _setup_owner(client, email)
    # Fresh n8n instances issue an authenticated cookie from owner setup. Older
    # releases can require a separate login, so only make that second request when
    # setup did not provide the session.
    if not client.has_cookie("n8n-auth"):
        _login(client, email)
    scope_status, scope_payload = client.request(
        "GET", "/rest/api-keys/scopes", expected=(200, 404)
    )
    scopes = _api_key_scopes(scope_status, scope_payload)
    key_payload = {"label": f"upgrade-gate-{run_id}", "expiresAt": int(time.time()) + 3600}
    if scopes:
        key_payload["scopes"] = scopes
    _, key_payload = client.request(
        "POST",
        "/rest/api-keys",
        payload=key_payload,
        expected=(200, 201),
    )
    key_data = _unwrap(key_payload)
    api_key = key_data.get("rawApiKey") or key_data.get("apiKey")
    if not isinstance(api_key, str) or not api_key:
        raise RuntimeError("n8n did not return a one-time API key")
    return api_key


def _api_key_scopes(status: int, payload: Any) -> list[str]:
    """Use scoped keys where n8n supports them, with 1.70's legacy fallback."""
    if status != 200:
        return []
    values = _unwrap(payload)
    return [
        scope
        for scope in values
        if isinstance(scope, str)
        and scope.startswith(("workflow:", "execution:"))
    ]


def _failure_workflow(path: str, name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "settings": {},
        "nodes": [
            {
                "id": "webhook",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "typeVersion": 2,
                "position": [0, 0],
                "parameters": {
                    "path": path,
                    "httpMethod": "POST",
                    "responseMode": "lastNode",
                },
                "webhookId": path,
            },
            {
                "id": "controlled-failure",
                "name": "Controlled failure",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "position": [240, 0],
                "parameters": {
                    "jsCode": "throw new Error('controlled upgrade restore failure');"
                },
            },
        ],
        "connections": {
            "Webhook": {
                "main": [
                    [{"node": "Controlled failure", "type": "main", "index": 0}]
                ]
            }
        },
    }


def _create_failure_workflow(lane: Lane, api_key: str, run_id: str) -> Tuple[str, str]:
    client = HttpJson(lane.n8n_url)
    path = f"upgrade-restore-{run_id}"
    _, payload = client.request(
        "POST",
        "/api/v1/workflows",
        payload=_failure_workflow(path, f"Pisama upgrade restore {run_id}"),
        api_key=api_key,
        expected=(200, 201),
    )
    workflow = _unwrap(payload)
    workflow_id = workflow.get("id") if isinstance(workflow, dict) else None
    if not isinstance(workflow_id, str) or not workflow_id:
        raise RuntimeError("n8n did not return a workflow ID")
    client.request(
        "POST",
        f"/api/v1/workflows/{workflow_id}/activate",
        api_key=api_key,
        expected=(200, 201),
    )
    return workflow_id, path


def _execution_ids(lane: Lane, api_key: str, workflow_id: str) -> Set[str]:
    client = HttpJson(lane.n8n_url)
    _, payload = client.request(
        "GET",
        "/api/v1/executions",
        query={"workflowId": workflow_id, "includeData": "false"},
        api_key=api_key,
    )
    executions = _unwrap(payload)
    if isinstance(executions, dict):
        executions = executions.get("data", [])
    return {
        str(execution["id"])
        for execution in executions
        if isinstance(execution, dict) and execution.get("id") is not None
    }


def _assert_active_workflow(lane: Lane, api_key: str, workflow_id: str) -> None:
    _, payload = HttpJson(lane.n8n_url).request(
        "GET", f"/api/v1/workflows/{workflow_id}", api_key=api_key
    )
    workflow = _unwrap(payload)
    if not isinstance(workflow, dict) or not workflow.get("active"):
        raise RuntimeError("controlled workflow was not retained as active")


def _run_failure(
    lane: Lane, api_key: str, workflow_id: str, path: str
) -> str:
    before = _execution_ids(lane, api_key, workflow_id)
    HttpJson(lane.n8n_url).request(
        "POST", f"/webhook/{path}", payload={}, expected=(500,)
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        observed = _execution_ids(lane, api_key, workflow_id) - before
        if observed:
            return sorted(observed)[-1]
        time.sleep(0.5)
    raise RuntimeError("n8n did not retain the controlled failure execution")


def _copy_volume(source: str, target: str) -> None:
    _run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{source}:/source:ro",
            "-v",
            f"{target}:/target",
            COPY_IMAGE,
            "sh",
            "-c",
            "cd /source && tar -cf - . | tar -xf - -C /target",
        ]
    )


def _volume_sha256(volume: str) -> str:
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{volume}:/data:ro",
        COPY_IMAGE,
        "sh",
        "-c",
        "cd /data && tar -cf - .",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    digest = hashlib.sha256()
    assert process.stdout is not None
    for chunk in iter(lambda: process.stdout.read(1024 * 1024), b""):
        digest.update(chunk)
    stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
    if process.wait() != 0:
        raise RuntimeError(f"could not hash backup volume: {stderr[-300:]}")
    return digest.hexdigest()


def _image_identity(version: str) -> Dict[str, Optional[str]]:
    image = f"n8nio/n8n:{version}"
    image_id = _run(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
    digests = _run(
        ["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"]
    )
    parsed = json.loads(digests)
    return {"tag": image, "image_id": image_id, "repo_digest": next(iter(parsed), None)}


def _start_pisama(
    lane: Lane, n8n_key: str, revision: str, n8n_version: str
) -> str:
    server_key = f"upgrade-gate-{uuid.uuid4().hex}"
    environment = _n8n_environment(n8n_version, lane)
    environment.update(
        {
            "PISAMA_DOGFOOD_SERVER_PORT": str(lane.server_port),
            "PISAMA_DOGFOOD_N8N_URL": f"http://host.docker.internal:{lane.n8n_port}",
            "PISAMA_DOGFOOD_N8N_API_KEY": n8n_key,
            "PISAMA_DOGFOOD_API_KEY": server_key,
            "PISAMA_DOGFOOD_POLL_INTERVAL": "0",
            "PISAMA_DOGFOOD_N8N_PROJECT_ID": "",
            "PISAMA_BUILD_REVISION": revision,
        }
    )
    _compose(
        lane,
        environment,
        "--profile",
        "server",
        "up",
        "-d",
        "--build",
        "--no-deps",
        "server",
    )
    health = _wait_for_json(f"{lane.server_url}/healthz")
    if health.get("status") != "ok":
        raise RuntimeError(f"Pisama health check was not ok: {health}")
    return server_key


def _verify_pisama(
    lane: Lane, server_key: str, workflow_id: str
) -> Dict[str, Any]:
    client = HttpJson(lane.server_url)
    auth = {"Authorization": f"Bearer {server_key}"}
    # The small client speaks n8n headers by default; use an endpoint-local request
    # for Pisama's bearer header without exposing the key in a subprocess command.
    initial = _pisama_request(client, "POST", "/api/v1/n8n/sync", auth)
    detections = _pisama_request(client, "GET", "/api/v1/detections", auth)
    fired = sorted(
        {
            str(row.get("detector"))
            for row in detections
            if isinstance(row, dict)
            and row.get("workflow_id") == workflow_id
            and row.get("detected")
        }
    )
    if "error" not in fired:
        raise RuntimeError("Pisama did not persist the controlled n8n error finding")
    second = _pisama_request(client, "POST", "/api/v1/n8n/sync", auth)
    if not isinstance(second, dict) or second.get("new") != 0:
        raise RuntimeError("Pisama did not deduplicate the second polling sync")
    return {
        "initial_sync_new": initial.get("new") if isinstance(initial, dict) else None,
        "second_sync_new": second.get("new"),
        "fired_detectors": fired,
    }


def _pisama_request(
    client: HttpJson, method: str, path: str, headers: Dict[str, str]
) -> Any:
    request = Request(
        client.base_url + path,
        headers={"Accept": "application/json", **headers},
        method=method,
    )
    try:
        with urlopen(request, timeout=30) as response:
            return _json_or_empty(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc


def _git_revision() -> str:
    try:
        return _run(["git", "rev-parse", "--short", "HEAD"])
    except RuntimeError:
        return "upgrade-restore-gate"


def _cleanup(lanes: Iterable[Lane], backup_volume: str) -> None:
    for lane in lanes:
        environment = os.environ.copy()
        environment.update(
            {
                "PISAMA_DOGFOOD_N8N_PORT": str(lane.n8n_port),
                "PISAMA_DOGFOOD_SERVER_PORT": str(lane.server_port),
            }
        )
        try:
            _compose(
                lane,
                environment,
                "--profile",
                "server",
                "down",
                "-v",
                "--remove-orphans",
            )
        except RuntimeError:
            for container in (
                f"{lane.project}-server-1",
                f"{lane.project}-n8n-1",
            ):
                try:
                    _run(["docker", "rm", "-f", container])
                except RuntimeError:
                    pass
            for volume in (
                lane.n8n_volume,
                f"{lane.project}_dogfood_pisama_data",
            ):
                try:
                    _run(["docker", "volume", "rm", "-f", volume])
                except RuntimeError:
                    pass
            try:
                _run(["docker", "network", "rm", f"{lane.project}_default"])
            except RuntimeError:
                pass
    try:
        _run(["docker", "volume", "rm", "-f", backup_volume])
    except RuntimeError:
        pass


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-version", default="1.70.0")
    parser.add_argument("--target-version", default="1.91.3")
    parser.add_argument(
        "--keep", action="store_true", help="Keep the uniquely named Docker lanes"
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    token = uuid.uuid4().hex[:10]
    source = Lane(f"pisama-n8n-upgrade-{token}", _free_port(), _free_port())
    restored = Lane(f"pisama-n8n-restore-{token}", _free_port(), _free_port())
    backup_volume = f"pisama-n8n-backup-{token}"
    revision = _git_revision()
    manifest: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source_version": args.source_version,
        "target_version": args.target_version,
        "lanes": {"upgraded": asdict(source), "restored": asdict(restored)},
    }
    owner_email = f"upgrade-{token}@pisama.test"
    try:
        _start_n8n(source, args.source_version)
        source_key = _provision_api_key(source, token, owner_email)
        workflow_id, webhook_path = _create_failure_workflow(source, source_key, token)
        source_execution = _run_failure(source, source_key, workflow_id, webhook_path)
        _run(["docker", "volume", "create", backup_volume])
        _copy_volume(source.n8n_volume, backup_volume)
        manifest["backup_sha256"] = _volume_sha256(backup_volume)
        _compose(source, _n8n_environment(args.source_version, source), "stop", "n8n")
        _start_n8n(source, args.target_version)
        upgraded_key = _provision_api_key(
            source, f"{token}-upgraded", owner_email
        )
        _assert_active_workflow(source, upgraded_key, workflow_id)
        upgraded_execution = _run_failure(
            source, upgraded_key, workflow_id, webhook_path
        )
        upgraded_server_key = _start_pisama(
            source, upgraded_key, revision, args.target_version
        )
        manifest["upgraded"] = {
            "workflow_id": workflow_id,
            "source_execution_id": source_execution,
            "target_execution_id": upgraded_execution,
            "pisama": _verify_pisama(source, upgraded_server_key, workflow_id),
        }
        restore_env = _n8n_environment(args.target_version, restored)
        _compose(restored, restore_env, "create", "n8n")
        _copy_volume(backup_volume, restored.n8n_volume)
        _start_n8n(restored, args.target_version)
        restored_key = _provision_api_key(
            restored, f"{token}-restored", owner_email
        )
        _assert_active_workflow(restored, restored_key, workflow_id)
        restored_execution = _run_failure(
            restored, restored_key, workflow_id, webhook_path
        )
        restored_server_key = _start_pisama(
            restored, restored_key, revision, args.target_version
        )
        manifest["restored"] = {
            "workflow_id": workflow_id,
            "target_execution_id": restored_execution,
            "pisama": _verify_pisama(restored, restored_server_key, workflow_id),
        }
        manifest["images"] = {
            "source": _image_identity(args.source_version),
            "target": _image_identity(args.target_version),
        }
        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        manifest["passed"] = True
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    except RuntimeError as exc:
        print(f"n8n upgrade/restore gate failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if not args.keep:
            _cleanup((source, restored), backup_volume)


if __name__ == "__main__":
    raise SystemExit(main())
