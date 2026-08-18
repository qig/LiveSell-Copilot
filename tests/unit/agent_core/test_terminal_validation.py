from __future__ import annotations

import pytest

from sidestage.agent_core import (
    AgentProfile,
    CoreFailureCode,
    DeadlinePolicy,
    QueuePolicy,
    TerminalToolSchema,
    register_profile,
)
from sidestage.agent_core.model import ModelResponse, ModelTerminalCall
from sidestage.agent_core.terminal import TerminalResponseError, decode_terminal_response


def make_registered_profile():
    return register_profile(
        AgentProfile(
            adapter_id="generic.qa",
            profile_version="1.0.0",
            system_policy="Choose exactly one terminal result.",
            input_schema={"type": "object"},
            terminal_tools=(
                TerminalToolSchema(
                    name="emit_answer",
                    description="Return a grounded answer.",
                    parameters_schema={
                        "type": "object",
                        "properties": {
                            "answer": {"type": "string", "minLength": 1},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": ["answer", "confidence"],
                        "additionalProperties": False,
                    },
                ),
                TerminalToolSchema(
                    name="abstain",
                    description="Decline when evidence is insufficient.",
                    parameters_schema={
                        "type": "object",
                        "properties": {"reason": {"type": "string", "minLength": 1}},
                        "required": ["reason"],
                        "additionalProperties": False,
                    },
                ),
            ),
            queue_policy=QueuePolicy(capacity=4, max_concurrency=1),
            deadline_policy=DeadlinePolicy(default_timeout_ms=1_000, max_timeout_ms=5_000),
            model_config_ref="scripted-fast-v1",
            max_model_input_bytes=4_096,
        )
    )


def call(name: str, arguments_json: str) -> ModelTerminalCall:
    return ModelTerminalCall(tool_name=name, arguments_json=arguments_json)


def test_decodes_exactly_one_allowed_terminal_call() -> None:
    intent = decode_terminal_response(
        ModelResponse(
            model_id="scripted-model-v1",
            terminal_calls=(
                call(
                    "emit_answer",
                    '{"answer":"Supported by evidence","confidence":0.9}',
                ),
            ),
        ),
        make_registered_profile(),
    )

    assert intent.tool_name == "emit_answer"
    assert intent.arguments.to_dict() == {
        "answer": "Supported by evidence",
        "confidence": 0.9,
    }


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (
            ModelResponse(model_id="scripted-model-v1", text="ordinary free text"),
            CoreFailureCode.MISSING_TERMINAL_CALL,
        ),
        (
            ModelResponse(model_id="scripted-model-v1"),
            CoreFailureCode.MISSING_TERMINAL_CALL,
        ),
        (
            ModelResponse(
                model_id="scripted-model-v1",
                terminal_calls=(
                    call("abstain", '{"reason":"not enough evidence"}'),
                    call("emit_answer", '{"answer":"A","confidence":0.8}'),
                ),
            ),
            CoreFailureCode.MULTIPLE_TERMINAL_CALLS,
        ),
        (
            ModelResponse(
                model_id="scripted-model-v1",
                terminal_calls=(call("read_catalog", "{}"),),
            ),
            CoreFailureCode.UNKNOWN_TOOL,
        ),
        (
            ModelResponse(
                model_id="scripted-model-v1",
                terminal_calls=(call("emit_answer", "not-json"),),
            ),
            CoreFailureCode.MALFORMED_ARGUMENTS,
        ),
        (
            ModelResponse(
                model_id="scripted-model-v1",
                terminal_calls=(call("emit_answer", "[]"),),
            ),
            CoreFailureCode.MALFORMED_ARGUMENTS,
        ),
        (
            ModelResponse(
                model_id="scripted-model-v1",
                terminal_calls=(call("emit_answer", '{"answer":"missing confidence"}'),),
            ),
            CoreFailureCode.MALFORMED_ARGUMENTS,
        ),
        (
            ModelResponse(
                model_id="scripted-model-v1",
                terminal_calls=(
                    call(
                        "emit_answer",
                        '{"answer":"A","confidence":2,"effect_authority":"forbidden"}',
                    ),
                ),
            ),
            CoreFailureCode.MALFORMED_ARGUMENTS,
        ),
    ],
)
def test_terminal_verdict_matrix_fails_closed(
    response: ModelResponse,
    expected_code: CoreFailureCode,
) -> None:
    with pytest.raises(TerminalResponseError) as captured:
        decode_terminal_response(response, make_registered_profile())

    assert captured.value.code is expected_code
    assert "ordinary free text" not in str(captured.value)
    assert "effect_authority" not in str(captured.value)
