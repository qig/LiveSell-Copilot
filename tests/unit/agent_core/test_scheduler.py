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
    TerminalToolSchema,
    register_profile,
)
from sidestage.agent_core.core import StaticAgentCore
from sidestage.agent_core.model import ModelInvocation, ModelResponse, ModelTerminalCall


def make_profile(
    *,
    capacity: int,
    max_concurrency: int,
    adapter_id: str = "generic.scheduler",
) -> AgentProfile:
    return AgentProfile(
        adapter_id=adapter_id,
        profile_version="1.0.0",
        system_policy="Return exactly one result.",
        input_schema={
            "type": "object",
            "properties": {"label": {"type": "string", "minLength": 1}},
            "required": ["label"],
            "additionalProperties": False,
        },
        terminal_tools=(
            TerminalToolSchema(
                name="finish",
                description="Finish one generic task.",
                parameters_schema={
                    "type": "object",
                    "properties": {"label": {"type": "string", "minLength": 1}},
                    "required": ["label"],
                    "additionalProperties": False,
                },
            ),
        ),
        queue_policy=QueuePolicy(
            capacity=capacity,
            max_concurrency=max_concurrency,
        ),
        deadline_policy=DeadlinePolicy(default_timeout_ms=1_000, max_timeout_ms=5_000),
        model_config_ref="scripted-scheduler-v1",
        max_model_input_bytes=1_024,
    )


def make_task(profile: AgentProfile, label: str, *, timeout_s: float = 2.0) -> AgentTask:
    return AgentTask(
        task_id=f"task-{label}",
        adapter_id=profile.adapter_id,
        profile_version=profile.profile_version,
        profile_digest=register_profile(profile).digest,
        deadline_monotonic_s=time.monotonic() + timeout_s,
        model_input={"label": label},
        correlation_metadata={
            "trace_id": f"trace-{label}",
            "scenario_id": "scenario-scheduler",
        },
    )


def response(label: str) -> ModelResponse:
    return ModelResponse(
        model_id="scripted-scheduler-model-v1",
        terminal_calls=(
            ModelTerminalCall(
                tool_name="finish",
                arguments_json=f'{{"label":"{label}"}}',
            ),
        ),
    )


class ControlledRunner:
    def __init__(self) -> None:
        self.calls: list[ModelInvocation] = []
        self.started: asyncio.Queue[str] = asyncio.Queue()
        self.releases: dict[str, asyncio.Event] = {}

    async def run(self, invocation: ModelInvocation) -> ModelResponse:
        label = invocation.request.model_input.to_dict()["label"]
        self.calls.append(invocation)
        release = self.releases.setdefault(label, asyncio.Event())
        await self.started.put(label)
        await release.wait()
        return response(label)

    def release(self, label: str) -> None:
        self.releases[label].set()


def make_core(
    profile: AgentProfile,
    runner: ControlledRunner,
    *,
    monotonic=time.monotonic,
) -> StaticAgentCore:
    identifiers = (f"run-{index}" for index in range(1, 20))
    return StaticAgentCore(
        registry=AgentProfileRegistry((profile,)),
        model_runner=runner,
        monotonic=monotonic,
        id_factory=lambda: next(identifiers),
    )


def test_capacity_includes_active_and_waiting_tasks_and_rejects_without_provider_work() -> None:
    async def scenario() -> None:
        profile = make_profile(capacity=2, max_concurrency=1)
        runner = ControlledRunner()
        core = make_core(profile, runner)

        first = asyncio.create_task(core.run(make_task(profile, "first")))
        assert await runner.started.get() == "first"

        second = asyncio.create_task(core.run(make_task(profile, "second")))
        await asyncio.sleep(0)
        rejected = await core.run(make_task(profile, "third"))

        assert rejected.failure is not None
        assert rejected.failure.code is CoreFailureCode.QUEUE_FULL
        assert [call.request.model_input.to_dict()["label"] for call in runner.calls] == [
            "first"
        ]

        runner.release("first")
        assert await runner.started.get() == "second"
        runner.release("second")
        first_result, second_result = await asyncio.gather(first, second)

        assert first_result.terminal_intent is not None
        assert second_result.terminal_intent is not None
        assert [call.request.model_input.to_dict()["label"] for call in runner.calls] == [
            "first",
            "second",
        ]

    asyncio.run(scenario())


def test_fifo_dispatch_is_preserved_when_active_tasks_complete_out_of_order() -> None:
    async def scenario() -> None:
        profile = make_profile(capacity=4, max_concurrency=2)
        runner = ControlledRunner()
        core = make_core(profile, runner)

        tasks = [
            asyncio.create_task(core.run(make_task(profile, label)))
            for label in ("first", "second", "third", "fourth")
        ]
        assert [await runner.started.get(), await runner.started.get()] == ["first", "second"]

        runner.release("second")
        assert await runner.started.get() == "third"
        runner.release("first")
        assert await runner.started.get() == "fourth"
        runner.release("fourth")
        runner.release("third")

        results = await asyncio.gather(*tasks)
        assert [
            result.terminal_intent.arguments.to_dict()["label"]  # type: ignore[union-attr]
            for result in results
        ] == ["first", "second", "third", "fourth"]
        assert [call.request.model_input.to_dict()["label"] for call in runner.calls] == [
            "first",
            "second",
            "third",
            "fourth",
        ]

    asyncio.run(scenario())


def test_invalid_task_is_rejected_before_it_consumes_queue_capacity() -> None:
    async def scenario() -> None:
        profile = make_profile(capacity=1, max_concurrency=1)
        runner = ControlledRunner()
        core = make_core(profile, runner)
        invalid_payload = make_task(profile, "invalid").model_dump()
        invalid_payload["model_input"] = {"label": 7}
        invalid = AgentTask.model_validate(invalid_payload)

        invalid_result = await core.run(invalid)
        valid = asyncio.create_task(core.run(make_task(profile, "valid")))
        assert await runner.started.get() == "valid"
        runner.release("valid")
        valid_result = await valid

        assert invalid_result.failure is not None
        assert invalid_result.failure.code is CoreFailureCode.INVALID_TASK
        assert valid_result.terminal_intent is not None
        assert len(runner.calls) == 1

    asyncio.run(scenario())


def test_queue_latency_is_attributed_to_the_correct_out_of_order_run() -> None:
    class FakeClock:
        def __init__(self) -> None:
            self.value = 100.0

        def __call__(self) -> float:
            return self.value

    def task_at(profile: AgentProfile, label: str) -> AgentTask:
        return AgentTask(
            task_id=f"task-{label}",
            adapter_id=profile.adapter_id,
            profile_version=profile.profile_version,
            profile_digest=register_profile(profile).digest,
            deadline_monotonic_s=104.0,
            model_input={"label": label},
            correlation_metadata={"trace_id": f"trace-{label}"},
        )

    async def scenario() -> None:
        profile = make_profile(capacity=2, max_concurrency=1)
        clock = FakeClock()
        runner = ControlledRunner()
        core = make_core(profile, runner, monotonic=clock)

        first = asyncio.create_task(core.run(task_at(profile, "first")))
        assert await runner.started.get() == "first"
        second = asyncio.create_task(core.run(task_at(profile, "second")))
        await asyncio.sleep(0)

        clock.value = 100.05
        runner.release("first")
        assert await runner.started.get() == "second"
        runner.release("second")
        first_result, second_result = await asyncio.gather(first, second)

        assert first_result.latency.queue_ms == 0.0
        assert second_result.latency.queue_ms == pytest.approx(50.0)
        assert first_result.task_id == "task-first"
        assert second_result.task_id == "task-second"

    asyncio.run(scenario())


def test_saturated_profile_lane_does_not_block_another_registered_profile() -> None:
    async def scenario() -> None:
        first_profile = make_profile(
            capacity=1,
            max_concurrency=1,
            adapter_id="generic.scheduler.first",
        )
        second_profile = make_profile(
            capacity=1,
            max_concurrency=1,
            adapter_id="generic.scheduler.second",
        )
        runner = ControlledRunner()
        identifiers = (f"run-profile-{index}" for index in range(1, 20))
        core = StaticAgentCore(
            registry=AgentProfileRegistry((first_profile, second_profile)),
            model_runner=runner,
            id_factory=lambda: next(identifiers),
        )

        first = asyncio.create_task(core.run(make_task(first_profile, "first")))
        assert await runner.started.get() == "first"
        second = asyncio.create_task(core.run(make_task(second_profile, "second")))
        assert await runner.started.get() == "second"

        rejected = await core.run(make_task(first_profile, "first-overflow"))
        assert rejected.failure is not None
        assert rejected.failure.code is CoreFailureCode.QUEUE_FULL
        assert [
            call.request.model_input.to_dict()["label"] for call in runner.calls
        ] == ["first", "second"]

        runner.release("first")
        runner.release("second")
        first_result, second_result = await asyncio.gather(first, second)
        assert first_result.terminal_intent is not None
        assert second_result.terminal_intent is not None

    asyncio.run(scenario())
