from __future__ import annotations

import asyncio
import time

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
from sidestage.agent_core.model import (
    ModelInvocation,
    ModelResponse,
    ModelTerminalCall,
    ScriptedModelRunner,
)


def make_profile() -> AgentProfile:
    return AgentProfile(
        adapter_id="generic.intent",
        profile_version="1.0.0",
        system_policy="Return one intent; never perform it.",
        input_schema={
            "type": "object",
            "properties": {"instruction": {"type": "string"}},
            "required": ["instruction"],
            "additionalProperties": False,
        },
        terminal_tools=(
            TerminalToolSchema(
                name="request_effect",
                description="Describe a requested effect without executing it.",
                parameters_schema={
                    "type": "object",
                    "properties": {
                        "effect_name": {"type": "string"},
                        "payload": {"type": "string"},
                    },
                    "required": ["effect_name", "payload"],
                    "additionalProperties": False,
                },
            ),
        ),
        queue_policy=QueuePolicy(capacity=2, max_concurrency=1),
        deadline_policy=DeadlinePolicy(default_timeout_ms=1_000, max_timeout_ms=5_000),
        model_config_ref="scripted-intent-v1",
        max_model_input_bytes=2_048,
    )


def make_task(profile: AgentProfile) -> AgentTask:
    now = time.monotonic()
    return AgentTask(
        task_id="effect-isolation-task",
        adapter_id=profile.adapter_id,
        profile_version=profile.profile_version,
        profile_digest=register_profile(profile).digest,
        deadline_monotonic_s=now + 2.0,
        model_input={"instruction": "Describe the requested operation"},
        correlation_metadata={"trace_id": "effect-isolation-trace"},
    )


class ModelAndEffectSpy:
    """A runner that would expose an effect if the core tried to discover one."""

    def __init__(self, response: ModelResponse) -> None:
        self.response = response
        self.model_calls: list[ModelInvocation] = []
        self.effect_calls: list[dict] = []

    async def run(self, invocation: ModelInvocation) -> ModelResponse:
        self.model_calls.append(invocation)
        return self.response

    def execute_effect(self, payload: dict) -> None:
        self.effect_calls.append(payload)


def make_core(profile: AgentProfile, runner) -> StaticAgentCore:
    identifiers = iter(("effect-run-1", "effect-trace-generated-1"))
    return StaticAgentCore(
        registry=AgentProfileRegistry((profile,)),
        model_runner=runner,
        id_factory=lambda: next(identifiers),
    )


def test_core_returns_intent_data_without_invoking_effect_spy() -> None:
    profile = make_profile()
    runner = ModelAndEffectSpy(
        ModelResponse(
            model_id="scripted-intent-v1",
            terminal_calls=(
                ModelTerminalCall(
                    tool_name="request_effect",
                    arguments_json=(
                        '{"effect_name":"send_message",'
                        '"payload":"This is intent data only"}'
                    ),
                ),
            ),
        ),
    )

    result = asyncio.run(make_core(profile, runner).run(make_task(profile)))

    assert result.terminal_intent is not None
    assert result.terminal_intent.arguments.to_dict() == {
        "effect_name": "send_message",
        "payload": "This is intent data only",
    }
    assert len(runner.model_calls) == 1
    assert runner.effect_calls == []
    assert "effect_executed" not in result.model_dump()


def test_invalid_terminal_intent_performs_no_effect_and_no_second_round() -> None:
    profile = make_profile()
    runner = ScriptedModelRunner(
        (
            ModelResponse(
                model_id="scripted-intent-v1",
                terminal_calls=(
                    ModelTerminalCall(
                        tool_name="request_effect",
                        arguments_json='{"effect_name":"send_message"}',
                    ),
                ),
            ),
        )
    )

    result = asyncio.run(make_core(profile, runner).run(make_task(profile)))

    assert result.failure is not None
    assert result.failure.code is CoreFailureCode.MALFORMED_ARGUMENTS
    assert result.terminal_intent is None
    assert len(runner.calls) == 1
