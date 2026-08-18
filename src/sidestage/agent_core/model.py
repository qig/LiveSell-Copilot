"""Provider-neutral model port plus scripted and OpenAI-compatible runners."""

from __future__ import annotations

import asyncio
import inspect
import json
import math
from typing import Any, Iterable, Literal, Mapping, Optional, Protocol, Tuple, Union
from urllib.parse import urlsplit

import httpx
from pydantic import Field, SecretStr, field_validator, model_validator

from sidestage.agent_core.contracts import (
    FrozenContract,
    FrozenJsonObject,
    ModelRequestProjection,
    NonEmptyText,
    PositiveFiniteFloat,
    ToolName,
)


class ModelRunnerError(RuntimeError):
    """A sanitized provider-port failure safe for core classification."""


class ModelTerminalCall(FrozenContract):
    """One raw terminal call returned by a provider."""

    tool_name: ToolName
    arguments_json: str
    provider_call_id: Optional[str] = None


class ModelResponse(FrozenContract):
    """Provider-neutral response; terminal arguments remain untrusted JSON text."""

    model_id: NonEmptyText
    terminal_calls: Tuple[ModelTerminalCall, ...] = ()
    text: Optional[str] = None
    provider_metadata: FrozenJsonObject = Field(default_factory=lambda: FrozenJsonObject({}))


class ModelInvocation(FrozenContract):
    """One invocation with provider routing kept separate from model-visible input."""

    model_config_ref: NonEmptyText
    request: ModelRequestProjection


class ModelRunner(Protocol):
    """Replaceable one-request model boundary."""

    async def run(self, invocation: ModelInvocation) -> ModelResponse:
        ...


ScriptedOutcome = Union[ModelResponse, BaseException]


_LOCAL_ONLY_STRICT_SCHEMA_KEYS = frozenset(
    {
        "minLength",
        "maxLength",
        "uniqueItems",
    }
)


def _openai_strict_schema(value: Any) -> Any:
    """Project the full local schema into OpenAI's strict JSON Schema subset."""

    if isinstance(value, list):
        return [_openai_strict_schema(item) for item in value]
    if not isinstance(value, Mapping):
        return value

    projected: dict[str, Any] = {}
    for key, item in value.items():
        if key in _LOCAL_ONLY_STRICT_SCHEMA_KEYS:
            continue
        if key == "const":
            if "enum" not in value:
                projected["enum"] = [_openai_strict_schema(item)]
            continue
        projected[key] = _openai_strict_schema(item)
    return projected


class ScriptedModelRunner:
    """Deterministic in-memory runner with no retry or fallback behavior."""

    def __init__(self, outcomes: Iterable[ScriptedOutcome]) -> None:
        self._outcomes = tuple(outcomes)
        self._next_outcome = 0
        self._calls: list[ModelInvocation] = []

    @property
    def calls(self) -> tuple[ModelInvocation, ...]:
        return tuple(self._calls)

    async def run(self, invocation: ModelInvocation) -> ModelResponse:
        self._calls.append(invocation)
        if self._next_outcome >= len(self._outcomes):
            raise ModelRunnerError("scripted model outcomes are exhausted")
        outcome = self._outcomes[self._next_outcome]
        self._next_outcome += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class OpenAICompatibleModelConfig(FrozenContract):
    """One pinned OpenAI-compatible Chat Completions configuration."""

    config_ref: NonEmptyText
    base_url: NonEmptyText
    api_key: SecretStr = Field(repr=False)
    model_id: NonEmptyText
    request_timeout_s: PositiveFiniteFloat
    strict_function_tools: bool = False
    reasoning_effort: Optional[
        Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
    ] = None
    service_tier: Optional[Literal["default", "priority"]] = None
    openrouter_routing: Optional["OpenRouterRoutingConfig"] = None

    @field_validator("base_url")
    @classmethod
    def require_http_base_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("base_url cannot contain embedded credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("base_url cannot contain a query or fragment")
        return value.rstrip("/")

    @model_validator(mode="after")
    def service_tier_is_direct_openai_only(self) -> "OpenAICompatibleModelConfig":
        if self.openrouter_routing is not None and self.service_tier is not None:
            raise ValueError("service_tier is only supported for direct OpenAI requests")
        return self


class OpenRouterRoutingConfig(FrozenContract):
    """Fail-closed OpenRouter preferences for comparable benchmark cells."""

    allow_fallbacks: Literal[False] = False
    require_parameters: Literal[True] = True
    sort: Literal["latency", "throughput", "price"] = "latency"
    data_collection: Literal["deny"] = "deny"
    metadata_enabled: Literal[True] = True


class AsyncHttpClient(Protocol):
    async def post(self, url: str, **kwargs: Any) -> Any:
        ...


class OpenAICompatibleModelRunner:
    """Single-request Chat Completions runner with static function tools."""

    def __init__(
        self,
        config: OpenAICompatibleModelConfig,
        *,
        http_client: Optional[AsyncHttpClient] = None,
    ) -> None:
        self.config = config
        self._owns_client = http_client is None
        self._http_client: AsyncHttpClient = http_client or httpx.AsyncClient()

    async def run(self, invocation: ModelInvocation) -> ModelResponse:
        if invocation.model_config_ref != self.config.config_ref:
            raise ModelRunnerError("model configuration reference is not registered by this runner")

        request_payload = {
            "model": self.config.model_id,
            "messages": [
                {"role": "system", "content": invocation.request.system_policy},
                {
                    "role": "user",
                    "content": json.dumps(
                        invocation.request.model_input.to_dict(),
                        ensure_ascii=False,
                        allow_nan=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        **{
                            **tool.to_provider_dict(),
                            "parameters": (
                                _openai_strict_schema(
                                    tool.parameters_schema.to_dict()
                                )
                                if self.config.strict_function_tools
                                else tool.parameters_schema.to_dict()
                            ),
                        },
                        **({"strict": True} if self.config.strict_function_tools else {}),
                    },
                }
                for tool in invocation.request.terminal_tools
            ],
            "tool_choice": "required",
            "stream": False,
        }
        # OpenRouter's cross-model `require_parameters` gate excludes models whose
        # endpoints do not advertise this optional OpenAI control (for example,
        # Kimi K3). The provider-neutral core independently requires exactly one
        # terminal call, so omitting the hint does not weaken the local contract.
        if self.config.openrouter_routing is None:
            request_payload["parallel_tool_calls"] = False
        if self.config.openrouter_routing is not None:
            if self.config.reasoning_effort is not None:
                request_payload["reasoning"] = {"effort": self.config.reasoning_effort}
            routing = self.config.openrouter_routing
            request_payload["provider"] = {
                "allow_fallbacks": routing.allow_fallbacks,
                "require_parameters": routing.require_parameters,
                "sort": routing.sort,
                "data_collection": routing.data_collection,
            }
        else:
            if self.config.reasoning_effort is not None:
                request_payload["reasoning_effort"] = self.config.reasoning_effort
            if self.config.service_tier is not None:
                request_payload["service_tier"] = self.config.service_tier
        headers = {
            "Authorization": f"Bearer {self.config.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        if self.config.openrouter_routing is not None:
            headers["X-OpenRouter-Metadata"] = "enabled"
        try:
            response = await self._http_client.post(
                f"{self.config.base_url}/chat/completions",
                headers=headers,
                json=request_payload,
                timeout=self.config.request_timeout_s,
            )
            response.raise_for_status()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ModelRunnerError("model provider request failed") from exc

        try:
            payload = response.json()
            return self._decode_chat_completion(payload)
        except ModelRunnerError:
            raise
        except Exception as exc:
            raise ModelRunnerError("model provider returned an invalid response") from exc

    def _decode_chat_completion(self, payload: Any) -> ModelResponse:
        if not isinstance(payload, Mapping):
            raise ModelRunnerError("model provider returned an invalid response")
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ModelRunnerError("model provider returned an invalid response")
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise ModelRunnerError("model provider returned an invalid response")
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise ModelRunnerError("model provider returned an invalid response")

        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ModelRunnerError("model provider returned an invalid response")
        raw_calls = message.get("tool_calls")
        if raw_calls is None:
            raw_calls = []
        if not isinstance(raw_calls, list):
            raise ModelRunnerError("model provider returned an invalid response")

        terminal_calls: list[ModelTerminalCall] = []
        for raw_call in raw_calls:
            if not isinstance(raw_call, Mapping) or raw_call.get("type") != "function":
                raise ModelRunnerError("model provider returned an invalid response")
            function = raw_call.get("function")
            if not isinstance(function, Mapping):
                raise ModelRunnerError("model provider returned an invalid response")
            name = function.get("name")
            arguments = function.get("arguments")
            call_id = raw_call.get("id")
            if not isinstance(name, str) or not isinstance(arguments, str):
                raise ModelRunnerError("model provider returned an invalid response")
            if call_id is not None and not isinstance(call_id, str):
                raise ModelRunnerError("model provider returned an invalid response")
            terminal_calls.append(
                ModelTerminalCall(
                    tool_name=name,
                    arguments_json=arguments,
                    provider_call_id=call_id,
                )
            )

        model_id = payload.get("model")
        if not isinstance(model_id, str) or not model_id:
            model_id = self.config.model_id
        return ModelResponse(
            model_id=model_id,
            terminal_calls=tuple(terminal_calls),
            text=content,
            provider_metadata=self._provider_metadata(payload, model_id),
        )

    def _provider_metadata(self, payload: Mapping[str, Any], model_id: str) -> dict[str, Any]:
        """Project only benchmark-safe provider fields; never retain headers or credentials."""

        metadata: dict[str, Any] = {
            "requested_model_id": self.config.model_id,
            "resolved_model_id": model_id,
        }
        generation_id = payload.get("id")
        if isinstance(generation_id, str) and generation_id:
            metadata["generation_id"] = generation_id[:256]
        service_tier = payload.get("service_tier")
        if isinstance(service_tier, str) and service_tier:
            metadata["service_tier"] = service_tier[:64]

        usage = _project_usage(payload.get("usage"))
        if usage:
            metadata["usage"] = usage

        router = payload.get("openrouter_metadata")
        if isinstance(router, Mapping):
            for key in ("requested", "strategy", "region", "summary", "attempt", "is_byok"):
                value = router.get(key)
                if isinstance(value, (str, int, bool)) and not isinstance(value, float):
                    metadata[f"router_{key}"] = value[:256] if isinstance(value, str) else value
            attempts = _project_router_attempts(router.get("attempts"))
            if attempts:
                metadata["routing_attempts"] = attempts
                selected = next(
                    (
                        attempt["provider"]
                        for attempt in reversed(attempts)
                        if attempt.get("status") == 200
                    ),
                    None,
                )
                if selected is not None:
                    metadata["resolved_provider"] = selected
        provider = payload.get("provider")
        if isinstance(provider, str) and provider:
            metadata["resolved_provider"] = provider[:128]
        return metadata

    async def aclose(self) -> None:
        if not self._owns_client:
            return
        close = getattr(self._http_client, "aclose", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result


def _project_usage(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    projected: dict[str, Any] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        item = value.get(key)
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
            projected[key] = item
    cost = value.get("cost")
    if (
        isinstance(cost, (int, float))
        and not isinstance(cost, bool)
        and math.isfinite(cost)
        and cost >= 0
    ):
        projected["cost"] = cost
    completion_details = value.get("completion_tokens_details")
    if isinstance(completion_details, Mapping):
        reasoning = completion_details.get("reasoning_tokens")
        if isinstance(reasoning, int) and not isinstance(reasoning, bool) and reasoning >= 0:
            projected["reasoning_tokens"] = reasoning
    prompt_details = value.get("prompt_tokens_details")
    if isinstance(prompt_details, Mapping):
        for source, target in (
            ("cached_tokens", "cached_tokens"),
            ("cache_write_tokens", "cache_write_tokens"),
        ):
            item = prompt_details.get(source)
            if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
                projected[target] = item
    cost_details = value.get("cost_details")
    if isinstance(cost_details, Mapping):
        upstream = cost_details.get("upstream_inference_cost")
        if (
            isinstance(upstream, (int, float))
            and not isinstance(upstream, bool)
            and math.isfinite(upstream)
            and upstream >= 0
        ):
            projected["upstream_inference_cost"] = upstream
    return projected


def _project_router_attempts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    attempts: list[dict[str, Any]] = []
    for raw in value[:16]:
        if not isinstance(raw, Mapping):
            continue
        provider = raw.get("provider")
        model = raw.get("model")
        status = raw.get("status")
        if not isinstance(provider, str) or not isinstance(model, str):
            continue
        attempt: dict[str, Any] = {
            "provider": provider[:128],
            "model": model[:256],
        }
        if isinstance(status, int) and not isinstance(status, bool):
            attempt["status"] = status
        attempts.append(attempt)
    return attempts
