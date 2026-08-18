from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from sidestage.agent_core import ModelResponse, ModelTerminalCall, RunStatus, ScriptedModelRunner
from sidestage.copilot.contracts import (
    BoundListing,
    EvidenceRecord,
    EvidenceSnapshot,
    EvidenceSource,
    ReplyTask,
    ReplyTone,
    TemplateSelectionTask,
)
from sidestage.copilot.profile import (
    LIVESSELL_ADAPTER_ID,
    LIVESSELL_TEMPLATE_ADAPTER_ID,
    build_livesell_reply_profile,
    build_livesell_template_profile,
    decode_livesell_intent,
    decode_template_selection,
    register_livesell_reply_agent,
    register_livesell_template_agent,
)
from sidestage.domain.replies import (
    AnswerCategory,
    BindingBasis,
    BindingStatus,
    FactType,
    ReplyTemplateId,
    RequestReplySendIntent,
    TemplateSelectionIntent,
)


NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def make_reply_task(*, question_id: str = "qst_profile_1", show_id: str = "show_velocity"):
    snapshot = EvidenceSnapshot(
        snapshot_id=f"snp_{question_id}",
        seller_id="sel_velocity_kicks",
        show_id=show_id,
        listing_id="lst_velocity_aero_dash",
        epoch_id="epc_velocity_1",
        created_at=NOW,
        records=(
            EvidenceRecord(
                evidence_id="evd_price_profile",
                seller_id="sel_velocity_kicks",
                listing_id="lst_velocity_aero_dash",
                fact_type=FactType.CURRENT_PRICE,
                value="USD 160.00",
                source=EvidenceSource.MARKETPLACE_STATE,
                source_ref="sqlite:listings/lst_velocity_aero_dash/price_cents",
                source_version=1,
                observed_at=NOW,
                provenance="synthetic_seller_data",
            ),
        ),
    )
    return ReplyTask(
        question_id=question_id,
        trace_id=f"trc_{question_id}",
        analysis_id=f"ana_{question_id}",
        seller_id="sel_velocity_kicks",
        show_id=show_id,
        asked_at=NOW,
        deadline_monotonic_s=105.0,
        question="How much is this pair?",
        bound_listing=BoundListing(
            listing_id="lst_velocity_aero_dash",
            sku="VK-AD-RC-001",
            epoch_id="epc_velocity_1",
            binding_basis=BindingBasis.SOURCE_EPOCH,
            binding_status=BindingStatus.CERTAIN,
        ),
        evidence_snapshot=snapshot,
        answer_category=AnswerCategory.PRICE,
        tone=ReplyTone(
            voice="energetic_concise",
            max_reply_chars=180,
            emoji_mode="light",
            prohibited_phrases=("cheapest anywhere",),
        ),
    )


def valid_reply_response() -> ModelResponse:
    return ModelResponse(
        model_id="scripted-reply",
        terminal_calls=(
            ModelTerminalCall(
                tool_name="request_reply_send",
                arguments_json=json.dumps(
                    {
                        "reply_text": "It is $160.",
                        "answer_category": "price",
                        "claims": [
                            {
                                "reply_span": "It is $160.",
                                "evidence_ids": ["evd_price_profile"],
                            }
                        ],
                    }
                ),
            ),
        ),
    )


def make_template_task() -> TemplateSelectionTask:
    draft = make_reply_task()
    return TemplateSelectionTask(
        question_id=draft.question_id,
        trace_id=draft.trace_id,
        seller_id=draft.seller_id,
        show_id=draft.show_id,
        asked_at=draft.asked_at,
        deadline_monotonic_s=draft.deadline_monotonic_s,
        question=draft.question,
        bound_listing=draft.bound_listing,
        evidence_snapshot=draft.evidence_snapshot,
        tone=draft.tone,
    )


def test_livesell_profile_registers_exactly_two_terminal_tools_and_no_effect_tools() -> None:
    profile = build_livesell_reply_profile(model_config_ref="luna-fast-v1")

    assert profile.adapter_id == LIVESSELL_ADAPTER_ID == "sidestage.reply"
    assert [tool.name for tool in profile.terminal_tools] == [
        "request_reply_send",
        "abstain",
    ]
    assert profile.queue_policy.capacity == 12
    assert profile.queue_policy.max_concurrency == 12
    tool_names = {tool.name for tool in profile.terminal_tools}
    for forbidden_tool in (
        "lookup_catalog",
        "search",
        "send_reply_directly",
        "push_listing",
        "swap_listing",
        "markdown_listing",
        "update_inventory",
        "memory",
        "fallback_provider",
    ):
        assert forbidden_tool not in tool_names
    request_schema = profile.terminal_tools[0].parameters_schema.to_dict()
    assert set(request_schema["properties"]) == {
        "reply_text",
        "answer_category",
        "claims",
    }
    claim_schema = request_schema["properties"]["claims"]["items"]
    assert set(claim_schema["properties"]) == {"reply_span", "evidence_ids"}


def test_registered_handle_runs_the_public_m3a_core_and_decodes_typed_intent() -> None:
    runner = ScriptedModelRunner([valid_reply_response()])
    handle = register_livesell_reply_agent(
        runner,
        model_config_ref="luna-fast-v1",
        monotonic=lambda: 100.0,
        core_id_factory=iter(("run_profile_1", "trace_unused")).__next__,
    )

    result = asyncio.run(handle.run(make_reply_task()))
    decoded = decode_livesell_intent(result)

    assert result.status is RunStatus.SUCCEEDED
    assert isinstance(decoded, RequestReplySendIntent)
    assert decoded.claims[0].reply_span == "It is $160."
    assert len(runner.calls) == 1
    assert handle.registered_profile.digest == result.profile_digest
    assert handle.registered_profile.profile.adapter_id == result.adapter_id
    assert handle.per_show_capacity == 64
    assert handle.per_show_concurrency == 4
    assert handle.global_concurrency == 12
    provider_input = runner.calls[0].request.model_input.to_dict()
    assert "seller_id" not in provider_input
    assert "show_id" not in provider_input
    assert provider_input["question"]["question_id"] == "qst_profile_1"


def test_livesell_profile_rejects_authority_inside_terminal_arguments() -> None:
    response = valid_reply_response()
    arguments = json.loads(response.terminal_calls[0].arguments_json)
    arguments["send_authority"] = True
    runner = ScriptedModelRunner(
        [
            ModelResponse(
                model_id="scripted-reply",
                terminal_calls=(
                    ModelTerminalCall(
                        tool_name="request_reply_send",
                        arguments_json=json.dumps(arguments),
                    ),
                ),
            )
        ]
    )
    handle = register_livesell_reply_agent(
        runner,
        model_config_ref="luna-fast-v1",
        monotonic=lambda: 100.0,
    )

    result = asyncio.run(handle.run(make_reply_task()))

    assert result.status is RunStatus.FAILED
    assert result.failure.code.value == "malformed_arguments"
    assert len(runner.calls) == 1


def test_template_profile_registers_only_the_closed_approved_catalog() -> None:
    profile = build_livesell_template_profile(model_config_ref="openrouter-screen-v1")

    assert profile.adapter_id == LIVESSELL_TEMPLATE_ADAPTER_ID == "sidestage.reply_template"
    assert [tool.name for tool in profile.terminal_tools] == [
        template.value for template in ReplyTemplateId
    ]
    for tool in profile.terminal_tools:
        properties = set(tool.parameters_schema.to_dict()["properties"])
        assert "reply_text" not in properties
        assert "price" not in properties
        assert "quantity" not in properties
        assert "send_authority" not in properties
        if tool.name in {
            ReplyTemplateId.NEEDS_SELLER.value,
            ReplyTemplateId.NO_RESPONSE.value,
        }:
            assert "evidence_ids" not in properties
        else:
            assert "evidence_ids" in properties


def test_registered_template_handle_makes_one_call_and_excludes_authority_and_tone() -> None:
    runner = ScriptedModelRunner(
        [
            ModelResponse(
                model_id="scripted-template",
                terminal_calls=(
                    ModelTerminalCall(
                        tool_name=ReplyTemplateId.CURRENT_PRICE.value,
                        arguments_json='{"evidence_ids":["evd_price_profile"]}',
                    ),
                ),
            )
        ]
    )
    handle = register_livesell_template_agent(
        runner,
        model_config_ref="openrouter-screen-v1",
        monotonic=lambda: 100.0,
        core_id_factory=iter(("run_template_1", "trace_unused")).__next__,
    )

    result = asyncio.run(handle.run(make_template_task()))
    decoded = decode_template_selection(result)

    assert result.status is RunStatus.SUCCEEDED
    assert decoded == TemplateSelectionIntent(
        template_id=ReplyTemplateId.CURRENT_PRICE,
        evidence_ids=("evd_price_profile",),
    )
    assert len(runner.calls) == 1
    projection = runner.calls[0].request.model_input.to_dict()
    assert "seller_id" not in projection
    assert "show_id" not in projection
    assert "tone" not in projection
    assert "answer_category" not in projection
    assert "reply_text" not in json.dumps(projection)


def test_template_profile_rejects_model_authored_reply_text() -> None:
    runner = ScriptedModelRunner(
        [
            ModelResponse(
                model_id="scripted-template",
                terminal_calls=(
                    ModelTerminalCall(
                        tool_name=ReplyTemplateId.CURRENT_PRICE.value,
                        arguments_json=(
                            '{"evidence_ids":["evd_price_profile"],'
                            '"reply_text":"Trust me, it is cheap."}'
                        ),
                    ),
                ),
            )
        ]
    )
    handle = register_livesell_template_agent(
        runner,
        model_config_ref="openrouter-screen-v1",
        monotonic=lambda: 100.0,
    )

    result = asyncio.run(handle.run(make_template_task()))

    assert result.status is RunStatus.FAILED
    assert result.failure.code.value == "malformed_arguments"
    assert len(runner.calls) == 1
