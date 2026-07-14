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
    select,
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
    received_at: Mapped[str] = mapped_column(String, nullable=False)
    raw: Mapped[str] = mapped_column(Text, nullable=False)

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


def database_url() -> str:
    return os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL


def make_engine(url: Optional[str] = None):
    url = url or database_url()
    # check_same_thread=False so the FastAPI TestClient's threadpool can share a
    # SQLite connection; harmless for the default single-process self-host case.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args, future=True)
    Base.metadata.create_all(engine)
    return engine


class Storage:
    """A tiny persistence facade around a SQLAlchemy engine + session factory."""

    def __init__(self, url: Optional[str] = None) -> None:
        self.engine = make_engine(url)
        self._Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def save_report(self, execution_data: Dict[str, Any], report: Any) -> int:
        """Persist the raw payload + every detection in the report. Returns exec id."""
        try:
            raw = json.dumps(execution_data, default=str)
        except (TypeError, ValueError):
            raw = str(execution_data)

        workflow_id = report.workflow_id or execution_data.get("workflowId")
        received_at = datetime.now(timezone.utc).isoformat()

        with self._Session() as session:
            execution = Execution(
                workflow_id=workflow_id,
                received_at=received_at,
                raw=raw,
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

    def list_detections(self) -> List[Dict[str, Any]]:
        with self._Session() as session:
            # Join executions so each detection carries the real ingest time,
            # giving the dashboard a genuine timestamp instead of a fabricated one.
            rows = session.execute(
                select(DetectionRow, Execution.received_at)
                .join(Execution, DetectionRow.execution_id == Execution.id)
                .order_by(DetectionRow.id)
            ).all()
            return [
                {**row.to_dict(), "received_at": received_at}
                for row, received_at in rows
            ]
