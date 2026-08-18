from __future__ import annotations

import asyncio
import time

import pytest

from sidestage.agent_core import (
    AgentProfile,
    AgentProfileRegistry,
    AgentTask,
    CoreFailureCode,
    DeadlinePolicy,
    QueuePolicy,
    TerminalIntent,
    TerminalToolSchema,
    register_profile,
)
from sidestage.agent_core.core import StaticAgentCore
from sidestage.agent_core.model import ModelInvocation, ModelResponse, ModelTerminalCall


def make_profile() -> AgentProfile:
    return AgentProfile(
        adapter_id="generic.deadline",
        profile_version="1.0.0",
        system_policy="Return one terminal result.",
        input_schema={
            "type": "object",
            "properties": {"label": {"type": "string"}},
            "required": ["label"],
            "additionalProperties": False,
        },
        terminal_tools=(
            TerminalToolSchema(
                name="finish",
                description="Finish one task.",
                parameters_schema={
                    "type": "object",
                    "properties": {"label": {"type": "string"}},
                    "required": ["label"],
                    "additionalProperties": False,
                },
            ),
        ),
        queue_policy=QueuePolicy(capacity=3, max_concurrency=1),
        deadline_policy=DeadlinePolicy(default_timeout_ms=1_000, max_timeout_ms=5_000),
        model_config_ref="scripted-deadline-v1",
        max_model_input_bytes=1_024,
    )


def make_task(
    profile: AgentProfile,
    label: str,
    *,
    deadline_monotonic_s: float,
) -> AgentTask:
    return AgentTask(
        task_id=f"task-{label}",
        adapter_id=profile.adapter_id,
        profile_version=profile.profile_version,
        profile_digest=register_profile(profile).digest,
        deadline_monotonic_s=deadline_monotonic_s,
        model_input={"label": label},
        correlation_metadata={"trace_id": f"trace-{label}"},
    )


def success_response(label: str) -> ModelResponse:
    return ModelResponse(
        model_id="scripted-deadline-model-v1",
        terminal_calls=(
            ModelTerminalCall(
                tool_name="finish",
                arguments_json=f'{{"label":"{label}"}}',
            ),
        ),
    )


class BlockingRunner:
    def __init__(self) -> None:
        self.calls: list[ModelInvocation] = []
        self.started: asyncio.Queue[str] = asyncio.Queue()
        self.release = asyncio.Event()
        self.cancelled = False

    async def run(self, invocation: ModelInvocation) -> ModelResponse:
        label = invocation.request.model_input.to_dict()["label"]
        self.calls.append(invocation)
        await self.started.put(label)
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return success_response(label)


def make_core(profile: AgentProfile, runner, **kwargs) -> StaticAgentCore:
    identifiers = (f"run-deadline-{index}" for index in range(1, 20))
    return StaticAgentCore(
        registry=AgentProfileRegistry((profile,)),
        model_runner=runner,
        id_factory=lambda: next(identifiers),
        **kwargs,
    )


def test_deadline_expiring_while_queued_starts_zero_provider_work_for_that_task() -> None:
    async def scenario() -> None:
        profile = make_profile()
        runner = BlockingRunner()
        core = make_core(profile, runner)
        now = time.monotonic()

        active = asyncio.create_task(
            core.run(make_task(profile, "active", deadline_monotonic_s=now + 1.0))
        )
        assert await runner.started.get() == "active"
        queued = await core.run(
            make_task(profile, "queued", deadline_monotonic_s=time.monotonic() + 0.02)
        )

        assert queued.failure is not None
        assert queued.failure.code is CoreFailureCode.HARD_TIMEOUT
        assert len(runner.calls) == 1
        runner.release.set()
        await active

    asyncio.run(scenario())


def test_cancelling_queued_work_returns_typed_failure_and_does_not_leak_a_slot() -> None:
    async def scenario() -> None:
        profile = make_profile()
        runner = BlockingRunner()
        core = make_core(profile, runner)
        now = time.monotonic()

        active = asyncio.create_task(
            core.run(make_task(profile, "active", deadline_monotonic_s=now + 2.0))
        )
        assert await runner.started.get() == "active"
        queued_task = asyncio.create_task(
            core.run(make_task(profile, "cancelled", deadline_monotonic_s=now + 2.0))
        )
        await asyncio.sleep(0)
        queued_task.cancel()
        cancelled = await queued_task

        assert cancelled.failure is not None
        assert cancelled.failure.code is CoreFailureCode.CANCELLED
        assert len(runner.calls) == 1

        runner.release.set()
        await active

        runner.release = asyncio.Event()
        successor = asyncio.create_task(
            core.run(
                make_task(
                    profile,
                    "successor",
                    deadline_monotonic_s=time.monotonic() + 1.0,
                )
            )
        )
        assert await runner.started.get() == "successor"
        runner.release.set()
        assert (await successor).terminal_intent is not None

    asyncio.run(scenario())


def test_deadline_crossed_during_terminal_parsing_discards_the_intent() -> None:
    class FakeClock:
        def __init__(self) -> None:
            self.value = 100.0

        def __call__(self) -> float:
            return self.value

    class AdvancingRunner:
        def __init__(self, clock: FakeClock) -> None:
            self.clock = clock
            self.calls: list[ModelInvocation] = []

        async def run(self, invocation: ModelInvocation) -> ModelResponse:
            self.calls.append(invocation)
            self.clock.value = 100.05
            return success_response("parse")

    clock = FakeClock()
    profile = make_profile()
    runner = AdvancingRunner(clock)

    def terminal_decoder(response, registered) -> TerminalIntent:
        del response, registered
        clock.value = 100.2
        return TerminalIntent(tool_name="finish", arguments={"label": "parse"})

    core = make_core(
        profile,
        runner,
        monotonic=clock,
        terminal_decoder=terminal_decoder,
    )
    result = asyncio.run(
        core.run(make_task(profile, "parse", deadline_monotonic_s=100.1))
    )

    assert result.failure is not None
    assert result.failure.code is CoreFailureCode.HARD_TIMEOUT
    assert result.terminal_intent is None
    assert len(runner.calls) == 1
    assert result.latency.provider_ms == pytest.approx(50.0)
    assert result.latency.parse_ms == pytest.approx(150.0)
    assert result.latency.total_ms == pytest.approx(200.0)


def test_cancelling_in_flight_work_releases_capacity_for_the_next_task() -> None:
    async def scenario() -> None:
        profile = make_profile()
        runner = BlockingRunner()
        core = make_core(profile, runner)

        active = asyncio.create_task(
            core.run(
                make_task(
                    profile,
                    "active",
                    deadline_monotonic_s=time.monotonic() + 2.0,
                )
            )
        )
        assert await runner.started.get() == "active"
        active.cancel()
        cancelled = await active

        assert cancelled.failure is not None
        assert cancelled.failure.code is CoreFailureCode.CANCELLED
        assert runner.cancelled is True

        runner.cancelled = False
        runner.release = asyncio.Event()
        successor = asyncio.create_task(
            core.run(
                make_task(
                    profile,
                    "successor",
                    deadline_monotonic_s=time.monotonic() + 1.0,
                )
            )
        )
        assert await runner.started.get() == "successor"
        runner.release.set()
        assert (await successor).terminal_intent is not None

    asyncio.run(scenario())
