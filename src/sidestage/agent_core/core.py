"""One-request, no-effect static agent core."""

from __future__ import annotations

import asyncio
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
from sidestage.agent_core.terminal import TerminalResponseError, decode_terminal_response


_ENTITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


def _new_id() -> str:
    return uuid4().hex


class StaticAgentCore:
    """Validate once, call one model once, return intent data without effects."""

    def __init__(
        self,
        *,
        registry: AgentProfileRegistry,
        model_runner: ModelRunner,
        monotonic: Callable[[], float] = time.monotonic,
        id_factory: Callable[[], str] = _new_id,
    ) -> None:
        self._registry = registry
        self._model_runner = model_runner
        self._monotonic = monotonic
        self._id_factory = id_factory

    async def run(self, task: AgentTask) -> AgentRunResult:
        started_at = self._monotonic()
        run_id = self._id_factory()
        trace_id = self._trace_id(task)

        try:
            registered = self._registry.resolve(
                task.adapter_id,
                task.profile_version,
                task.profile_digest,
            )
        except UnknownAgentProfileError:
            return self._failure_result(
                task=task,
                run_id=run_id,
                trace_id=trace_id,
                model_id="not-invoked",
                code=CoreFailureCode.INVALID_PROFILE,
                message="task references an unknown startup profile",
                started_at=started_at,
            )

        try:
            projection = registered.project_model_request(
                task,
                now_monotonic_s=self._monotonic(),
            )
        except AgentTaskValidationError:
            return self._failure_result(
                task=task,
                run_id=run_id,
                trace_id=trace_id,
                model_id=registered.profile.model_config_ref,
                code=CoreFailureCode.INVALID_TASK,
                message="task failed startup profile validation",
                started_at=started_at,
            )

        remaining_s = task.deadline_monotonic_s - self._monotonic()
        if remaining_s <= 0:
            return self._failure_result(
                task=task,
                run_id=run_id,
                trace_id=trace_id,
                model_id=registered.profile.model_config_ref,
                code=CoreFailureCode.HARD_TIMEOUT,
                message="agent task exceeded its hard deadline",
                started_at=started_at,
            )

        invocation = ModelInvocation(
            model_config_ref=registered.profile.model_config_ref,
            request=projection,
        )
        provider_started_at = self._monotonic()
        remaining_s = task.deadline_monotonic_s - provider_started_at
        if remaining_s <= 0:
            return self._failure_result(
                task=task,
                run_id=run_id,
                trace_id=trace_id,
                model_id=registered.profile.model_config_ref,
                code=CoreFailureCode.HARD_TIMEOUT,
                message="agent task exceeded its hard deadline",
                started_at=started_at,
            )
        try:
            response = await asyncio.wait_for(
                self._model_runner.run(invocation),
                timeout=remaining_s,
            )
        except asyncio.TimeoutError:
            return self._failure_result(
                task=task,
                run_id=run_id,
                trace_id=trace_id,
                model_id=registered.profile.model_config_ref,
                code=CoreFailureCode.HARD_TIMEOUT,
                message="agent task exceeded its hard deadline",
                started_at=started_at,
                provider_started_at=provider_started_at,
            )
        except asyncio.CancelledError:
            return self._failure_result(
                task=task,
                run_id=run_id,
                trace_id=trace_id,
                model_id=registered.profile.model_config_ref,
                code=CoreFailureCode.CANCELLED,
                message="model provider request was cancelled",
                started_at=started_at,
                provider_started_at=provider_started_at,
            )
        except Exception:
            return self._failure_result(
                task=task,
                run_id=run_id,
                trace_id=trace_id,
                model_id=registered.profile.model_config_ref,
                code=CoreFailureCode.PROVIDER_ERROR,
                message="model provider request failed",
                started_at=started_at,
                provider_started_at=provider_started_at,
            )

        provider_completed_at = self._monotonic()
        if provider_completed_at >= task.deadline_monotonic_s:
            return self._failure_result(
                task=task,
                run_id=run_id,
                trace_id=trace_id,
                model_id=response.model_id,
                code=CoreFailureCode.HARD_TIMEOUT,
                message="agent task exceeded its hard deadline",
                started_at=started_at,
                provider_started_at=provider_started_at,
                provider_completed_at=provider_completed_at,
            )

        parse_started_at = self._monotonic()
        try:
            intent = decode_terminal_response(response, registered)
        except TerminalResponseError as exc:
            return self._failure_result(
                task=task,
                run_id=run_id,
                trace_id=trace_id,
                model_id=response.model_id,
                code=exc.code,
                message=str(exc),
                started_at=started_at,
                provider_started_at=provider_started_at,
                provider_completed_at=provider_completed_at,
                parse_started_at=parse_started_at,
            )

        completed_at = self._monotonic()
        if completed_at >= task.deadline_monotonic_s:
            return self._failure_result(
                task=task,
                run_id=run_id,
                trace_id=trace_id,
                model_id=response.model_id,
                code=CoreFailureCode.HARD_TIMEOUT,
                message="agent task exceeded its hard deadline",
                started_at=started_at,
                provider_started_at=provider_started_at,
                provider_completed_at=provider_completed_at,
                parse_started_at=parse_started_at,
                completed_at=completed_at,
            )
        return self._success_result(
            task=task,
            registered=registered,
            response=response,
            intent=intent,
            run_id=run_id,
            trace_id=trace_id,
            started_at=started_at,
            provider_started_at=provider_started_at,
            provider_completed_at=provider_completed_at,
            parse_started_at=parse_started_at,
            completed_at=completed_at,
        )

    def _trace_id(self, task: AgentTask) -> str:
        candidate = task.correlation_metadata.to_dict().get("trace_id")
        if isinstance(candidate, str) and _ENTITY_ID.fullmatch(candidate):
            return candidate
        return self._id_factory()

    def _success_result(
        self,
        *,
        task: AgentTask,
        registered: RegisteredAgentProfile,
        response: ModelResponse,
        intent: TerminalIntent,
        run_id: str,
        trace_id: str,
        started_at: float,
        provider_started_at: float,
        provider_completed_at: float,
        parse_started_at: float,
        completed_at: float,
    ) -> AgentRunResult:
        return AgentRunResult(
            task_id=task.task_id,
            adapter_id=registered.profile.adapter_id,
            profile_version=registered.profile.profile_version,
            profile_digest=registered.digest,
            run_id=run_id,
            trace_id=trace_id,
            model_id=response.model_id,
            status=RunStatus.SUCCEEDED,
            terminal_intent=intent,
            latency=self._latency(
                started_at=started_at,
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
        task: AgentTask,
        run_id: str,
        trace_id: str,
        model_id: str,
        code: CoreFailureCode,
        message: str,
        started_at: float,
        provider_started_at: Optional[float] = None,
        provider_completed_at: Optional[float] = None,
        parse_started_at: Optional[float] = None,
        completed_at: Optional[float] = None,
    ) -> AgentRunResult:
        if completed_at is None:
            completed_at = self._monotonic()
        return AgentRunResult(
            task_id=task.task_id,
            adapter_id=task.adapter_id,
            profile_version=task.profile_version,
            profile_digest=task.profile_digest,
            run_id=run_id,
            trace_id=trace_id,
            model_id=model_id,
            status=RunStatus.FAILED,
            failure=CoreFailure(code=code, message=message),
            latency=self._latency(
                started_at=started_at,
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
        started_at: float,
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
        total_ms = max(0.0, (completed_at - started_at) * 1_000)
        total_ms = max(total_ms, provider_ms + parse_ms)
        return LatencyBreakdown(
            queue_ms=0.0,
            provider_ms=provider_ms,
            parse_ms=parse_ms,
            total_ms=total_ms,
        )
