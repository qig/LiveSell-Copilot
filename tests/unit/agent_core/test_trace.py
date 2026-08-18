from __future__ import annotations

import asyncio
import json
import time

from sidestage.agent_core import (
    AgentProfile,
    AgentProfileRegistry,
    AgentTask,
    CoreFailureCode,
    CoreTraceEventType,
    DeadlinePolicy,
    InMemoryTraceSink,
    QueuePolicy,
    TerminalToolSchema,
    register_profile,
)
from sidestage.agent_core.core import StaticAgentCore
from sidestage.agent_core.model import ModelResponse, ModelTerminalCall, ScriptedModelRunner


def make_profile() -> AgentProfile:
    return AgentProfile(
        adapter_id="generic.trace",
        profile_version="1.0.0",
        system_policy="Never expose trace authority; return one result.",
        input_schema={
            "type": "object",
            "properties": {"prompt": {"type": "string"}},
            "required": ["prompt"],
            "additionalProperties": False,
        },
        terminal_tools=(
            TerminalToolSchema(
                name="finish",
                description="Finish generically.",
                parameters_schema={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                    "additionalProperties": False,
                },
            ),
        ),
        queue_policy=QueuePolicy(capacity=2, max_concurrency=1),
        deadline_policy=DeadlinePolicy(default_timeout_ms=1_000, max_timeout_ms=5_000),
        model_config_ref="scripted-trace-v1",
        max_model_input_bytes=1_024,
    )


def make_task(profile: AgentProfile) -> AgentTask:
    return AgentTask(
        task_id="task-trace-1",
        adapter_id=profile.adapter_id,
        profile_version=profile.profile_version,
        profile_digest=register_profile(profile).digest,
        deadline_monotonic_s=time.monotonic() + 2.0,
        model_input={"prompt": "private model-visible prompt"},
        correlation_metadata={
            "trace_id": "trace-core-1",
            "scenario_id": "scenario-core-1",
            "effect_id": "effect-never-traced",
            "authorization_version": 7,
        },
    )


def success_response() -> ModelResponse:
    return ModelResponse(
        model_id="scripted-trace-model-v1",
        terminal_calls=(
            ModelTerminalCall(
                tool_name="finish",
                arguments_json='{"answer":"private terminal output"}',
            ),
        ),
    )


def make_core(profile: AgentProfile, runner, sink) -> StaticAgentCore:
    return StaticAgentCore(
        registry=AgentProfileRegistry((profile,)),
        model_runner=runner,
        trace_sink=sink,
        id_factory=lambda: "run-core-1",
    )


def test_success_trace_has_exact_adapter_neutral_lifecycle_and_correlations() -> None:
    profile = make_profile()
    sink = InMemoryTraceSink()
    result = asyncio.run(
        make_core(
            profile,
            ScriptedModelRunner((success_response(),)),
            sink,
        ).run(make_task(profile))
    )

    assert [event.event_type for event in sink.events] == [
        CoreTraceEventType.TASK_ACCEPTED,
        CoreTraceEventType.TASK_QUEUED,
        CoreTraceEventType.PROVIDER_STARTED,
        CoreTraceEventType.PROVIDER_COMPLETED,
        CoreTraceEventType.TERMINAL_VALIDATED,
        CoreTraceEventType.RUN_COMPLETED,
    ]
    for event in sink.events:
        assert event.task_id == result.task_id
        assert event.adapter_id == result.adapter_id
        assert event.profile_version == result.profile_version
        assert event.profile_digest == result.profile_digest
        assert event.run_id == result.run_id
        assert event.trace_id == result.trace_id
        assert event.scenario_id == "scenario-core-1"

    final = sink.events[-1]
    assert final.model_id == result.model_id
    assert final.terminal_tool == "finish"
    assert final.queue_ms == result.latency.queue_ms
    assert final.provider_ms == result.latency.provider_ms
    assert final.parse_ms == result.latency.parse_ms
    assert final.total_ms == result.latency.total_ms

    serialized = json.dumps([event.model_dump(mode="json") for event in sink.events])
    for forbidden in (
        "private model-visible prompt",
        "private terminal output",
        "effect-never-traced",
        "authorization_version",
        profile.system_policy,
    ):
        assert forbidden not in serialized


def test_terminal_failure_is_traced_without_echoing_provider_payload() -> None:
    profile = make_profile()
    sink = InMemoryTraceSink()
    result = asyncio.run(
        make_core(
            profile,
            ScriptedModelRunner(
                (
                    ModelResponse(
                        model_id="scripted-trace-model-v1",
                        terminal_calls=(
                            ModelTerminalCall(
                                tool_name="finish",
                                arguments_json='{"answer":7,"secret_text":"do-not-echo"}',
                            ),
                        ),
                    ),
                )
            ),
            sink,
        ).run(make_task(profile))
    )

    assert result.failure is not None
    assert result.failure.code is CoreFailureCode.MALFORMED_ARGUMENTS
    assert sink.events[-2].event_type is CoreTraceEventType.TERMINAL_VALIDATED
    assert sink.events[-2].failure_code is CoreFailureCode.MALFORMED_ARGUMENTS
    assert sink.events[-1].event_type is CoreTraceEventType.RUN_FAILED
    assert sink.events[-1].failure_code is CoreFailureCode.MALFORMED_ARGUMENTS
    assert "do-not-echo" not in json.dumps(
        [event.model_dump(mode="json") for event in sink.events]
    )


def test_provider_failure_closes_the_provider_boundary_and_run_trace() -> None:
    profile = make_profile()
    sink = InMemoryTraceSink()
    result = asyncio.run(
        make_core(
            profile,
            ScriptedModelRunner((RuntimeError("private provider failure"),)),
            sink,
        ).run(make_task(profile))
    )

    assert result.failure is not None
    assert result.failure.code is CoreFailureCode.PROVIDER_ERROR
    assert [event.event_type for event in sink.events] == [
        CoreTraceEventType.TASK_ACCEPTED,
        CoreTraceEventType.TASK_QUEUED,
        CoreTraceEventType.PROVIDER_STARTED,
        CoreTraceEventType.PROVIDER_COMPLETED,
        CoreTraceEventType.RUN_FAILED,
    ]
    assert sink.events[-2].failure_code is CoreFailureCode.PROVIDER_ERROR
    assert sink.events[-1].failure_code is CoreFailureCode.PROVIDER_ERROR
    assert "private provider failure" not in json.dumps(
        [event.model_dump(mode="json") for event in sink.events]
    )


def test_trace_sink_failure_cannot_change_result_or_trigger_an_effect() -> None:
    class ExplodingTraceSink:
        def __init__(self) -> None:
            self.calls = 0
            self.effect_calls: list[object] = []

        def emit_nowait(self, event) -> None:
            self.calls += 1
            raise RuntimeError("trace storage unavailable")

        def execute_effect(self, payload: object) -> None:
            self.effect_calls.append(payload)

    profile = make_profile()
    sink = ExplodingTraceSink()
    runner = ScriptedModelRunner((success_response(),))

    result = asyncio.run(make_core(profile, runner, sink).run(make_task(profile)))

    assert result.terminal_intent is not None
    assert len(runner.calls) == 1
    assert sink.calls == 6
    assert sink.effect_calls == []


def test_queued_event_is_observable_before_provider_dispatch() -> None:
    class BlockingRunner:
        def __init__(self) -> None:
            self.started: asyncio.Queue[str] = asyncio.Queue()
            self.releases: dict[str, asyncio.Event] = {}

        async def run(self, invocation):
            prompt = invocation.request.model_input.to_dict()["prompt"]
            release = self.releases.setdefault(prompt, asyncio.Event())
            await self.started.put(prompt)
            await release.wait()
            return success_response()

    async def scenario() -> None:
        profile = make_profile()
        sink = InMemoryTraceSink()
        runner = BlockingRunner()
        identifiers = (f"run-queued-{index}" for index in range(1, 10))
        core = StaticAgentCore(
            registry=AgentProfileRegistry((profile,)),
            model_runner=runner,
            trace_sink=sink,
            id_factory=lambda: next(identifiers),
        )
        first_task = make_task(profile)
        second_payload = first_task.model_dump()
        second_payload.update(
            task_id="task-trace-2",
            model_input={"prompt": "second prompt"},
            correlation_metadata={
                "trace_id": "trace-core-2",
                "scenario_id": "scenario-core-1",
            },
        )
        second_task = AgentTask.model_validate(second_payload)

        first = asyncio.create_task(core.run(first_task))
        assert await runner.started.get() == "private model-visible prompt"
        second = asyncio.create_task(core.run(second_task))
        await asyncio.sleep(0)

        second_events = [event.event_type for event in sink.events if event.task_id == "task-trace-2"]
        assert second_events == [
            CoreTraceEventType.TASK_ACCEPTED,
            CoreTraceEventType.TASK_QUEUED,
        ]

        runner.releases["private model-visible prompt"].set()
        assert await runner.started.get() == "second prompt"
        runner.releases["second prompt"].set()
        await asyncio.gather(first, second)

    asyncio.run(scenario())
