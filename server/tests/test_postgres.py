"""Real PostgreSQL migration and cross-replica concurrency contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from pisama_n8n_server.storage import Storage


POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="TEST_POSTGRES_URL is required for the real PostgreSQL lane.",
)


@pytest.fixture()
def postgres_url():
    assert POSTGRES_URL is not None
    schema = f"pisama_test_{uuid.uuid4().hex}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    parsed = make_url(POSTGRES_URL)
    query = dict(parsed.query)
    query["options"] = f"-csearch_path={schema}"
    isolated = parsed.set(query=query).render_as_string(hide_password=False)
    try:
        yield isolated
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_postgres_applies_every_schema_migration(postgres_url):
    storage = Storage(url=postgres_url)
    try:
        with storage.engine.begin() as connection:
            versions = connection.execute(
                text("SELECT version FROM schema_migrations ORDER BY version")
            ).scalars().all()
        assert versions == [
            "001_legacy_columns",
            "002_source_execution_dedup",
            "003_closed_loop_audit",
        ]
    finally:
        storage.close()


def test_postgres_request_controls_are_atomic_across_connections(postgres_url):
    first = Storage(url=postgres_url)
    second = Storage(url=postgres_url)
    clients = [first, second]
    try:
        with ThreadPoolExecutor(max_workers=12) as executor:
            rate_results = list(
                executor.map(
                    lambda index: clients[index % 2].consume_rate_limit(
                        "shared-postgres-principal", 10
                    ),
                    range(24),
                )
            )
            nonce_results = list(
                executor.map(
                    lambda index: clients[index % 2].consume_webhook_nonce(
                        "shared-postgres-nonce", 600
                    ),
                    range(12),
                )
            )
        assert sum(rate_results) == 10
        assert sum(nonce_results) == 1
    finally:
        first.close()
        second.close()
