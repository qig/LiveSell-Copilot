"""Provider-neutral model port plus scripted and OpenAI-compatible runners."""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Iterable, Literal, Mapping, Optional, Protocol, Tuple, Union
from urllib.parse import urlsplit

import httpx
from pydantic import Field, SecretStr, field_validator

from sidestage.agent_core.contracts import (
    FrozenContract,
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


class ModelInvocation(FrozenContract):
    """One invocation with provider routing kept separate from model-visible input."""

    model_config_ref: NonEmptyText
    request: ModelRequestProjection


class ModelRunner(Protocol):
    """Replaceable one-request model boundary."""

    async def run(self, invocation: ModelInvocation) -> ModelResponse:
        ...


ScriptedOutcome = Union[ModelResponse, BaseException]


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
    reasoning_effort: Optional[
        Literal["none", "low", "medium", "high", "xhigh", "max"]
    ] = None

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
                {"type": "function", "function": tool.to_provider_dict()}
                for tool in invocation.request.terminal_tools
            ],
            "tool_choice": "required",
            "parallel_tool_calls": False,
            "stream": False,
        }
        if self.config.reasoning_effort is not None:
            request_payload["reasoning_effort"] = self.config.reasoning_effort
        try:
            response = await self._http_client.post(
                f"{self.config.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
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
        )

    async def aclose(self) -> None:
        if not self._owns_client:
            return
        close = getattr(self._http_client, "aclose", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result
