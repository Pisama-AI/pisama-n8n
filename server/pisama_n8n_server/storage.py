"""pisama_n8n_server.storage — SQLite persistence for ingested executions + detections.

Single-tenant, SQLAlchemy 2.x. Defaults to a local SQLite file; override with
``DATABASE_URL`` (e.g. a Postgres DSN) later. Two tables are enough:

  - ``executions``  (id, workflow_id, received_at, raw)
  - ``detections`` (id, execution_id FK, detector, detected, confidence,
                    failure_mode, explanation)

No mocks: this is real SQLite via a real SQLAlchemy engine. Tests point
``DATABASE_URL`` at a temp file / ``sqlite:///:memory:`` — still real SQLite.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Float,
    ForeignKey,
    String,
    Text,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

DEFAULT_DATABASE_URL = "sqlite:///pisama_n8n.db"


class Base(DeclarativeBase):
    pass


class Execution(Base):
    __tablename__ = "executions"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Human-readable workflow name (from the execution payload), so the dashboard can
    # group detections by workflow and label them without the opaque n8n id.
    workflow_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    received_at: Mapped[str] = mapped_column(String, nullable=False)
    raw: Mapped[str] = mapped_column(Text, nullable=False)
    # The upstream n8n execution id, when this row came from API polling — used to
    # dedup so re-polling doesn't re-ingest the same execution. Null for webhook pushes.
    source_execution_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    detections: Mapped[List["DetectionRow"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )


class DetectionRow(Base):
    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(primary_key=True)
    execution_id: Mapped[int] = mapped_column(ForeignKey("executions.id"), nullable=False)
    detector: Mapped[str] = mapped_column(String, nullable=False)
    detected: Mapped[bool] = mapped_column(nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    failure_mode: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, default="")

    execution: Mapped["Execution"] = relationship(back_populates="detections")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "detector": self.detector,
            "detected": self.detected,
            "confidence": self.confidence,
            "failure_mode": self.failure_mode,
            "explanation": self.explanation,
        }


def _extract_workflow_name(payload: Dict[str, Any]) -> Optional[str]:
    """Pull the workflow name out of an execution payload. Full executions carry it
    under ``workflowData``/``workflow``; a bare workflow POST has it at the top level."""
    for key in ("workflowData", "workflow"):
        block = payload.get(key)
        if isinstance(block, dict) and block.get("name"):
            return str(block["name"])
    if payload.get("workflowName"):
        return str(payload["workflowName"])
    if payload.get("name") and ("nodes" in payload or "connections" in payload):
        return str(payload["name"])
    return None


def database_url() -> str:
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


# Columns added after the first (id, workflow_id, received_at, raw) release, keyed by
# table. create_all() only creates missing TABLES, not missing columns, so an existing
# self-host DB needs these added in place. ALTER TABLE ADD COLUMN is supported by both
# SQLite and Postgres. Keep every post-initial column here so an upgraded instance's
# DB catches up (source_execution_id shipped without a migration and would otherwise
# break reads on a pre-polling DB).
_ADDED_COLUMNS = {
    "executions": {
        "source_execution_id": "VARCHAR",
        "workflow_name": "VARCHAR",
    },
}


def _ensure_columns(engine) -> None:
    """Additive, idempotent schema catch-up for a no-migration-framework server."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue  # create_all already made it with every column
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl_type in columns.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))


def make_engine(url: Optional[str] = None):
    url = url or database_url()
    # check_same_thread=False so the FastAPI TestClient's threadpool can share a
    # SQLite connection; harmless for the default single-process self-host case.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args, future=True)
    Base.metadata.create_all(engine)
    _ensure_columns(engine)
    return engine


class Storage:
    """A tiny persistence facade around a SQLAlchemy engine + session factory."""

    def __init__(self, url: Optional[str] = None) -> None:
        self.engine = make_engine(url)
        self._Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def save_report(
        self,
        execution_data: Dict[str, Any],
        report: Any,
        source_execution_id: Optional[str] = None,
    ) -> int:
        """Persist the raw payload + every detection in the report. Returns exec id."""
        try:
            raw = json.dumps(execution_data, default=str)
        except (TypeError, ValueError):
            raw = str(execution_data)

        workflow_id = report.workflow_id or execution_data.get("workflowId")
        workflow_name = _extract_workflow_name(execution_data)
        received_at = datetime.now(timezone.utc).isoformat()

        with self._Session() as session:
            execution = Execution(
                workflow_id=workflow_id,
                workflow_name=workflow_name,
                received_at=received_at,
                raw=raw,
                source_execution_id=source_execution_id,
            )
            for d in report.detections:
                execution.detections.append(
                    DetectionRow(
                        detector=d.detector,
                        detected=bool(d.detected),
                        confidence=float(d.confidence),
                        failure_mode=d.failure_mode,
                        explanation=d.explanation or "",
                    )
                )
            session.add(execution)
            session.commit()
            return execution.id

    def seen_source_ids(self) -> set:
        """The set of upstream n8n execution ids already ingested (for poll dedup)."""
        with self._Session() as session:
            rows = session.execute(
                select(Execution.source_execution_id).where(
                    Execution.source_execution_id.is_not(None)
                )
            ).all()
            return {r[0] for r in rows}

    def get_detection_context(self, detection_id: int) -> Optional[Dict[str, Any]]:
        """A detection plus the workflow JSON of the execution it came from — the input
        the cloud fix generator needs. None if the detection id is unknown."""
        with self._Session() as session:
            det = session.get(DetectionRow, detection_id)
            if det is None:
                return None
            execution = session.get(Execution, det.execution_id)
            workflow = None
            if execution is not None:
                try:
                    raw = json.loads(execution.raw)
                    workflow = raw.get("workflow") or raw.get("workflowData")
                    if workflow is None and ("nodes" in raw or "connections" in raw):
                        workflow = raw
                except (TypeError, ValueError):
                    workflow = None
            return {
                "detection": det.to_dict(),
                "workflow": workflow,
                "workflow_id": execution.workflow_id if execution else None,
            }

    # The execution columns joined onto every detection row the API returns.
    _EXEC_COLS = (
        Execution.received_at,
        Execution.workflow_id,
        Execution.workflow_name,
        Execution.source_execution_id,
    )

    @staticmethod
    def _enrich(det: DetectionRow, received_at, workflow_id, workflow_name, source_id) -> Dict[str, Any]:
        return {
            **det.to_dict(),
            "received_at": received_at,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            # The upstream n8n execution id (poll-ingested rows only); lets the
            # dashboard deep-link to the exact execution in the user's n8n.
            "n8n_execution_id": source_id,
        }

    def list_detections(self) -> List[Dict[str, Any]]:
        with self._Session() as session:
            # Join executions so each detection carries the real ingest time plus the
            # workflow it came from, instead of a fabricated timestamp and no context.
            rows = session.execute(
                select(DetectionRow, *self._EXEC_COLS)
                .join(Execution, DetectionRow.execution_id == Execution.id)
                .order_by(DetectionRow.id)
            ).all()
            return [self._enrich(*row) for row in rows]

    def get_detection(self, detection_id: int) -> Optional[Dict[str, Any]]:
        """A single enriched detection row, or None if the id is unknown. Backs the
        detail view's fetch-by-id so a deep link doesn't depend on the full list."""
        with self._Session() as session:
            row = session.execute(
                select(DetectionRow, *self._EXEC_COLS)
                .join(Execution, DetectionRow.execution_id == Execution.id)
                .where(DetectionRow.id == detection_id)
            ).first()
            return self._enrich(*row) if row else None
