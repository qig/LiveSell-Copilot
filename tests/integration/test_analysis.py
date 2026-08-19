from __future__ import annotations

import asyncio
import json
import time

import pytest

from sidestage.agent_core import ModelResponse, ModelTerminalCall, ScriptedModelRunner
from sidestage.copilot.analysis import (
    AnalysisFailureCode,
    AnalysisInput,
    AnalysisStatus,
    MessageAnalyzer,
    register_evidence_planner_agent,
)
from sidestage.copilot.contracts import BoundListing
from sidestage.domain.replies import BindingBasis, BindingStatus, FactType


def _input() -> AnalysisInput:
    return AnalysisInput(
        question_id="qst_analysis_1",
        trace_id="trc_analysis_1",
        question="Do you have size 9?",
        bound_listing=BoundListing(
            listing_id="lst_velocity_aero_dash",
            sku="VK-AD-RC-001",
            epoch_id="epc_velocity_1",
            binding_basis=BindingBasis.SOURCE_EPOCH,
            binding_status=BindingStatus.CERTAIN,
        ),
        deadline_monotonic_s=105.0,
    )


def _response(arguments: dict, *, tool: str = "request_evidence") -> ModelResponse:
    return ModelResponse(
        model_id="scripted-analysis",
        terminal_calls=(
            ModelTerminalCall(
                tool_name=tool,
                arguments_json=json.dumps(arguments),
            ),
        ),
    )


def _analyzer(
    runner,
    *,
    monotonic=lambda: 100.0,
    analysis_id_factory=lambda: "ana_analysis_1",
) -> MessageAnalyzer:
    agent = register_evidence_planner_agent(
        runner,
        model_config_ref="analysis-fast-v1",
        monotonic=monotonic,
        core_id_factory=lambda: "run_analysis_1",
    )
    return MessageAnalyzer(agent, id_factory=analysis_id_factory)


def test_analysis_makes_one_bounded_non_effect_request_and_validates_output() -> None:
    runner = ScriptedModelRunner(
        [
            _response(
                {
                    "intent": "answerable",
                    "answer_category": "availability",
                    "product_mentions": ["Aero Dash"],
                    "required_fact_types": ["variant_availability"],
                    "query_terms": [],
                }
            )
        ]
    )
    analyzer = _analyzer(runner)

    result = asyncio.run(analyzer.analyze(_input()))

    assert result.status is AnalysisStatus.SUCCEEDED
    assert result.request is not None
    assert result.request.required_fact_types == (FactType.VARIANT_AVAILABILITY,)
    assert result.failure is None
    assert result.agent_run_id == "run_analysis_1"
    assert result.profile_digest.startswith("sha256:")
    assert len(runner.calls) == 1
    invocation = runner.calls[0]
    assert invocation.model_config_ref == "analysis-fast-v1"
    assert [tool.name for tool in invocation.request.terminal_tools] == ["request_evidence"]
    assert invocation.request.model_input.to_dict() == {
        "bound_listing": {
            "binding_basis": "source_epoch",
            "binding_status": "certain",
            "epoch_id": "epc_velocity_1",
            "listing_id": "lst_velocity_aero_dash",
            "sku": "VK-AD-RC-001",
        },
        "question": "Do you have size 9?",
    }
    projection_text = json.dumps(invocation.request.to_provider_dict(), sort_keys=True)
    for forbidden in (
        "seller_id",
        "show_id",
        "send_authority",
        "credentials",
        "prior_chat",
        "r3_state",
        "oracle",
    ):
        assert forbidden not in projection_text


@pytest.mark.parametrize(
    ("response", "failure_code"),
    [
        (
            ModelResponse(model_id="scripted", terminal_calls=()),
            AnalysisFailureCode.MISSING_CALL,
        ),
        (
            ModelResponse(
                model_id="scripted",
                terminal_calls=(
                    ModelTerminalCall(tool_name="request_evidence", arguments_json="{}"),
                    ModelTerminalCall(tool_name="request_evidence", arguments_json="{}"),
                ),
            ),
            AnalysisFailureCode.MULTIPLE_CALLS,
        ),
        (
            _response({}, tool="send_reply"),
            AnalysisFailureCode.UNKNOWN_TOOL,
        ),
        (
            ModelResponse(
                model_id="scripted",
                terminal_calls=(
                    ModelTerminalCall(
                        tool_name="request_evidence",
                        arguments_json='{"intent":"answerable","intent":"unsupported"}',
                    ),
                ),
            ),
            AnalysisFailureCode.MALFORMED_REQUEST,
        ),
        (
            _response(
                {
                    "intent": "answerable",
                    "answer_category": "price",
                    "required_fact_types": ["current_price"],
                    "product_mentions": [],
                    "query_terms": [],
                    "seller_id": "sel_attacker",
                }
            ),
            AnalysisFailureCode.MALFORMED_REQUEST,
        ),
        (
            _response(
                {
                    "intent": "answerable",
                    "answer_category": "availability",
                    "required_fact_types": ["variant_availability"],
                    "product_mentions": [],
                    "variant_mentions": ["US M 9"],
                    "query_terms": [],
                }
            ),
            AnalysisFailureCode.MALFORMED_REQUEST,
        ),
    ],
)
def test_analysis_failures_are_typed_and_never_trigger_another_call(
    response: ModelResponse,
    failure_code: AnalysisFailureCode,
) -> None:
    runner = ScriptedModelRunner([response])
    analyzer = _analyzer(runner)

    result = asyncio.run(analyzer.analyze(_input()))

    assert result.status is AnalysisStatus.FAILED
    assert result.request is None
    assert result.failure is not None
    assert result.failure.code is failure_code
    assert len(runner.calls) == 1


def test_expired_analysis_starts_zero_provider_work() -> None:
    runner = ScriptedModelRunner([_response({})])
    analyzer = _analyzer(runner, monotonic=lambda: 105.0)

    result = asyncio.run(analyzer.analyze(_input()))

    assert result.failure is not None
    assert result.failure.code is AnalysisFailureCode.HARD_TIMEOUT
    assert runner.calls == ()


def test_provider_error_and_inflight_timeout_fail_closed() -> None:
    provider_error = ScriptedModelRunner([RuntimeError("provider detail must stay hidden")])
    failed = asyncio.run(
        _analyzer(provider_error).analyze(_input())
    )
    assert failed.failure is not None
    assert failed.failure.code is AnalysisFailureCode.PROVIDER_ERROR
    assert "provider detail" not in failed.failure.message

    class SlowRunner:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, _invocation):
            self.calls += 1
            await asyncio.sleep(0.05)
            return _response({})

    slow = SlowRunner()
    started = time.monotonic()
    timed_out = asyncio.run(
        _analyzer(slow, monotonic=time.monotonic).analyze(
            _input().model_copy(update={"deadline_monotonic_s": started + 0.02})
        )
    )
    assert timed_out.failure is not None
    assert timed_out.failure.code is AnalysisFailureCode.HARD_TIMEOUT
    assert slow.calls == 1
