"""Sanitized, adapter-neutral lifecycle events for static agent runs."""

from __future__ import annotations

from enum import Enum
from typing import Optional, Protocol

from sidestage.agent_core.contracts import (
    AdapterId,
    CoreFailureCode,
    EntityId,
    FrozenContract,
    NonEmptyText,
    NonNegativeFiniteFloat,
    ProfileDigest,
    ProfileVersion,
    ToolName,
)


class CoreTraceEventType(str, Enum):
    TASK_ACCEPTED = "task_accepted"
    TASK_QUEUED = "task_queued"
    PROVIDER_STARTED = "provider_started"
    PROVIDER_COMPLETED = "provider_completed"
    TERMINAL_VALIDATED = "terminal_validated"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"


class CoreTraceEvent(FrozenContract):
    """One bounded observation; model and adapter payloads are intentionally absent."""

    schema_version: str = "sidestage.agent_core.trace.v1"
    event_type: CoreTraceEventType
    task_id: EntityId
    adapter_id: AdapterId
    profile_version: ProfileVersion
    profile_digest: ProfileDigest
    run_id: EntityId
    trace_id: EntityId
    scenario_id: Optional[EntityId] = None
    model_id: Optional[NonEmptyText] = None
    occurred_monotonic_s: NonNegativeFiniteFloat
    queue_ms: NonNegativeFiniteFloat = 0.0
    provider_ms: NonNegativeFiniteFloat = 0.0
    parse_ms: NonNegativeFiniteFloat = 0.0
    total_ms: NonNegativeFiniteFloat = 0.0
    terminal_tool: Optional[ToolName] = None
    failure_code: Optional[CoreFailureCode] = None


class TraceSink(Protocol):
    """A sink whose emission method must enqueue or record without awaiting I/O."""

    def emit_nowait(self, event: CoreTraceEvent) -> None:
        ...


class NullTraceSink:
    def emit_nowait(self, event: CoreTraceEvent) -> None:
        del event


class InMemoryTraceSink:
    """Deterministic no-I/O sink for tests and local evaluation."""

    def __init__(self) -> None:
        self._events: list[CoreTraceEvent] = []

    @property
    def events(self) -> tuple[CoreTraceEvent, ...]:
        return tuple(self._events)

    def emit_nowait(self, event: CoreTraceEvent) -> None:
        self._events.append(event)


class SafeTraceEmitter:
    """Fail-open wrapper that never grants a diagnostic sink control of a run."""

    def __init__(self, sink: TraceSink) -> None:
        self._sink = sink

    def emit(self, event: CoreTraceEvent) -> None:
        try:
            self._sink.emit_nowait(event)
        except Exception:
            return
