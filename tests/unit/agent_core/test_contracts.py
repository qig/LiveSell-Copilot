from __future__ import annotations

import math
from typing import Optional

import pytest
from pydantic import ValidationError

from sidestage.agent_core.contracts import (
    AgentProfile,
    AgentRunResult,
    AgentTask,
    CoreFailure,
    CoreFailureCode,
    DeadlinePolicy,
    LatencyBreakdown,
    QueuePolicy,
    RunStatus,
    TerminalIntent,
    TerminalToolSchema,
)
from sidestage.agent_core.profile import register_profile


def make_profile(*, input_schema: Optional[dict] = None) -> AgentProfile:
    return AgentProfile(
        adapter_id="generic.qa",
        profile_version="1.0.0",
        system_policy="Use the supplied evidence and choose exactly one terminal tool.",
        input_schema=input_schema
        or {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "minLength": 1},
                "evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["prompt", "evidence"],
            "additionalProperties": False,
        },
        terminal_tools=(
            TerminalToolSchema(
                name="emit_answer",
                description="Return one evidence-backed answer.",
                parameters_schema={
                    "type": "object",
                    "properties": {"answer": {"type": "string", "minLength": 1}},
                    "required": ["answer"],
                    "additionalProperties": False,
                },
            ),
            TerminalToolSchema(
                name="abstain",
                description="Return a reason when no answer is supported.",
                parameters_schema={
                    "type": "object",
                    "properties": {"reason": {"type": "string", "minLength": 1}},
                    "required": ["reason"],
                    "additionalProperties": False,
                },
            ),
        ),
        queue_policy=QueuePolicy(capacity=8, max_concurrency=2),
        deadline_policy=DeadlinePolicy(default_timeout_ms=1_000, max_timeout_ms=5_000),
        model_config_ref="fast-primary-v1",
        max_model_input_bytes=1_024,
    )


def make_task(profile: AgentProfile) -> AgentTask:
    digest = register_profile(profile).digest
    return AgentTask(
        task_id="task-contract-1",
        adapter_id=profile.adapter_id,
        profile_version=profile.profile_version,
        profile_digest=digest,
        deadline_monotonic_s=105.0,
        model_input={"prompt": "What is supported?", "evidence": ["Fact A"]},
        correlation_metadata={"trace_id": "trace-contract-1"},
    )


def test_profile_and_task_are_deeply_immutable() -> None:
    source_schema = {
        "type": "object",
        "properties": {"prompt": {"type": "string"}},
    }
    profile = make_profile(input_schema=source_schema)
    task = make_task(profile)
    original_digest = register_profile(profile).digest

    source_schema["properties"]["prompt"]["type"] = "integer"

    assert register_profile(profile).digest == original_digest
    assert profile.input_schema.to_dict()["properties"]["prompt"]["type"] == "string"

    copied_input = task.model_input.to_dict()
    copied_input["prompt"] = "mutated"
    assert task.model_input.to_dict()["prompt"] == "What is supported?"

    with pytest.raises(ValidationError):
        profile.system_policy = "replacement"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        task.deadline_monotonic_s = 999.0  # type: ignore[misc]


@pytest.mark.parametrize("deadline", [0.0, -1.0, math.inf, math.nan])
def test_task_rejects_invalid_absolute_monotonic_deadline(deadline: float) -> None:
    profile = make_profile()
    payload = make_task(profile).model_dump()
    payload["deadline_monotonic_s"] = deadline

    with pytest.raises(ValidationError):
        AgentTask.model_validate(payload)


@pytest.mark.parametrize("field", ["api_key", "password", "secret", "access_token"])
def test_task_rejects_credentials_in_correlation_metadata(field: str) -> None:
    profile = make_profile()
    payload = make_task(profile).model_dump()
    payload["correlation_metadata"] = {field: "must-not-enter-the-task"}

    with pytest.raises(ValidationError, match="credential|secret"):
        AgentTask.model_validate(payload)


def test_result_requires_exactly_one_terminal_intent_or_failure() -> None:
    profile = make_profile()
    task = make_task(profile)
    common = {
        "task_id": task.task_id,
        "adapter_id": task.adapter_id,
        "profile_version": task.profile_version,
        "profile_digest": task.profile_digest,
        "run_id": "run-contract-1",
        "trace_id": "trace-contract-1",
        "model_id": "scripted",
        "completed_monotonic_s": 101.0,
        "latency": LatencyBreakdown(
            queue_ms=1.0,
            provider_ms=2.0,
            parse_ms=1.0,
            total_ms=4.5,
        ),
    }

    success = AgentRunResult(
        **common,
        status=RunStatus.SUCCEEDED,
        terminal_intent=TerminalIntent(
            tool_name="emit_answer",
            arguments={"answer": "Supported answer"},
        ),
    )
    failure = AgentRunResult(
        **common,
        status=RunStatus.FAILED,
        failure=CoreFailure(
            code=CoreFailureCode.MALFORMED_ARGUMENTS,
            message="terminal arguments did not match the registered schema",
        ),
    )

    assert success.failure is None
    assert failure.terminal_intent is None
    assert "effect_executed" not in AgentRunResult.model_fields
    assert "effect_executed" not in success.model_dump()

    with pytest.raises(ValidationError, match="exactly one|succeeded"):
        AgentRunResult(**common, status=RunStatus.SUCCEEDED)
    with pytest.raises(ValidationError, match="exactly one|failed"):
        AgentRunResult(
            **common,
            status=RunStatus.FAILED,
            terminal_intent=TerminalIntent(
                tool_name="emit_answer",
                arguments={"answer": "not allowed on failure"},
            ),
            failure=CoreFailure(
                code=CoreFailureCode.PROVIDER_ERROR,
                message="provider unavailable",
            ),
        )


def test_contracts_forbid_unknown_fields() -> None:
    payload = make_profile().model_dump()
    payload["effect_authority"] = "send_anything"

    with pytest.raises(ValidationError):
        AgentProfile.model_validate(payload)


def test_exported_contract_schemas_describe_json_documents_as_objects() -> None:
    profile_schema = AgentProfile.model_json_schema()
    task_schema = AgentTask.model_json_schema()

    assert profile_schema["$defs"]["FrozenJsonObject"]["type"] == "object"
    assert task_schema["$defs"]["FrozenJsonObject"]["type"] == "object"
