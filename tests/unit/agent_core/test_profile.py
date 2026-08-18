from __future__ import annotations

import json
from typing import Optional

import pytest
from pydantic import ValidationError

from sidestage.agent_core.contracts import (
    AgentProfile,
    AgentTask,
    DeadlinePolicy,
    QueuePolicy,
    TerminalToolSchema,
)
from sidestage.agent_core.profile import (
    AgentProfileRegistry,
    AgentProfileValidationError,
    AgentTaskValidationError,
    UnknownAgentProfileError,
    register_profile,
)


def make_profile(
    *,
    input_schema: Optional[dict] = None,
    max_model_input_bytes: int = 1_024,
) -> AgentProfile:
    return AgentProfile(
        adapter_id="generic.qa",
        profile_version="1.0.0",
        system_policy="Use bounded evidence and choose exactly one terminal tool.",
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
                description="Return an evidence-backed answer.",
                parameters_schema={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                    "additionalProperties": False,
                },
            ),
            TerminalToolSchema(
                name="abstain",
                description="Return a reason for not answering.",
                parameters_schema={
                    "type": "object",
                    "properties": {"reason": {"type": "string"}},
                    "required": ["reason"],
                    "additionalProperties": False,
                },
            ),
        ),
        queue_policy=QueuePolicy(capacity=8, max_concurrency=2),
        deadline_policy=DeadlinePolicy(default_timeout_ms=1_000, max_timeout_ms=5_000),
        model_config_ref="fast-primary-v1",
        max_model_input_bytes=max_model_input_bytes,
    )


def make_task(profile: AgentProfile, **updates: object) -> AgentTask:
    payload: dict[str, object] = {
        "task_id": "task-profile-1",
        "adapter_id": profile.adapter_id,
        "profile_version": profile.profile_version,
        "profile_digest": register_profile(profile).digest,
        "deadline_monotonic_s": 103.0,
        "model_input": {"prompt": "Answer this", "evidence": ["Fact A"]},
        "correlation_metadata": {
            "trace_id": "trace-profile-1",
            "authorization_version": 7,
            "effect_id": "effect-not-model-visible",
            "dependency_versions": {"catalog": 3},
            "oracle": {"expected_tool": "emit_answer"},
        },
    }
    payload.update(updates)
    return AgentTask.model_validate(payload)


def test_logically_identical_profiles_have_the_same_sha256_digest() -> None:
    schema_a = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["prompt", "evidence"],
        "additionalProperties": False,
    }
    schema_b = {
        "additionalProperties": False,
        "required": ["prompt", "evidence"],
        "properties": {
            "evidence": {"items": {"type": "string"}, "type": "array"},
            "prompt": {"type": "string"},
        },
        "type": "object",
    }

    digest_a = register_profile(make_profile(input_schema=schema_a)).digest
    digest_b = register_profile(make_profile(input_schema=schema_b)).digest

    assert digest_a == digest_b
    assert digest_a.startswith("sha256:")
    assert len(digest_a) == len("sha256:") + 64


def test_profile_rejects_duplicate_terminal_names_and_invalid_schema() -> None:
    profile = make_profile()

    with pytest.raises(ValidationError, match="unique"):
        AgentProfile.model_validate(
            {
                **profile.model_dump(),
                "terminal_tools": (
                    profile.terminal_tools[0],
                    profile.terminal_tools[0],
                ),
            },
        )

    invalid = make_profile(input_schema={"type": "definitely-not-a-json-schema-type"})
    with pytest.raises(AgentProfileValidationError, match="input schema"):
        register_profile(invalid)


@pytest.mark.parametrize("reference_keyword", ["$ref", "$dynamicRef"])
def test_profile_rejects_remote_schema_references(reference_keyword: str) -> None:
    profile = make_profile(
        input_schema={reference_keyword: "https://example.invalid/remote-schema.json"}
    )

    with pytest.raises(AgentProfileValidationError, match="remote schema reference"):
        register_profile(profile)


def test_registry_is_startup_only_and_rejects_unknown_or_duplicate_profiles() -> None:
    profile = make_profile()
    registered = register_profile(profile)
    registry = AgentProfileRegistry((profile,))

    assert registry.resolve(
        profile.adapter_id,
        profile.profile_version,
        registered.digest,
    ).digest == registered.digest

    with pytest.raises(UnknownAgentProfileError):
        registry.resolve("missing.adapter", profile.profile_version, registered.digest)
    with pytest.raises(UnknownAgentProfileError, match="digest"):
        registry.resolve(profile.adapter_id, profile.profile_version, "sha256:" + "0" * 64)
    with pytest.raises(AgentProfileValidationError, match="duplicate"):
        AgentProfileRegistry((profile, profile))
    with pytest.raises(AttributeError):
        registry.profiles = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"adapter_id": "other.adapter"}, "adapter"),
        ({"profile_version": "2.0.0"}, "version"),
        ({"profile_digest": "sha256:" + "0" * 64}, "digest"),
        ({"deadline_monotonic_s": 99.0}, "deadline"),
        ({"deadline_monotonic_s": 106.0}, "deadline"),
        ({"model_input": {"prompt": 7, "evidence": []}}, "input schema"),
    ],
)
def test_registered_profile_rejects_mismatched_or_invalid_tasks(
    updates: dict[str, object],
    message: str,
) -> None:
    profile = make_profile()
    task = make_task(profile, **updates)

    with pytest.raises(AgentTaskValidationError, match=message):
        register_profile(profile).validate_task(task, now_monotonic_s=100.0)


def test_registered_profile_rejects_oversized_model_input() -> None:
    profile = make_profile(max_model_input_bytes=64)
    task = make_task(
        profile,
        model_input={"prompt": "x" * 100, "evidence": ["Fact A"]},
    )

    with pytest.raises(AgentTaskValidationError, match="bytes"):
        register_profile(profile).validate_task(task, now_monotonic_s=100.0)


def test_task_schema_error_does_not_echo_the_invalid_model_input() -> None:
    profile = make_profile()
    task = make_task(
        profile,
        model_input={
            "prompt": {"private": "value-that-must-not-enter-an-error"},
            "evidence": [],
        },
    )

    with pytest.raises(AgentTaskValidationError) as captured:
        register_profile(profile).validate_task(task, now_monotonic_s=100.0)

    assert "value-that-must-not-enter-an-error" not in str(captured.value)
    assert "prompt" in str(captured.value)
    assert "type" in str(captured.value)


def test_model_projection_excludes_non_model_visible_authority_and_oracle_data() -> None:
    profile = make_profile()
    registered = register_profile(profile)
    task = make_task(profile)

    projection = registered.project_model_request(task, now_monotonic_s=100.0)
    provider_payload = projection.to_provider_dict()
    serialized = json.dumps(provider_payload, sort_keys=True)

    assert provider_payload == {
        "system_policy": profile.system_policy,
        "input": {"prompt": "Answer this", "evidence": ["Fact A"]},
        "tools": [
            {
                "name": "emit_answer",
                "description": "Return an evidence-backed answer.",
                "parameters": {
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "abstain",
                "description": "Return a reason for not answering.",
                "parameters": {
                    "type": "object",
                    "properties": {"reason": {"type": "string"}},
                    "required": ["reason"],
                    "additionalProperties": False,
                },
            },
        ],
    }
    for forbidden in (
        "authorization_version",
        "effect-not-model-visible",
        "dependency_versions",
        "expected_tool",
        "model_config_ref",
        task.task_id,
        task.profile_digest,
    ):
        assert forbidden not in serialized


def test_valid_task_is_returned_unchanged_after_validation() -> None:
    profile = make_profile()
    task = make_task(profile)

    assert register_profile(profile).validate_task(task, now_monotonic_s=100.0) is task
