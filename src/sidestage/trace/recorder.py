"""Fail-open observations around the exact eight M3B component calls."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import json
from queue import Full, Queue
from threading import Lock, Thread
import time
from typing import Annotated, Any, Callable, Literal, Optional, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from sidestage.storage.database import MarketplaceDatabase


SafeRef = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=240,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]


class TraceStage(str, Enum):
    INGEST = "ingest"
    NORMALIZE_DEDUPLICATE = "normalize_deduplicate"
    DETERMINISTIC_ROUTE = "deterministic_route"
    LLM_ANALYSIS = "llm_analysis"
    EVIDENCE_RETRIEVAL = "evidence_retrieval"
    REPLY_AGENT = "registered_reply_agent"
    BROKER_GUARDRAILS = "broker_guardrails"
    RESULT = "result"


class TraceObservationStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    EXITED = "exited"
    SKIPPED = "skipped"


_COMPONENTS = {
    TraceStage.INGEST: "streaming.ingest.EventIngestor.ingest",
    TraceStage.NORMALIZE_DEDUPLICATE: (
        "copilot.routing.CopilotRouter.normalize_and_deduplicate"
    ),
    TraceStage.DETERMINISTIC_ROUTE: "copilot.routing.CopilotRouter.route",
    TraceStage.LLM_ANALYSIS: "copilot.analysis.MessageAnalyzer.analyze",
    TraceStage.EVIDENCE_RETRIEVAL: "copilot.retrieval.EvidenceRetriever.retrieve",
    TraceStage.REPLY_AGENT: "copilot.profile.LivesellReplyAgent.run",
    TraceStage.BROKER_GUARDRAILS: "copilot.broker.ReplyEffectBroker.evaluate",
    TraceStage.RESULT: "copilot.pipeline.ResultHandler.handle",
}
_STAGE_NUMBERS = {stage: index for index, stage in enumerate(TraceStage, start=1)}


class TraceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    observation_id: SafeRef
    trace_id: SafeRef
    stage: TraceStage
    stage_number: Annotated[int, Field(strict=True, ge=1, le=8)]
    component_id: SafeRef
    status: TraceObservationStatus
    seller_id: Optional[SafeRef] = None
    show_id: Optional[SafeRef] = None
    event_id: Optional[SafeRef] = None
    question_id: Optional[SafeRef] = None
    analysis_call_id: Optional[SafeRef] = None
    agent_run_id: Optional[SafeRef] = None
    profile_digest: Optional[SafeRef] = None
    snapshot_id: Optional[SafeRef] = None
    workflow_id: Optional[SafeRef] = None
    model_profile_id: Optional[SafeRef] = None
    selection_version: Optional[Annotated[int, Field(strict=True, gt=0)]] = None
    sample_phase: Optional[Literal["cold", "steady"]] = None
    occurred_at: datetime
    duration_ms: Optional[
        Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    ] = None
    input_ref: Optional[SafeRef] = None
    output_ref: Optional[SafeRef] = None
    verdict: Optional[SafeRef] = None
    reason_code: Optional[SafeRef] = None

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_is_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("trace timestamp must be timezone-aware")
        if value.utcoffset().total_seconds() != 0:
            raise ValueError("trace timestamp must use UTC")
        return value

    @model_validator(mode="after")
    def stage_number_matches_stage(self) -> "TraceObservation":
        if self.stage_number != _STAGE_NUMBERS[self.stage]:
            raise ValueError("trace stage number does not match stage")
        if self.status is TraceObservationStatus.STARTED and self.duration_ms is not None:
            raise ValueError("started observation cannot have duration")
        if self.status is not TraceObservationStatus.STARTED and self.duration_ms is None:
            raise ValueError("terminal observation requires duration")
        return self


class TraceSink(Protocol):
    def emit(self, observation: TraceObservation) -> None:
        ...


class InMemoryTraceSink:
    def __init__(self) -> None:
        self._observations: list[TraceObservation] = []

    @property
    def observations(self) -> tuple[TraceObservation, ...]:
        return tuple(self._observations)

    def emit(self, observation: TraceObservation) -> None:
        self._observations.append(observation)


class SqliteTraceSink:
    def __init__(self, database: MarketplaceDatabase) -> None:
        self.database = database

    def emit(self, observation: TraceObservation) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO copilot_trace_observations(
                       observation_id, trace_id, stage, stage_number, component_id,
                       status, seller_id, show_id, event_id, question_id,
                       analysis_call_id, agent_run_id, profile_digest, snapshot_id,
                       workflow_id, model_profile_id, selection_version, sample_phase,
                       occurred_at, duration_ms, input_ref, output_ref, verdict, reason_code
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    observation.observation_id,
                    observation.trace_id,
                    observation.stage.value,
                    observation.stage_number,
                    observation.component_id,
                    observation.status.value,
                    observation.seller_id,
                    observation.show_id,
                    observation.event_id,
                    observation.question_id,
                    observation.analysis_call_id,
                    observation.agent_run_id,
                    observation.profile_digest,
                    observation.snapshot_id,
                    observation.workflow_id,
                    observation.model_profile_id,
                    observation.selection_version,
                    observation.sample_phase,
                    _utc_text(observation.occurred_at),
                    observation.duration_ms,
                    observation.input_ref,
                    observation.output_ref,
                    observation.verdict,
                    observation.reason_code,
                ),
            )

    def for_trace(self, trace_id: str) -> tuple[TraceObservation, ...]:
        with self.database.read() as connection:
            rows = connection.execute(
                """SELECT * FROM copilot_trace_observations
                   WHERE trace_id = ? ORDER BY observation_number""",
                (trace_id,),
            ).fetchall()
        return tuple(
            TraceObservation(
                observation_id=row["observation_id"],
                trace_id=row["trace_id"],
                stage=TraceStage(row["stage"]),
                stage_number=int(row["stage_number"]),
                component_id=row["component_id"],
                status=TraceObservationStatus(row["status"]),
                seller_id=row["seller_id"],
                show_id=row["show_id"],
                event_id=row["event_id"],
                question_id=row["question_id"],
                analysis_call_id=row["analysis_call_id"],
                agent_run_id=row["agent_run_id"],
                profile_digest=row["profile_digest"],
                snapshot_id=row["snapshot_id"],
                workflow_id=row["workflow_id"],
                model_profile_id=row["model_profile_id"],
                selection_version=(
                    int(row["selection_version"])
                    if row["selection_version"] is not None
                    else None
                ),
                sample_phase=row["sample_phase"],
                occurred_at=datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00")),
                duration_ms=float(row["duration_ms"])
                if row["duration_ms"] is not None
                else None,
                input_ref=row["input_ref"],
                output_ref=row["output_ref"],
                verdict=row["verdict"],
                reason_code=row["reason_code"],
            )
            for row in rows
        )

    def record_artifact(
        self,
        *,
        artifact_id: str,
        trace_id: str,
        stage: TraceStage,
        artifact_kind: str,
        payload: dict,
        recorded_at: datetime,
    ) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO copilot_trace_artifacts(
                       artifact_id, trace_id, stage, artifact_kind,
                       payload_json, recorded_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    artifact_id,
                    trace_id,
                    stage.value,
                    artifact_kind,
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    _utc_text(recorded_at),
                ),
            )


class BufferedTraceSink:
    """Bounded nowait adapter that isolates reply latency from trace persistence."""

    _STOP = object()

    def __init__(self, sink: Any, *, capacity: int = 65_536) -> None:
        if capacity < 1:
            raise ValueError("trace buffer capacity must be positive")
        self.sink = sink
        self.queue: Queue = Queue(maxsize=capacity)
        self._lock = Lock()
        self.enqueued_count = 0
        self.persisted_count = 0
        self.dropped_count = 0
        self.failure_count = 0
        self._closed = False
        self._worker = Thread(
            target=self._drain,
            name="sidestage-trace-writer",
            daemon=True,
        )
        self._worker.start()

    def emit(self, observation: TraceObservation) -> None:
        self._enqueue(("emit", (observation,), {}))

    def record_artifact(self, **kwargs) -> None:
        self._enqueue(("record_artifact", (), kwargs))

    def flush(self) -> None:
        self.queue.join()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self.flush()
        self.queue.put(self._STOP)
        self._worker.join(timeout=5)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "capacity": self.queue.maxsize,
                "queued": self.queue.qsize(),
                "enqueued_count": self.enqueued_count,
                "persisted_count": self.persisted_count,
                "dropped_count": self.dropped_count,
                "failure_count": self.failure_count,
            }

    def _enqueue(self, operation: tuple) -> None:
        with self._lock:
            if self._closed:
                self.dropped_count += 1
                return
        try:
            self.queue.put_nowait(operation)
        except Full:
            with self._lock:
                self.dropped_count += 1
            return
        with self._lock:
            self.enqueued_count += 1

    def _drain(self) -> None:
        while True:
            operation = self.queue.get()
            try:
                if operation is self._STOP:
                    return
                method_name, args, kwargs = operation
                getattr(self.sink, method_name)(*args, **kwargs)
                with self._lock:
                    self.persisted_count += 1
            except Exception:
                with self._lock:
                    self.failure_count += 1
            finally:
                self.queue.task_done()


class TraceRecorder:
    """Construct strict observations and isolate every sink failure."""

    def __init__(
        self,
        *,
        sink: TraceSink,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] = lambda: f"obs_{uuid4().hex}",
    ) -> None:
        self.sink = sink
        self.wall_clock = wall_clock
        self.monotonic = monotonic
        self.id_factory = id_factory

    def start(self, stage: TraceStage, **context) -> "TraceSpan":
        started_at = self.monotonic()
        self._emit(
            stage=stage,
            status=TraceObservationStatus.STARTED,
            context=context,
            duration_ms=None,
        )
        return TraceSpan(self, stage=stage, started_at=started_at, context=context)

    def artifact(
        self,
        stage: TraceStage,
        *,
        trace_id: str,
        artifact_kind: str,
        payload: dict,
    ) -> None:
        """Persist one sanitized typed stage artifact through the fail-open trace sink."""

        try:
            record = getattr(self.sink, "record_artifact", None)
            if record is None:
                return
            record(
                artifact_id=f"art_{uuid4().hex}",
                trace_id=trace_id,
                stage=stage,
                artifact_kind=artifact_kind,
                payload=payload,
                recorded_at=self.wall_clock(),
            )
        except Exception:
            return

    def skip(self, stage: TraceStage, **context) -> None:
        self._emit(
            stage=stage,
            status=TraceObservationStatus.SKIPPED,
            context=context,
            duration_ms=0.0,
        )

    def _terminal(
        self,
        *,
        stage: TraceStage,
        status: TraceObservationStatus,
        started_at: float,
        context: dict,
    ) -> None:
        duration_ms = max(0.0, (self.monotonic() - started_at) * 1_000)
        self._emit(stage=stage, status=status, context=context, duration_ms=duration_ms)

    def _emit(
        self,
        *,
        stage: TraceStage,
        status: TraceObservationStatus,
        context: dict,
        duration_ms: Optional[float],
    ) -> None:
        try:
            observation = TraceObservation(
                observation_id=self.id_factory(),
                trace_id=context["trace_id"],
                stage=stage,
                stage_number=_STAGE_NUMBERS[stage],
                component_id=_COMPONENTS[stage],
                status=status,
                seller_id=context.get("seller_id"),
                show_id=context.get("show_id"),
                event_id=context.get("event_id"),
                question_id=context.get("question_id"),
                analysis_call_id=context.get("analysis_call_id"),
                agent_run_id=context.get("agent_run_id"),
                profile_digest=context.get("profile_digest"),
                snapshot_id=context.get("snapshot_id"),
                workflow_id=context.get("workflow_id"),
                model_profile_id=context.get("model_profile_id"),
                selection_version=context.get("selection_version"),
                sample_phase=context.get("sample_phase"),
                occurred_at=self.wall_clock(),
                duration_ms=duration_ms,
                input_ref=context.get("input_ref"),
                output_ref=context.get("output_ref"),
                verdict=context.get("verdict"),
                reason_code=context.get("reason_code"),
            )
            self.sink.emit(observation)
        except Exception:
            return


class TraceSpan:
    def __init__(
        self,
        recorder: TraceRecorder,
        *,
        stage: TraceStage,
        started_at: float,
        context: dict,
    ) -> None:
        self.recorder = recorder
        self.stage = stage
        self.started_at = started_at
        self.context = dict(context)
        self.terminal = False

    def completed(self, **updates) -> None:
        self._finish(TraceObservationStatus.COMPLETED, updates)

    def failed(self, **updates) -> None:
        self._finish(TraceObservationStatus.FAILED, updates)

    def exited(self, **updates) -> None:
        self._finish(TraceObservationStatus.EXITED, updates)

    def _finish(self, status: TraceObservationStatus, updates: dict) -> None:
        if self.terminal:
            raise RuntimeError("trace span already has a terminal observation")
        self.terminal = True
        context = {**self.context, **updates}
        self.recorder._terminal(
            stage=self.stage,
            status=status,
            started_at=self.started_at,
            context=context,
        )


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
