"""Startup-only profile registration, hashing, and task projection."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Optional

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from sidestage.agent_core.contracts import (
    AgentProfile,
    AgentTask,
    ModelRequestProjection,
    ProfileDigest,
)


class AgentProfileValidationError(ValueError):
    """Raised when a static profile cannot be registered safely."""


class UnknownAgentProfileError(LookupError):
    """Raised when a task references an unregistered profile identity."""


class AgentTaskValidationError(ValueError):
    """Raised before provider work when a task violates its static profile."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _schema_validator(schema: Mapping[str, object], *, label: str) -> Draft202012Validator:
    _reject_remote_schema_references(schema, label=label)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise AgentProfileValidationError(f"{label} is invalid: {exc.message}") from exc
    return Draft202012Validator(schema)


def _reject_remote_schema_references(
    value: Any,
    *,
    label: str,
    path: str = "$",
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {"$ref", "$dynamicRef"} and isinstance(child, str):
                if not child.startswith("#"):
                    raise AgentProfileValidationError(
                        f"{label} contains a remote schema reference at {child_path}"
                    )
            _reject_remote_schema_references(child, label=label, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_remote_schema_references(
                child,
                label=label,
                path=f"{path}[{index}]",
            )


@dataclass(frozen=True)
class RegisteredAgentProfile:
    """A validated profile plus compiled validators and its stable digest."""

    profile: AgentProfile
    digest: ProfileDigest
    _input_validator: Draft202012Validator = field(repr=False, compare=False)
    _terminal_validators: Mapping[str, Draft202012Validator] = field(
        repr=False,
        compare=False,
    )

    def validate_task(
        self,
        task: AgentTask,
        *,
        now_monotonic_s: float,
    ) -> AgentTask:
        if not math.isfinite(now_monotonic_s) or now_monotonic_s < 0:
            raise AgentTaskValidationError("current monotonic time must be finite and nonnegative")
        if task.adapter_id != self.profile.adapter_id:
            raise AgentTaskValidationError("task adapter does not match registered profile")
        if task.profile_version != self.profile.profile_version:
            raise AgentTaskValidationError("task profile version does not match registered profile")
        if task.profile_digest != self.digest:
            raise AgentTaskValidationError("task profile digest does not match registered profile")
        if task.deadline_monotonic_s <= now_monotonic_s:
            raise AgentTaskValidationError("task deadline has already expired")

        maximum_deadline = now_monotonic_s + self.profile.deadline_policy.max_timeout_ms / 1_000
        if task.deadline_monotonic_s > maximum_deadline:
            raise AgentTaskValidationError("task deadline exceeds the profile maximum timeout")

        input_size = len(task.model_input.canonical_bytes())
        if input_size > self.profile.max_model_input_bytes:
            raise AgentTaskValidationError(
                f"model input is {input_size} bytes; maximum is "
                f"{self.profile.max_model_input_bytes} bytes"
            )

        try:
            self._input_validator.validate(task.model_input.to_dict())
        except JsonSchemaValidationError as exc:
            location = ".".join(str(part) for part in exc.absolute_path) or "$"
            failed_keyword = str(exc.validator) if exc.validator is not None else "unknown"
            raise AgentTaskValidationError(
                f"model input schema validation failed at {location} "
                f"for keyword {failed_keyword}"
            ) from exc
        return task

    def project_model_request(
        self,
        task: AgentTask,
        *,
        now_monotonic_s: float,
    ) -> ModelRequestProjection:
        validated_task = self.validate_task(task, now_monotonic_s=now_monotonic_s)
        return ModelRequestProjection(
            system_policy=self.profile.system_policy,
            model_input=validated_task.model_input,
            terminal_tools=self.profile.terminal_tools,
        )

    def terminal_validator(self, tool_name: str) -> Optional[Draft202012Validator]:
        return self._terminal_validators.get(tool_name)


def register_profile(profile: AgentProfile) -> RegisteredAgentProfile:
    """Validate and compile a profile before the first task is accepted."""

    try:
        profile = AgentProfile.model_validate(profile.model_dump())
    except PydanticValidationError as exc:
        raise AgentProfileValidationError(f"profile contract is invalid: {exc}") from exc

    input_schema = profile.input_schema.to_dict()
    input_validator = _schema_validator(input_schema, label="input schema")
    terminal_validators: dict[str, Draft202012Validator] = {}
    for tool in profile.terminal_tools:
        terminal_validators[tool.name] = _schema_validator(
            tool.parameters_schema.to_dict(),
            label=f"terminal schema {tool.name!r}",
        )

    digest = f"sha256:{sha256(_canonical_json_bytes(profile.model_dump(mode='json'))).hexdigest()}"
    return RegisteredAgentProfile(
        profile=profile,
        digest=digest,
        _input_validator=input_validator,
        _terminal_validators=MappingProxyType(terminal_validators),
    )


class AgentProfileRegistry:
    """Immutable startup registry keyed by adapter and profile version."""

    __slots__ = ("_profiles", "_profiles_by_identity")

    def __init__(self, profiles: Iterable[AgentProfile]) -> None:
        registered_profiles: list[RegisteredAgentProfile] = []
        by_identity: dict[tuple[str, str], RegisteredAgentProfile] = {}
        for profile in profiles:
            registered = register_profile(profile)
            identity = (profile.adapter_id, profile.profile_version)
            if identity in by_identity:
                raise AgentProfileValidationError(
                    f"duplicate profile for adapter {profile.adapter_id!r} "
                    f"and version {profile.profile_version!r}"
                )
            by_identity[identity] = registered
            registered_profiles.append(registered)
        if not registered_profiles:
            raise AgentProfileValidationError("at least one profile must be registered")

        object.__setattr__(self, "_profiles", tuple(registered_profiles))
        object.__setattr__(self, "_profiles_by_identity", MappingProxyType(by_identity))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("agent profile registry is immutable after startup")

    @property
    def profiles(self) -> tuple[RegisteredAgentProfile, ...]:
        return self._profiles

    def resolve(
        self,
        adapter_id: str,
        profile_version: str,
        profile_digest: str,
    ) -> RegisteredAgentProfile:
        registered = self._profiles_by_identity.get((adapter_id, profile_version))
        if registered is None:
            raise UnknownAgentProfileError(
                f"unknown profile for adapter {adapter_id!r} and version {profile_version!r}"
            )
        if registered.digest != profile_digest:
            raise UnknownAgentProfileError("profile digest does not match the startup registry")
        return registered
