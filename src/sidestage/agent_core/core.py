"""One-request, no-effect static agent core with bounded scheduling and tracing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
import time
from typing import Callable, Optional
from uuid import uuid4

from sidestage.agent_core.contracts import (
    AgentRunResult,
    AgentTask,
    CoreFailure,
    CoreFailureCode,
    LatencyBreakdown,
    RunStatus,
    TerminalIntent,
)
from sidestage.agent_core.model import ModelInvocation, ModelResponse, ModelRunner
from sidestage.agent_core.profile import (
    AgentProfileRegistry,
    AgentTaskValidationError,
    RegisteredAgentProfile,
    UnknownAgentProfileError,
)
from sidestage.agent_core.scheduler import (
    BoundedFifoScheduler,
    SchedulerCancelledError,
    SchedulerDeadlineError,
    SchedulerLease,
    SchedulerQueueFullError,
)
from sidestage.agent_core.terminal import TerminalResponseError, decode_terminal_response
from sidestage.agent_core.trace import (
    CoreTraceEvent,
    CoreTraceEventType,
    NullTraceSink,
    SafeTraceEmitter,
    TraceSink,
)


_ENTITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
TerminalDecoder = Callable[[ModelResponse, RegisteredAgentProfile], TerminalIntent]


def _new_id() -> str:
    return uuid4().hex


@dataclass(frozen=True)
class _RunIdentity:
    task: AgentTask
    run_id: str
    trace_id: str
    scenario_id: Optional[str]


class StaticAgentCore:
    """Queue, validate, call one model once, and return intent data without effects."""

    def __init__(
        self,
        *,
        registry: AgentProfileRegistry,
        model_runner: ModelRunner,
        monotonic: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] = _new_id,
        trace_sink: Optional[TraceSink] = None,
        terminal_decoder: TerminalDecoder = decode_terminal_response,
    ) -> None:
        self._registry = registry
        self._model_runner = model_runner
        self._monotonic = monotonic
        self._id_factory = id_factory
        self._terminal_decoder = terminal_decoder
        self._scheduler = BoundedFifoScheduler(
            (registered.profile for registered in registry.profiles),
            monotonic=monotonic,
        )
        self._trace = SafeTraceEmitter(trace_sink or NullTraceSink())

    async def run(self, task: AgentTask) -> AgentRunResult:
        accepted_at = self._monotonic()
        identity = _RunIdentity(
            task=task,
            run_id=self._id_factory(),
            trace_id=self._correlation_id(task, "trace_id") or self._id_factory(),
            scenario_id=self._correlation_id(task, "scenario_id"),
        )

        try:
            registered = self._registry.resolve(
                task.adapter_id,
                task.profile_version,
                task.profile_digest,
            )
        except UnknownAgentProfileError:
            result = self._failure_result(
                identity=identity,
                model_id="not-invoked",
                code=CoreFailureCode.INVALID_PROFILE,
                message="task references an unknown startup profile",
                accepted_at=accepted_at,
            )
            self._emit_result(identity, result)
            return result

        try:
            projection = registered.project_model_request(
                task,
                now_monotonic_s=self._monotonic(),
            )
        except AgentTaskValidationError:
            result = self._failure_result(
                identity=identity,
                model_id=registered.profile.model_config_ref,
                code=CoreFailureCode.INVALID_TASK,
                message="task failed startup profile validation",
                accepted_at=accepted_at,
            )
            self._emit_result(identity, result)
            return result

        self._emit(
            CoreTraceEventType.TASK_ACCEPTED,
            identity,
            occurred_at=accepted_at,
            model_id=registered.profile.model_config_ref,
        )
        profile_identity = (
            registered.profile.adapter_id,
            registered.profile.profile_version,
        )
        try:
            lease = await self._scheduler.acquire(
                profile_identity,
                deadline_monotonic_s=task.deadline_monotonic_s,
                on_queued=lambda queued_at: self._emit(
                    CoreTraceEventType.TASK_QUEUED,
                    identity,
                    occurred_at=queued_at,
                    model_id=registered.profile.model_config_ref,
                ),
            )
        except SchedulerQueueFullError:
            result = self._failure_result(
                identity=identity,
                model_id=registered.profile.model_config_ref,
                code=CoreFailureCode.QUEUE_FULL,
                message="agent profile queue is full",
                accepted_at=accepted_at,
            )
            self._emit_result(identity, result)
            return result
        except SchedulerDeadlineError as exc:
            completed_at = self._monotonic()
            result = self._failure_result(
                identity=identity,
                model_id=registered.profile.model_config_ref,
                code=CoreFailureCode.HARD_TIMEOUT,
                message="agent task exceeded its hard deadline while queued",
                accepted_at=accepted_at,
                queue_ms=max(0.0, (completed_at - exc.queued_at) * 1_000),
                completed_at=completed_at,
            )
            self._emit_result(identity, result)
            return result
        except SchedulerCancelledError as exc:
            completed_at = self._monotonic()
            result = self._failure_result(
                identity=identity,
                model_id=registered.profile.model_config_ref,
                code=CoreFailureCode.CANCELLED,
                message="agent task was cancelled while queued",
                accepted_at=accepted_at,
                queue_ms=max(0.0, (completed_at - exc.queued_at) * 1_000),
                completed_at=completed_at,
            )
            self._emit_result(identity, result)
            return result
        try:
            return await self._run_dispatched(
                identity=identity,
                registered=registered,
                projection=projection,
                lease=lease,
                accepted_at=accepted_at,
            )
        finally:
            lease.release()

    async def _run_dispatched(
        self,
        *,
        identity: _RunIdentity,
        registered: RegisteredAgentProfile,
        projection,
        lease: SchedulerLease,
        accepted_at: float,
    ) -> AgentRunResult:
        task = identity.task
        provider_started_at = self._monotonic()
        if provider_started_at >= task.deadline_monotonic_s:
            result = self._failure_result(
                identity=identity,
                model_id=registered.profile.model_config_ref,
                code=CoreFailureCode.HARD_TIMEOUT,
                message="agent task exceeded its hard deadline before provider dispatch",
                accepted_at=accepted_at,
                queue_ms=lease.queue_ms,
                completed_at=provider_started_at,
            )
            self._emit_result(identity, result)
            return result

        self._emit(
            CoreTraceEventType.PROVIDER_STARTED,
            identity,
            occurred_at=provider_started_at,
            model_id=registered.profile.model_config_ref,
            queue_ms=lease.queue_ms,
        )
        invocation = ModelInvocation(
            model_config_ref=registered.profile.model_config_ref,
            request=projection,
        )
        remaining_s = task.deadline_monotonic_s - provider_started_at
        try:
            response = await asyncio.wait_for(
                self._model_runner.run(invocation),
                timeout=remaining_s,
            )
        except asyncio.TimeoutError:
            return self._provider_failure(
                identity=identity,
                registered=registered,
                code=CoreFailureCode.HARD_TIMEOUT,
                message="agent task exceeded its hard deadline",
                accepted_at=accepted_at,
                lease=lease,
                provider_started_at=provider_started_at,
            )
        except asyncio.CancelledError:
            return self._provider_failure(
                identity=identity,
                registered=registered,
                code=CoreFailureCode.CANCELLED,
                message="model provider request was cancelled",
                accepted_at=accepted_at,
                lease=lease,
                provider_started_at=provider_started_at,
            )
        except Exception:
            return self._provider_failure(
                identity=identity,
                registered=registered,
                code=CoreFailureCode.PROVIDER_ERROR,
                message="model provider request failed",
                accepted_at=accepted_at,
                lease=lease,
                provider_started_at=provider_started_at,
            )

        provider_completed_at = self._monotonic()
        provider_ms = max(0.0, (provider_completed_at - provider_started_at) * 1_000)
        self._emit(
            CoreTraceEventType.PROVIDER_COMPLETED,
            identity,
            occurred_at=provider_completed_at,
            model_id=response.model_id,
            queue_ms=lease.queue_ms,
            provider_ms=provider_ms,
        )
        if provider_completed_at >= task.deadline_monotonic_s:
            result = self._failure_result(
                identity=identity,
                model_id=response.model_id,
                code=CoreFailureCode.HARD_TIMEOUT,
                message="agent task exceeded its hard deadline",
                accepted_at=accepted_at,
                queue_ms=lease.queue_ms,
                provider_started_at=provider_started_at,
                provider_completed_at=provider_completed_at,
            )
            self._emit_result(identity, result)
            return result

        parse_started_at = self._monotonic()
        try:
            intent = self._terminal_decoder(response, registered)
        except TerminalResponseError as exc:
            completed_at = self._monotonic()
            result = self._failure_result(
                identity=identity,
                model_id=response.model_id,
                code=exc.code,
                message=str(exc),
                accepted_at=accepted_at,
                queue_ms=lease.queue_ms,
                provider_started_at=provider_started_at,
                provider_completed_at=provider_completed_at,
                parse_started_at=parse_started_at,
                completed_at=completed_at,
            )
            self._emit(
                CoreTraceEventType.TERMINAL_VALIDATED,
                identity,
                occurred_at=completed_at,
                model_id=response.model_id,
                latency=result.latency,
                failure_code=exc.code,
            )
            self._emit_result(identity, result)
            return result

        completed_at = self._monotonic()
        preliminary_latency = self._latency(
            accepted_at=accepted_at,
            queue_ms=lease.queue_ms,
            provider_started_at=provider_started_at,
            provider_completed_at=provider_completed_at,
            parse_started_at=parse_started_at,
            completed_at=completed_at,
        )
        self._emit(
            CoreTraceEventType.TERMINAL_VALIDATED,
            identity,
            occurred_at=completed_at,
            model_id=response.model_id,
            latency=preliminary_latency,
            terminal_tool=intent.tool_name,
        )
        if completed_at >= task.deadline_monotonic_s:
            result = self._failure_result(
                identity=identity,
                model_id=response.model_id,
                code=CoreFailureCode.HARD_TIMEOUT,
                message="agent task exceeded its hard deadline",
                accepted_at=accepted_at,
                queue_ms=lease.queue_ms,
                provider_started_at=provider_started_at,
                provider_completed_at=provider_completed_at,
                parse_started_at=parse_started_at,
                completed_at=completed_at,
            )
            self._emit_result(identity, result)
            return result

        result = self._success_result(
            identity=identity,
            registered=registered,
            response=response,
            intent=intent,
            accepted_at=accepted_at,
            queue_ms=lease.queue_ms,
            provider_started_at=provider_started_at,
            provider_completed_at=provider_completed_at,
            parse_started_at=parse_started_at,
            completed_at=completed_at,
        )
        self._emit_result(identity, result)
        return result

    def _provider_failure(
        self,
        *,
        identity: _RunIdentity,
        registered: RegisteredAgentProfile,
        code: CoreFailureCode,
        message: str,
        accepted_at: float,
        lease: SchedulerLease,
        provider_started_at: float,
    ) -> AgentRunResult:
        completed_at = self._monotonic()
        result = self._failure_result(
            identity=identity,
            model_id=registered.profile.model_config_ref,
            code=code,
            message=message,
            accepted_at=accepted_at,
            queue_ms=lease.queue_ms,
            provider_started_at=provider_started_at,
            completed_at=completed_at,
        )
        self._emit(
            CoreTraceEventType.PROVIDER_COMPLETED,
            identity,
            occurred_at=completed_at,
            model_id=registered.profile.model_config_ref,
            latency=result.latency,
            failure_code=code,
        )
        self._emit_result(identity, result)
        return result

    @staticmethod
    def _correlation_id(task: AgentTask, key: str) -> Optional[str]:
        candidate = task.correlation_metadata.to_dict().get(key)
        if isinstance(candidate, str) and _ENTITY_ID.fullmatch(candidate):
            return candidate
        return None

    def _success_result(
        self,
        *,
        identity: _RunIdentity,
        registered: RegisteredAgentProfile,
        response: ModelResponse,
        intent: TerminalIntent,
        accepted_at: float,
        queue_ms: float,
        provider_started_at: float,
        provider_completed_at: float,
        parse_started_at: float,
        completed_at: float,
    ) -> AgentRunResult:
        return AgentRunResult(
            task_id=identity.task.task_id,
            adapter_id=registered.profile.adapter_id,
            profile_version=registered.profile.profile_version,
            profile_digest=registered.digest,
            run_id=identity.run_id,
            trace_id=identity.trace_id,
            model_id=response.model_id,
            status=RunStatus.SUCCEEDED,
            terminal_intent=intent,
            latency=self._latency(
                accepted_at=accepted_at,
                queue_ms=queue_ms,
                provider_started_at=provider_started_at,
                provider_completed_at=provider_completed_at,
                parse_started_at=parse_started_at,
                completed_at=completed_at,
            ),
            completed_monotonic_s=completed_at,
        )

    def _failure_result(
        self,
        *,
        identity: _RunIdentity,
        model_id: str,
        code: CoreFailureCode,
        message: str,
        accepted_at: float,
        queue_ms: float = 0.0,
        provider_started_at: Optional[float] = None,
        provider_completed_at: Optional[float] = None,
        parse_started_at: Optional[float] = None,
        completed_at: Optional[float] = None,
    ) -> AgentRunResult:
        if completed_at is None:
            completed_at = self._monotonic()
        return AgentRunResult(
            task_id=identity.task.task_id,
            adapter_id=identity.task.adapter_id,
            profile_version=identity.task.profile_version,
            profile_digest=identity.task.profile_digest,
            run_id=identity.run_id,
            trace_id=identity.trace_id,
            model_id=model_id,
            status=RunStatus.FAILED,
            failure=CoreFailure(code=code, message=message),
            latency=self._latency(
                accepted_at=accepted_at,
                queue_ms=queue_ms,
                provider_started_at=provider_started_at,
                provider_completed_at=provider_completed_at,
                parse_started_at=parse_started_at,
                completed_at=completed_at,
            ),
            completed_monotonic_s=completed_at,
        )

    @staticmethod
    def _latency(
        *,
        accepted_at: float,
        queue_ms: float,
        provider_started_at: Optional[float],
        provider_completed_at: Optional[float],
        parse_started_at: Optional[float],
        completed_at: float,
    ) -> LatencyBreakdown:
        provider_ms = 0.0
        if provider_started_at is not None:
            provider_end = provider_completed_at if provider_completed_at is not None else completed_at
            provider_ms = max(0.0, (provider_end - provider_started_at) * 1_000)
        parse_ms = 0.0
        if parse_started_at is not None:
            parse_ms = max(0.0, (completed_at - parse_started_at) * 1_000)
        total_ms = max(0.0, (completed_at - accepted_at) * 1_000)
        total_ms = max(total_ms, queue_ms + provider_ms + parse_ms)
        return LatencyBreakdown(
            queue_ms=queue_ms,
            provider_ms=provider_ms,
            parse_ms=parse_ms,
            total_ms=total_ms,
        )

    def _emit_result(self, identity: _RunIdentity, result: AgentRunResult) -> None:
        self._emit(
            CoreTraceEventType.RUN_COMPLETED
            if result.status is RunStatus.SUCCEEDED
            else CoreTraceEventType.RUN_FAILED,
            identity,
            occurred_at=result.completed_monotonic_s,
            model_id=result.model_id,
            latency=result.latency,
            terminal_tool=(
                result.terminal_intent.tool_name
                if result.terminal_intent is not None
                else None
            ),
            failure_code=result.failure.code if result.failure is not None else None,
        )

    def _emit(
        self,
        event_type: CoreTraceEventType,
        identity: _RunIdentity,
        *,
        occurred_at: float,
        model_id: Optional[str] = None,
        queue_ms: float = 0.0,
        provider_ms: float = 0.0,
        latency: Optional[LatencyBreakdown] = None,
        terminal_tool: Optional[str] = None,
        failure_code: Optional[CoreFailureCode] = None,
    ) -> None:
        if latency is not None:
            queue_ms = latency.queue_ms
            provider_ms = latency.provider_ms
            parse_ms = latency.parse_ms
            total_ms = latency.total_ms
        else:
            parse_ms = 0.0
            total_ms = max(queue_ms + provider_ms, 0.0)
        self._trace.emit(
            CoreTraceEvent(
                event_type=event_type,
                task_id=identity.task.task_id,
                adapter_id=identity.task.adapter_id,
                profile_version=identity.task.profile_version,
                profile_digest=identity.task.profile_digest,
                run_id=identity.run_id,
                trace_id=identity.trace_id,
                scenario_id=identity.scenario_id,
                model_id=model_id,
                occurred_monotonic_s=max(0.0, occurred_at),
                queue_ms=queue_ms,
                provider_ms=provider_ms,
                parse_ms=parse_ms,
                total_ms=total_ms,
                terminal_tool=terminal_tool,
                failure_code=failure_code,
            )
        )
