#!/usr/bin/env python3
"""Prepare the real guardrail evidence used by the image-led promo cut."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]


def response_data(response: httpx.Response) -> object:
    response.raise_for_status()
    payload = response.json()
    return payload.get("data", payload)


def provision(args: argparse.Namespace) -> int:
    browser_id = str(uuid.uuid4())
    headers = {
        "browser-id": browser_id,
        "Origin": args.n8n_url,
        "Referer": f"{args.n8n_url}/",
    }
    with httpx.Client(base_url=args.n8n_url, headers=headers, timeout=30) as client:
        login = client.post(
            "/rest/login",
            json={
                "emailOrLdapLoginId": args.email,
                "password": args.password,
            },
        )
        login.raise_for_status()

        existing = response_data(client.get("/rest/api-keys"))
        rows = existing.get("items", []) if isinstance(existing, dict) else existing
        for row in rows or []:
            if row.get("label") == "pisama-video-guardrail" and row.get("id"):
                client.delete(f"/rest/api-keys/{row['id']}").raise_for_status()

        scopes = response_data(client.get("/rest/api-keys/scopes"))
        created = response_data(
            client.post(
                "/rest/api-keys",
                json={
                    "label": "pisama-video-guardrail",
                    "expiresAt": None,
                    "scopes": scopes,
                },
            )
        )
        key = created.get("rawApiKey") or created.get("apiKey")
        if not key:
            raise RuntimeError("n8n did not return a usable API key")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(key, encoding="utf-8")
    output.chmod(0o600)
    print(json.dumps({"api_key_file": str(output), "status": "ready"}))
    return 0


def runtime_env(args: argparse.Namespace) -> dict[str, str]:
    env = dict(os.environ)
    pisama_api_key = env.get("PISAMA_API_KEY")
    if not pisama_api_key:
        raise RuntimeError("Set PISAMA_API_KEY before starting the guardrail demo")
    env.update(
        {
            "PYTHONPATH": f"{ROOT / 'engine'}:{ROOT / 'server'}",
            "DATABASE_URL": f"sqlite:///{Path(args.state_dir) / 'guardrail.db'}",
            "PISAMA_API_KEY": pisama_api_key,
            "PISAMA_N8N_URL": args.n8n_url,
            "PISAMA_N8N_API_KEY": Path(args.api_key_file)
            .read_text(encoding="utf-8")
            .strip(),
        }
    )
    return env


def serve(args: argparse.Namespace) -> int:
    Path(args.state_dir).mkdir(parents=True, exist_ok=True)
    env = runtime_env(args)
    os.environ.update(env)
    sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "server")]
    import uvicorn

    uvicorn.run(
        "pisama_n8n_server.app:app",
        host="127.0.0.1",
        port=args.server_port,
        log_level="warning",
    )
    return 0


def lifecycle(args: argparse.Namespace) -> int:
    env = runtime_env(args)
    env["PISAMA_SERVER_URL"] = f"http://127.0.0.1:{args.server_port}"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_guardrail_lifecycle.py")],
        cwd=ROOT,
        env=env,
        check=False,
    )
    return result.returncode


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)

    create = commands.add_parser("provision")
    create.add_argument("--n8n-url", default="http://127.0.0.1:5701")
    create.add_argument("--email", default="demo@pisama.local")
    create.add_argument("--password", required=True)
    create.add_argument("--output", required=True)
    create.set_defaults(handler=provision)

    for name, handler in (("serve", serve), ("lifecycle", lifecycle)):
        command = commands.add_parser(name)
        command.add_argument("--n8n-url", default="http://127.0.0.1:5701")
        command.add_argument("--api-key-file", required=True)
        command.add_argument("--state-dir", required=True)
        command.add_argument("--server-port", type=int, default=8511)
        command.set_defaults(handler=handler)
    return result


def main() -> int:
    args = parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
