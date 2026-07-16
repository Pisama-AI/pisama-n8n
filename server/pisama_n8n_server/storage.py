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
    desc,
    Float,
    ForeignKey,
    String,
    Text,
    create_engine,
    func,
    inspect,
    select,
    text,
    update,
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


class RepairAttempt(Base):
    """A durable, server-owned record of a proposed workflow repair.

    Repair payloads must never be trusted when they come back from a browser. Keeping
    the proposal, pre-apply snapshot, and lifecycle transitions here creates an audit
    trail and prevents stale tabs from applying arbitrary workflow JSON.
    """

    __tablename__ = "repair_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    detection_id: Mapped[int] = mapped_column(ForeignKey("detections.id"), nullable=False, index=True)
    workflow_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    baseline_workflow: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_workflow: Mapped[str] = mapped_column(Text, nullable=False)
    patch_ops: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String, default="proposed", nullable=False, index=True)
    snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    applied_workflow: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    applied_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    rolled_back_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    @staticmethod
    def _decode(value: Optional[str], fallback: Any) -> Any:
        if not value:
            return fallback
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return fallback

    def to_dict(self, include_workflows: bool = False) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "id": self.id,
            "detection_id": self.detection_id,
            "workflow_id": self.workflow_id,
            "patch_ops": self._decode(self.patch_ops, []),
            "explanation": self.explanation,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at,
            "applied_at": self.applied_at,
            "rolled_back_at": self.rolled_back_at,
        }
        if include_workflows:
            result.update(
                baseline_workflow=self._decode(self.baseline_workflow, {}),
                proposed_workflow=self._decode(self.proposed_workflow, {}),
                snapshot=self._decode(self.snapshot, None),
                applied_workflow=self._decode(self.applied_workflow, None),
            )
        return result


class DetectionFeedback(Base):
    """An operator's explicit verdict on a detection, kept in the self-host database."""

    __tablename__ = "detection_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    detection_id: Mapped[int] = mapped_column(ForeignKey("detections.id"), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String, nullable=False, index=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "detection_id": self.detection_id,
            "verdict": self.verdict,
            "note": self.note,
            "created_at": self.created_at,
        }


class OperationalEvent(Base):
    """Small, local-only audit events for ingestion and polling health."""

    __tablename__ = "operational_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    details: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "details": RepairAttempt._decode(self.details, {}),
            "created_at": self.created_at,
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


def _workflow_block(raw: Dict[str, Any]) -> Dict[str, Any]:
    """The block holding the workflow nodes: workflowData/workflow on a full
    execution, or the payload itself on a bare workflow POST."""
    for key in ("workflowData", "workflow"):
        block = raw.get(key)
        if isinstance(block, dict) and block.get("nodes"):
            return block
    if raw.get("nodes"):
        return raw
    return {}


def _parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_trace(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a stored n8n execution payload into a per-node trace the dashboard can
    render: what ran, its status, timing, item counts, and errors. Two kinds:
    ``runtime`` (has data.resultData.runData) and ``static`` (workflow nodes only,
    e.g. a structural detection). ``{"available": False}`` when neither is present."""
    if not isinstance(raw, dict):
        return {"available": False}

    block = _workflow_block(raw)
    node_type = {
        n.get("name"): n.get("type")
        for n in (block.get("nodes") or [])
        if isinstance(n, dict)
    }
    order_names = [n.get("name") for n in (block.get("nodes") or []) if isinstance(n, dict)]

    data = raw.get("data")
    result = data.get("resultData") if isinstance(data, dict) else None
    result = result if isinstance(result, dict) else {}
    run_data = result.get("runData")

    top_error = result.get("error", {}).get("message") if isinstance(result.get("error"), dict) else None
    started, stopped = _parse_iso(raw.get("startedAt")), _parse_iso(raw.get("stoppedAt"))
    duration_ms = int((stopped - started).total_seconds() * 1000) if started and stopped else None

    if isinstance(run_data, dict) and run_data:
        nodes: List[Dict[str, Any]] = []
        for name, runs in run_data.items():
            if not isinstance(runs, list):
                continue
            total_time, total_items, status, node_err, order = 0, 0, "success", None, None
            for run in runs:
                if not isinstance(run, dict):
                    continue
                total_time += int(run.get("executionTime") or 0)
                for branch in ((run.get("data") or {}).get("main") or []):
                    if isinstance(branch, list):
                        total_items += len(branch)
                errored = run.get("executionStatus") == "error" or bool(run.get("error"))
                if errored:
                    status = "error"
                    if node_err is None and isinstance(run.get("error"), dict):
                        node_err = run["error"].get("message")
                if order is None:
                    order = run.get("executionIndex")
            nodes.append(
                {
                    "name": name,
                    "type": node_type.get(name),
                    "ran": True,
                    "status": status,
                    "execution_time_ms": total_time,
                    "items_out": total_items,
                    "error": node_err,
                    "runs": len(runs),
                    "_order": order if order is not None else 10**9,
                }
            )
        nodes.sort(key=lambda n: n["_order"])
        for n in nodes:
            n.pop("_order", None)
        overall = "error" if (top_error or any(n["status"] == "error" for n in nodes)) else (
            "success" if raw.get("finished") else "unknown"
        )
        return {
            "available": True,
            "kind": "runtime",
            "status": overall,
            "finished": bool(raw.get("finished")),
            "duration_ms": duration_ms,
            "error": top_error,
            "last_node": result.get("lastNodeExecuted"),
            "node_count": len(nodes),
            "nodes": nodes,
        }

    if order_names:
        return {
            "available": True,
            "kind": "static",
            "status": None,
            "finished": None,
            "duration_ms": None,
            "error": None,
            "last_node": None,
            "node_count": len(order_names),
            "nodes": [
                {
                    "name": nm,
                    "type": node_type.get(nm),
                    "ran": False,
                    "status": "unknown",
                    "execution_time_ms": None,
                    "items_out": None,
                    "error": None,
                    "runs": 0,
                }
                for nm in order_names
            ],
        }

    return {"available": False}


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

    @staticmethod
    def _encode(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    def create_repair_proposal(
        self,
        detection_id: int,
        workflow_id: str,
        baseline_workflow: Dict[str, Any],
        suggestion: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Persist a cloud suggestion before a browser can see or apply it."""
        proposed = suggestion.get("mutated_workflow")
        if not isinstance(proposed, dict):
            raise ValueError("Cloud fix response did not include a mutated_workflow object.")
        now = datetime.now(timezone.utc).isoformat()
        with self._Session() as session:
            row = RepairAttempt(
                detection_id=detection_id,
                workflow_id=str(workflow_id),
                baseline_workflow=self._encode(baseline_workflow),
                proposed_workflow=self._encode(proposed),
                patch_ops=self._encode(suggestion.get("patch_ops") or []),
                explanation=str(suggestion.get("explanation") or ""),
                status="proposed",
                created_at=now,
            )
            session.add(row)
            session.commit()
            return row.to_dict()

    def get_repair(self, repair_id: int, include_workflows: bool = False) -> Optional[Dict[str, Any]]:
        with self._Session() as session:
            row = session.get(RepairAttempt, repair_id)
            return row.to_dict(include_workflows=include_workflows) if row else None

    def record_operational_event(self, event_type: str, details: Dict[str, Any]) -> None:
        """Persist a minimal local health event. Workflow payloads never belong here."""
        with self._Session() as session:
            session.add(
                OperationalEvent(
                    event_type=event_type,
                    details=self._encode(details),
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )
            session.commit()

    def submit_detection_feedback(
        self, detection_id: int, verdict: str, note: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Record one opt-in operator verdict. None means the detection does not exist."""
        with self._Session() as session:
            if session.get(DetectionRow, detection_id) is None:
                return None
            feedback = DetectionFeedback(
                detection_id=detection_id,
                verdict=verdict,
                note=note.strip()[:1000] if note else None,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            session.add(feedback)
            session.commit()
            return feedback.to_dict()

    def latest_detection_feedback(self, detection_id: int) -> Optional[Dict[str, Any]]:
        with self._Session() as session:
            row = session.execute(
                select(DetectionFeedback)
                .where(DetectionFeedback.detection_id == detection_id)
                .order_by(desc(DetectionFeedback.id))
                .limit(1)
            ).scalar_one_or_none()
            return row.to_dict() if row else None

    def operational_summary(self) -> Dict[str, Any]:
        """Local operational signals for an operator, derived from real persisted state."""
        with self._Session() as session:
            executions = session.scalar(select(func.count(Execution.id))) or 0
            fired = session.scalar(
                select(func.count(DetectionRow.id)).where(DetectionRow.detected.is_(True))
            ) or 0
            latest_execution = session.scalar(select(func.max(Execution.received_at)))
            detector_rows = session.execute(
                select(DetectionRow.detector, func.count(DetectionRow.id))
                .where(DetectionRow.detected.is_(True))
                .group_by(DetectionRow.detector)
                .order_by(desc(func.count(DetectionRow.id)))
            ).all()
            repair_rows = session.execute(
                select(RepairAttempt.status, func.count(RepairAttempt.id))
                .group_by(RepairAttempt.status)
            ).all()
            feedback_rows = session.execute(
                select(DetectionFeedback.verdict, func.count(DetectionFeedback.id))
                .group_by(DetectionFeedback.verdict)
            ).all()
            events = session.execute(
                select(OperationalEvent)
                .order_by(desc(OperationalEvent.id))
                .limit(100)
            ).scalars()
            latest_events: Dict[str, Dict[str, Any]] = {}
            for event in events:
                latest_events.setdefault(event.event_type, event.to_dict())
            return {
                "executions_analyzed": executions,
                "detections_fired": fired,
                "last_ingested_at": latest_execution,
                "fired_by_detector": dict(detector_rows),
                "repairs_by_status": dict(repair_rows),
                "feedback_by_verdict": dict(feedback_rows),
                "latest_events": latest_events,
            }

    def _claim_repair(self, repair_id: int, from_status: str, to_status: str) -> Optional[Dict[str, Any]]:
        """Atomically own a repair transition, preventing double-click races."""
        with self._Session() as session:
            claimed = session.execute(
                update(RepairAttempt)
                .where(RepairAttempt.id == repair_id, RepairAttempt.status == from_status)
                .values(status=to_status, failure_reason=None)
            ).rowcount
            if claimed != 1:
                session.rollback()
                return None
            session.commit()
            row = session.get(RepairAttempt, repair_id)
            return row.to_dict(include_workflows=True) if row else None

    def claim_repair_apply(self, repair_id: int) -> Optional[Dict[str, Any]]:
        return self._claim_repair(repair_id, "proposed", "applying")

    def claim_repair_rollback(self, repair_id: int) -> Optional[Dict[str, Any]]:
        return self._claim_repair(repair_id, "applied", "rolling_back")

    def mark_repair_applied(
        self, repair_id: int, snapshot: Dict[str, Any], applied_workflow: Dict[str, Any]
    ) -> Dict[str, Any]:
        return self._finish_repair(
            repair_id,
            "applying",
            "applied",
            snapshot=self._encode(snapshot),
            applied_workflow=self._encode(applied_workflow),
            applied_at=datetime.now(timezone.utc).isoformat(),
        )

    def mark_repair_rolled_back(self, repair_id: int) -> Dict[str, Any]:
        return self._finish_repair(
            repair_id,
            "rolling_back",
            "rolled_back",
            rolled_back_at=datetime.now(timezone.utc).isoformat(),
        )

    def mark_repair_failed(self, repair_id: int, from_status: str, reason: str) -> None:
        self._finish_repair(
            repair_id,
            from_status,
            "failed",
            failure_reason=reason[:1000],
        )

    def mark_repair_stale(self, repair_id: int, from_status: str, reason: str) -> None:
        self._finish_repair(
            repair_id,
            from_status,
            "stale",
            failure_reason=reason[:1000],
        )

    def _finish_repair(
        self, repair_id: int, from_status: str, to_status: str, **values: Any
    ) -> Dict[str, Any]:
        with self._Session() as session:
            changed = session.execute(
                update(RepairAttempt)
                .where(RepairAttempt.id == repair_id, RepairAttempt.status == from_status)
                .values(status=to_status, **values)
            ).rowcount
            if changed != 1:
                session.rollback()
                raise ValueError("Repair state changed concurrently.")
            session.commit()
            row = session.get(RepairAttempt, repair_id)
            assert row is not None
            return row.to_dict()

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
            if row is None:
                return None
            result = self._enrich(*row)
            feedback = session.execute(
                select(DetectionFeedback)
                .where(DetectionFeedback.detection_id == detection_id)
                .order_by(desc(DetectionFeedback.id))
                .limit(1)
            ).scalar_one_or_none()
            result["feedback"] = feedback.to_dict() if feedback else None
            return result

    def get_execution_trace(self, detection_id: int) -> Optional[Dict[str, Any]]:
        """The per-node execution trace for a detection's execution — what ran, its
        status, timing, and errors. None if the detection id is unknown; a
        ``{"available": False}`` dict if the stored payload has no parseable trace."""
        with self._Session() as session:
            det = session.get(DetectionRow, detection_id)
            if det is None:
                return None
            execution = session.get(Execution, det.execution_id)
            if execution is None:
                return {"available": False}
            try:
                raw = json.loads(execution.raw)
            except (TypeError, ValueError):
                return {"available": False}
            return parse_trace(raw)
