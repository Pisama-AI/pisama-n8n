"""No-mocks tests for the community node's HMAC webhook auth.

Signs real payloads exactly like the PUBLISHED n8n-nodes-pisama v0.3.0 does
(contract read from the npm tarball's dist, not a local checkout):
"sha256=" + hex(HMAC-SHA256(secret, "{timestamp}.{body}")) in
X-Pisama-Signature, with X-Pisama-Timestamp and X-Pisama-Nonce headers (the
nonce is sent but is NOT in the signature base), plus X-Pisama-API-Key always
carrying the node's apiKey credential. Posts go through the real app + engine
+ SQLite.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Dict

import pytest
from fastapi.testclient import TestClient

from pisama_n8n_server.app import app, get_storage
from pisama_n8n_server.storage import Storage

FIXTURES = Path(__file__).parent / "fixtures"

API_KEY = "s3cret-api-key"


def _load(rel: str) -> dict:
    return json.loads((FIXTURES / rel).read_text())


def _sign(body: str, secret: str, timestamp: str | None = None) -> Dict[str, str]:
    """Mirror published v0.3.0 signPayload(): "sha256=" + hex(HMAC(secret, "ts.body"))."""
    ts = timestamp if timestamp is not None else str(int(time.time()))
    nonce = secrets.token_hex(16)
    digest = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Pisama-Signature": f"sha256={digest}",
        "X-Pisama-Timestamp": ts,
        "X-Pisama-Nonce": nonce,
    }


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient backed by a fresh temp-file SQLite Storage. API key set."""
    monkeypatch.setenv("PISAMA_API_KEY", API_KEY)
    monkeypatch.delenv("PISAMA_WEBHOOK_SECRET", raising=False)
    db_path = tmp_path / "test.db"
    storage = Storage(url=f"sqlite:///{db_path}")
    app.dependency_overrides[get_storage] = lambda: storage
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def body() -> str:
    """The raw JSON string the node would sign and send."""
    return json.dumps(_load("executions/healthy/HEALTHY-01.json"))


# 1. A valid HMAC signature (secret = PISAMA_API_KEY fallback) is accepted.

def test_valid_hmac_accepted(client, body):
    resp = client.post(
        "/api/v1/n8n/webhook", content=body, headers=_sign(body, API_KEY)
    )
    assert resp.status_code == 200, resp.text
    assert "detections" in resp.json()


# 2. A dedicated PISAMA_WEBHOOK_SECRET takes precedence over the API key.

def test_webhook_secret_env_takes_precedence(client, body, monkeypatch):
    monkeypatch.setenv("PISAMA_WEBHOOK_SECRET", "separate-webhook-secret")

    signed_with_api_key = client.post(
        "/api/v1/n8n/webhook", content=body, headers=_sign(body, API_KEY)
    )
    assert signed_with_api_key.status_code == 401, signed_with_api_key.text

    signed_with_secret = client.post(
        "/api/v1/n8n/webhook",
        content=body,
        headers=_sign(body, "separate-webhook-secret"),
    )
    assert signed_with_secret.status_code == 200, signed_with_secret.text


# 3. A wrong signature is rejected.

def test_wrong_signature_401(client, body):
    headers = _sign(body, "not-the-secret")
    resp = client.post("/api/v1/n8n/webhook", content=body, headers=headers)
    assert resp.status_code == 401, resp.text


# 4. A stale timestamp (outside the +/-5 minute window) is rejected even when
#    the signature itself is valid for that timestamp.

def test_stale_timestamp_401(client, body):
    stale = str(int(time.time()) - 600)
    resp = client.post(
        "/api/v1/n8n/webhook", content=body, headers=_sign(body, API_KEY, timestamp=stale)
    )
    assert resp.status_code == 401, resp.text


def test_future_timestamp_401(client, body):
    future = str(int(time.time()) + 600)
    resp = client.post(
        "/api/v1/n8n/webhook", content=body, headers=_sign(body, API_KEY, timestamp=future)
    )
    assert resp.status_code == 401, resp.text


# 5. The signature covers the body: tampering after signing is rejected.

def test_tampered_body_401(client, body):
    headers = _sign(body, API_KEY)
    tampered = body.replace("HEALTHY-01", "TAMPERED-01")
    assert tampered != body, "fixture must contain the marker being replaced"
    resp = client.post("/api/v1/n8n/webhook", content=tampered, headers=headers)
    assert resp.status_code == 401, resp.text


# 6. Bearer-token auth still works alongside HMAC, and garbage is still rejected.

def test_bearer_still_works(client, body):
    resp = client.post(
        "/api/v1/n8n/webhook",
        content=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
    )
    assert resp.status_code == 200, resp.text

    wrong = client.post(
        "/api/v1/n8n/webhook",
        content=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"},
    )
    assert wrong.status_code == 401, wrong.text


# 7. The node ALWAYS sends its apiKey credential as X-Pisama-API-Key — a node
#    with no Webhook Secret configured must still authenticate through it.

def test_x_pisama_api_key_header_accepted(client, body):
    resp = client.post(
        "/api/v1/n8n/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Pisama-API-Key": API_KEY},
    )
    assert resp.status_code == 200, resp.text

    wrong = client.post(
        "/api/v1/n8n/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Pisama-API-Key": "wrong"},
    )
    assert wrong.status_code == 401, wrong.text


# 8. The DIVERGED unpublished signing variant (nonce inside the base, no
#    "sha256=" prefix) must be rejected — the server speaks published v0.3.0.

def test_old_nonce_in_base_variant_rejected(client, body):
    ts = str(int(time.time()))
    nonce = secrets.token_hex(16)
    old_style = hmac.new(
        API_KEY.encode(), f"{ts}.{nonce}.{body}".encode(), hashlib.sha256
    ).hexdigest()
    resp = client.post(
        "/api/v1/n8n/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Pisama-Signature": old_style,
            "X-Pisama-Timestamp": ts,
            "X-Pisama-Nonce": nonce,
        },
    )
    assert resp.status_code == 401, resp.text
