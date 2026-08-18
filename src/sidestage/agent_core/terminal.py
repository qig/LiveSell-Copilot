"""Strict decoding of one statically registered terminal call."""

from __future__ import annotations

import json
from typing import Any, Iterable, Tuple

from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from sidestage.agent_core.contracts import CoreFailureCode, TerminalIntent
from sidestage.agent_core.model import ModelResponse
from sidestage.agent_core.profile import RegisteredAgentProfile


class TerminalResponseError(ValueError):
    """A sanitized terminal-verdict failure with its core failure code."""

    def __init__(self, code: CoreFailureCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _reject_duplicate_object_keys(
    pairs: Iterable[Tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key is forbidden: {key}")
        result[key] = value
    return result


def decode_terminal_response(
    response: ModelResponse,
    profile: RegisteredAgentProfile,
) -> TerminalIntent:
    """Return one validated intent, or fail closed without echoing arguments."""

    call_count = len(response.terminal_calls)
    if call_count == 0:
        raise TerminalResponseError(
            CoreFailureCode.MISSING_TERMINAL_CALL,
            "model response did not contain a terminal call",
        )
    if call_count > 1:
        raise TerminalResponseError(
            CoreFailureCode.MULTIPLE_TERMINAL_CALLS,
            "model response contained multiple terminal calls",
        )

    call = response.terminal_calls[0]
    validator = profile.terminal_validator(call.tool_name)
    if validator is None:
        raise TerminalResponseError(
            CoreFailureCode.UNKNOWN_TOOL,
            "model response selected an unregistered terminal tool",
        )

    try:
        arguments: Any = json.loads(
            call.arguments_json,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_object_keys,
        )
    except (TypeError, ValueError) as exc:
        raise TerminalResponseError(
            CoreFailureCode.MALFORMED_ARGUMENTS,
            "terminal arguments are not valid JSON",
        ) from exc
    if not isinstance(arguments, dict):
        raise TerminalResponseError(
            CoreFailureCode.MALFORMED_ARGUMENTS,
            "terminal arguments must be a JSON object",
        )

    try:
        validator.validate(arguments)
    except JsonSchemaValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "$"
        failed_keyword = str(exc.validator) if exc.validator is not None else "unknown"
        raise TerminalResponseError(
            CoreFailureCode.MALFORMED_ARGUMENTS,
            f"terminal argument schema failed at {location} for keyword {failed_keyword}",
        ) from exc

    return TerminalIntent(tool_name=call.tool_name, arguments=arguments)
