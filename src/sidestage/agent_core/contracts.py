"""Immutable, domain-neutral contracts for the static single-step agent core."""

from __future__ import annotations

from enum import Enum
import json
import math
from typing import Annotated, Any, Mapping, Optional, Tuple, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    RootModel,
    StringConstraints,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema


NonEmptyText = Annotated[str, StringConstraints(strict=True, min_length=1)]
AdapterId = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$",
    ),
]
ProfileVersion = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^(?:0|[1-9][0-9]*)\.[0-9]+\.[0-9]+$"),
]
EntityId = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
ToolName = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$",
    ),
]
ProfileDigest = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^sha256:[0-9a-f]{64}$"),
]
PositiveFiniteFloat = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
NonNegativeFiniteFloat = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]


def _normalize_json(value: Any, *, path: str = "$") -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string object key")
            normalized[key] = _normalize_json(item, path=f"{path}.{key}")
        return normalized
    raise ValueError(f"{path} contains non-JSON value {type(value).__name__}")


def _canonical_json_object(value: Any) -> str:
    if isinstance(value, FrozenJsonObject):
        return value.root
    normalized = _normalize_json(value)
    if not isinstance(normalized, dict):
        raise ValueError("value must be a JSON object")
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class FrozenJsonObject(RootModel[str]):
    """A deeply immutable JSON object stored in canonical serialized form."""

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="before")
    @classmethod
    def canonicalize_object(cls, value: Any) -> str:
        return _canonical_json_object(value)

    @model_serializer(mode="plain")
    def serialize_as_object(self) -> dict[str, Any]:
        return self.to_dict()

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        handler(core_schema)
        return {
            "type": "object",
            "title": cls.__name__,
            "description": cls.__doc__,
            "additionalProperties": True,
        }

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.root))

    def canonical_bytes(self) -> bytes:
        return self.root.encode("utf-8")


class FrozenContract(BaseModel):
    """Strict immutable base for all public core contracts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
    )


class QueuePolicy(FrozenContract):
    capacity: PositiveInt
    max_concurrency: PositiveInt

    @model_validator(mode="after")
    def concurrency_must_fit_capacity(self) -> "QueuePolicy":
        if self.max_concurrency > self.capacity:
            raise ValueError("max_concurrency cannot exceed queue capacity")
        return self


class DeadlinePolicy(FrozenContract):
    default_timeout_ms: PositiveInt
    max_timeout_ms: PositiveInt

    @model_validator(mode="after")
    def default_must_fit_maximum(self) -> "DeadlinePolicy":
        if self.default_timeout_ms > self.max_timeout_ms:
            raise ValueError("default timeout cannot exceed maximum timeout")
        return self


class TerminalToolSchema(FrozenContract):
    name: ToolName
    description: NonEmptyText
    parameters_schema: FrozenJsonObject

    def to_provider_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema.to_dict(),
        }


class AgentProfile(FrozenContract):
    adapter_id: AdapterId
    profile_version: ProfileVersion
    system_policy: NonEmptyText
    input_schema: FrozenJsonObject
    terminal_tools: Annotated[Tuple[TerminalToolSchema, ...], Field(min_length=1)]
    queue_policy: QueuePolicy
    deadline_policy: DeadlinePolicy
    model_config_ref: NonEmptyText
    max_model_input_bytes: PositiveInt

    @model_validator(mode="after")
    def terminal_tool_names_must_be_unique(self) -> "AgentProfile":
        names = [tool.name for tool in self.terminal_tools]
        if len(set(names)) != len(names):
            raise ValueError("terminal tool names must be unique")
        return self


_SENSITIVE_METADATA_MARKERS = (
    "api_key",
    "apikey",
    "credential",
    "password",
    "secret",
    "token",
)


def _sensitive_metadata_path(
    value: Any,
    *,
    path: str = "correlation_metadata",
) -> Optional[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = key.casefold().replace("-", "_")
            if any(marker in normalized_key for marker in _SENSITIVE_METADATA_MARKERS):
                return f"{path}.{key}"
            found = _sensitive_metadata_path(item, path=f"{path}.{key}")
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _sensitive_metadata_path(item, path=f"{path}[{index}]")
            if found is not None:
                return found
    return None


class AgentTask(FrozenContract):
    task_id: EntityId
    adapter_id: AdapterId
    profile_version: ProfileVersion
    profile_digest: ProfileDigest
    deadline_monotonic_s: PositiveFiniteFloat
    model_input: FrozenJsonObject
    correlation_metadata: FrozenJsonObject = Field(default_factory=lambda: FrozenJsonObject({}))

    @field_validator("correlation_metadata")
    @classmethod
    def credentials_are_not_task_metadata(cls, metadata: FrozenJsonObject) -> FrozenJsonObject:
        sensitive_path = _sensitive_metadata_path(metadata.to_dict())
        if sensitive_path is not None:
            raise ValueError(f"credential or secret metadata is forbidden at {sensitive_path}")
        return metadata


class CoreFailureCode(str, Enum):
    INVALID_PROFILE = "invalid_profile"
    INVALID_TASK = "invalid_task"
    QUEUE_FULL = "queue_full"
    UNKNOWN_TOOL = "unknown_tool"
    MISSING_TERMINAL_CALL = "missing_terminal_call"
    MULTIPLE_TERMINAL_CALLS = "multiple_terminal_calls"
    MALFORMED_ARGUMENTS = "malformed_arguments"
    PROVIDER_ERROR = "provider_error"
    CANCELLED = "cancelled"
    HARD_TIMEOUT = "hard_timeout"


class CoreFailure(FrozenContract):
    code: CoreFailureCode
    message: NonEmptyText
    retryable: bool = False


class TerminalIntent(FrozenContract):
    tool_name: ToolName
    arguments: FrozenJsonObject


class LatencyBreakdown(FrozenContract):
    queue_ms: NonNegativeFiniteFloat
    provider_ms: NonNegativeFiniteFloat
    parse_ms: NonNegativeFiniteFloat
    total_ms: NonNegativeFiniteFloat

    @model_validator(mode="after")
    def total_must_cover_components(self) -> "LatencyBreakdown":
        component_total = self.queue_ms + self.provider_ms + self.parse_ms
        if self.total_ms + 1e-9 < component_total:
            raise ValueError("total latency cannot be less than its component durations")
        return self


class RunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AgentRunResult(FrozenContract):
    task_id: EntityId
    adapter_id: AdapterId
    profile_version: ProfileVersion
    profile_digest: ProfileDigest
    run_id: EntityId
    trace_id: EntityId
    model_id: NonEmptyText
    status: RunStatus
    terminal_intent: Optional[TerminalIntent] = None
    failure: Optional[CoreFailure] = None
    latency: LatencyBreakdown
    completed_monotonic_s: NonNegativeFiniteFloat
    provider_metadata: FrozenJsonObject = Field(
        default_factory=lambda: FrozenJsonObject({})
    )

    @model_validator(mode="after")
    def require_one_terminal_outcome(self) -> "AgentRunResult":
        outcome_count = int(self.terminal_intent is not None) + int(self.failure is not None)
        if outcome_count != 1:
            raise ValueError("result must contain exactly one terminal intent or failure")
        if self.status is RunStatus.SUCCEEDED and self.terminal_intent is None:
            raise ValueError("succeeded result requires a terminal intent")
        if self.status is RunStatus.FAILED and self.failure is None:
            raise ValueError("failed result requires a core failure")
        return self


class ModelRequestProjection(FrozenContract):
    system_policy: NonEmptyText
    model_input: FrozenJsonObject
    terminal_tools: Annotated[Tuple[TerminalToolSchema, ...], Field(min_length=1)]

    def to_provider_dict(self) -> dict[str, Any]:
        return {
            "system_policy": self.system_policy,
            "input": self.model_input.to_dict(),
            "tools": [tool.to_provider_dict() for tool in self.terminal_tools],
        }
