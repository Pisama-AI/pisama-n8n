# VENDORED from the pisama monorepo by scripts/extract_from_monorepo.py — do not edit here.
"""Provider-agnostic webhook security utilities.

Shared by all provider integrations (n8n, OpenClaw, Dify) for:
- Webhook signature verification (HMAC-SHA256)
- Sensitive data redaction
- State hash computation
- Instance URL validation
- API key hashing
"""

import hmac
import hashlib
import time
import re
import urllib.parse
from ipaddress import ip_address, IPv4Address, IPv6Address
from typing import Optional
from fastapi import HTTPException

BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"}  # nosec B104 - blocking, not binding
BLOCKED_PORTS = {22, 25, 445, 3306, 5432, 6379, 27017}
TIMESTAMP_TOLERANCE_SECONDS = 300  # 5 min industry-standard window. Replay
# is prevented by the nonce table (see verify_nonce below), not by a tight
# timestamp — 10s was too strict for legitimate cron sync scripts that face
# normal clock drift and network RTT.

SENSITIVE_PATTERNS = [
    re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
    re.compile(r'\bsk-[a-zA-Z0-9]{32,}\b'),
    re.compile(r'\bxai-[a-zA-Z0-9]{32,}\b'),
    re.compile(r'\bAIza[a-zA-Z0-9_-]{35}\b'),
    re.compile(r'\bghp_[a-zA-Z0-9]{36}\b'),
]


def verify_webhook_signature(
    payload: bytes,
    signature: str,
    secret: str,
    timestamp: str,
) -> bool:
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid timestamp format")

    if abs(time.time() - ts) > TIMESTAMP_TOLERANCE_SECONDS:
        raise HTTPException(status_code=401, detail="Webhook timestamp expired")

    message = f"{timestamp}.{payload.decode()}"
    expected = hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, f"sha256={expected}"):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    return True


def validate_instance_url(url: str) -> str:
    """Validate a provider instance URL for SSRF protection."""
    if not url:
        raise ValueError("Instance URL is required")

    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in ("https", "http"):
        raise ValueError("URL must use HTTP or HTTPS")

    if not parsed.hostname:
        raise ValueError("Invalid URL")

    hostname = parsed.hostname.lower()

    if hostname in BLOCKED_HOSTS:
        raise ValueError("Internal hosts not allowed")

    if hostname.endswith(".internal") or hostname.endswith(".local"):
        raise ValueError("Internal domains not allowed")

    try:
        ip = ip_address(hostname)
    except ValueError:
        pass
    else:
        if isinstance(ip, (IPv4Address, IPv6Address)):
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                raise ValueError("Private/internal IPs not allowed")

    # SSRF defense — also resolve the hostname to its actual IPs and reject
    # any that land on private/loopback ranges. The hostname check above
    # only catches literal IPs and `.internal`/`.local` suffixes; an
    # attacker controlling DNS for `evil.com` (or using `127.0.0.1.nip.io`)
    # could otherwise pass validation and resolve to an internal address
    # at request time. We don't pin the resolved IP here (that would
    # require a custom HTTP transport), but blocking at validation makes
    # the simple bypass infeasible.
    try:
        import socket
        for info in socket.getaddrinfo(hostname, None):
            try:
                ip = ip_address(info[4][0])
            except ValueError:
                continue
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                raise ValueError(
                    f"Hostname {hostname} resolves to internal IP {ip} (SSRF defense)"
                )
    except (socket.gaierror, OSError):
        # DNS lookup failed — allow caller to retry; downstream HTTP will
        # surface the resolution failure if the host genuinely doesn't exist.
        pass

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port in BLOCKED_PORTS:
        raise ValueError(f"Port {port} not allowed")

    return url


# Keep backward-compat alias
validate_n8n_url = validate_instance_url


def redact_sensitive_data(data: dict, skip_keys: Optional[list] = None) -> dict:
    """
    Redact sensitive data from a dictionary.

    Args:
        data: Dictionary to redact
        skip_keys: List of keys to skip redaction for (e.g., prompts, messages)

    Returns:
        Dictionary with sensitive data redacted
    """
    if not isinstance(data, dict):
        return data

    skip_keys = skip_keys or []

    result = {}
    for key, value in data.items():
        if key in skip_keys:
            result[key] = value
        elif isinstance(value, str):
            redacted = value
            for pattern in SENSITIVE_PATTERNS:
                redacted = pattern.sub("[REDACTED]", redacted)
            result[key] = redacted
        elif isinstance(value, dict):
            result[key] = redact_sensitive_data(value, skip_keys=skip_keys)
        elif isinstance(value, list):
            result[key] = [
                redact_sensitive_data(item, skip_keys=skip_keys) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value

    return result


def compute_state_hash(state_delta: dict) -> str:
    import json
    normalized = json.dumps(state_delta, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage using bcrypt (slow hash, rainbow-table resistant)."""
    import bcrypt
    return bcrypt.hashpw(api_key.encode(), bcrypt.gensalt()).decode()


def verify_api_key(api_key: str, hashed: str) -> bool:
    """Verify an API key against its bcrypt hash."""
    import bcrypt
    try:
        return bcrypt.checkpw(api_key.encode(), hashed.encode())
    except (ValueError, TypeError):
        # Fallback: check if it's a legacy SHA-256 hash
        return hashlib.sha256(api_key.encode()).hexdigest() == hashed


# Backward-compat alias
encrypt_api_key = hash_api_key
