from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from sidestage.agent_core import (
    AgentProfile,
    DeadlinePolicy,
    QueuePolicy,
    TerminalToolSchema,
    register_profile,
)
from sidestage.copilot.contracts import (
    AnalysisIntent,
    BoundListing,
    EvidenceRecord,
    EvidenceRequest,
    EvidenceSnapshot,
    EvidenceSource,
    ReplyTask,
    ReplyTone,
    project_reply_task,
)
from sidestage.domain.replies import (
    AbstainIntent,
    AbstentionReason,
    AnswerCategory,
    BindingBasis,
    BindingStatus,
    BrokerDecision,
    BrokerOutcome,
    EvidenceClaim,
    FactType,
    QuestionState,
    QuestionTransition,
    ReplyReceipt,
    ReplyRoute,
    RequestReplySendIntent,
)


NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def _reply_profile() -> tuple[AgentProfile, str]:
    profile = AgentProfile(
        adapter_id="sidestage.reply",
        profile_version="1.0.0",
        system_policy="Use only supplied evidence and select one terminal tool.",
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "object"},
                "bound_listing": {"type": "object"},
                "evidence": {"type": "array"},
                "tone": {"type": "object"},
                "answer_category": {"type": "string"},
            },
            "required": [
                "question",
                "bound_listing",
                "evidence",
                "tone",
                "answer_category",
            ],
            "additionalProperties": False,
        },
        terminal_tools=(
            TerminalToolSchema(
                name="request_reply_send",
                description="Request one evidence-backed reply.",
                parameters_schema={
                    "type": "object",
                    "properties": {"reply_text": {"type": "string"}},
                    "required": ["reply_text"],
                    "additionalProperties": False,
                },
            ),
        ),
        queue_policy=QueuePolicy(capacity=64, max_concurrency=4),
        deadline_policy=DeadlinePolicy(default_timeout_ms=5_000, max_timeout_ms=5_000),
        model_config_ref="gpt-5.6-luna-none",
        max_model_input_bytes=16_384,
    )
    return profile, register_profile(profile).digest


def _snapshot(*, seller_id: str = "sel_velocity_kicks") -> EvidenceSnapshot:
    return EvidenceSnapshot(
        snapshot_id="snp_contract_1",
        seller_id=seller_id,
        show_id="show_velocity_kicks",
        listing_id="lst_velocity_aero_dash",
        epoch_id="epc_velocity_1",
        created_at=NOW,
        records=(
            EvidenceRecord(
                evidence_id="evd_price_1",
                seller_id=seller_id,
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


def _task(*, snapshot: EvidenceSnapshot | None = None) -> ReplyTask:
    return ReplyTask(
        question_id="qst_contract_1",
        trace_id="trc_contract_1",
        analysis_id="ana_contract_1",
        seller_id="sel_velocity_kicks",
        show_id="show_velocity_kicks",
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
        evidence_snapshot=snapshot or _snapshot(),
        answer_category=AnswerCategory.PRICE,
        tone=ReplyTone(
            voice="energetic_concise",
            max_reply_chars=180,
            emoji_mode="light",
            prohibited_phrases=("cheapest anywhere",),
        ),
    )


def test_closed_reply_contracts_are_immutable_and_forbid_authority_extras() -> None:
    request = EvidenceRequest(
        intent=AnalysisIntent.ANSWERABLE,
        answer_category=AnswerCategory.AVAILABILITY,
        product_mentions=("Aero Dash",),
        variant_mentions=("US M 9",),
        required_fact_types=(FactType.VARIANT_AVAILABILITY,),
        query_terms=("Aero Dash US M 9",),
    )
    intent = RequestReplySendIntent(
        reply_text="Size 9 is available.",
        answer_category=AnswerCategory.AVAILABILITY,
        claims=(
            EvidenceClaim(
                reply_span="Size 9 is available.",
                evidence_ids=("evd_stock_1",),
            ),
        ),
    )

    assert request.intent is AnalysisIntent.ANSWERABLE
    assert intent.claims[0].evidence_ids == ("evd_stock_1",)
    assert AbstainIntent(reason_code=AbstentionReason.MISSING_EVIDENCE).reason_code

    with pytest.raises(ValidationError):
        request.intent = AnalysisIntent.NO_RESPONSE_NEEDED  # type: ignore[misc]
    with pytest.raises(ValidationError):
        EvidenceRequest.model_validate(
            {
                **request.model_dump(),
                "seller_id": "sel_attacker",
                "send_authority": True,
            }
        )
    with pytest.raises(ValidationError):
        RequestReplySendIntent.model_validate(
            {**intent.model_dump(), "effect_identity": "send_directly"}
        )


def test_question_transition_requires_trusted_times_and_valid_state_edges() -> None:
    queued = QuestionTransition(
        question_id="qst_contract_1",
        from_state=None,
        to_state=QuestionState.QUEUED,
        asked_at=NOW,
        state_changed_at=NOW,
        reason_code="accepted",
    )
    working = QuestionTransition(
        question_id=queued.question_id,
        from_state=QuestionState.QUEUED,
        to_state=QuestionState.AI_WORKING,
        asked_at=NOW,
        state_changed_at=NOW + timedelta(milliseconds=10),
        reason_code="analysis_started",
    )

    assert working.to_state is QuestionState.AI_WORKING

    with pytest.raises(ValidationError, match="transition"):
        QuestionTransition(
            question_id=queued.question_id,
            from_state=QuestionState.QUEUED,
            to_state=QuestionState.AUTO_ANSWERED,
            asked_at=NOW,
            state_changed_at=NOW,
            reason_code="invalid_jump",
        )
    with pytest.raises(ValidationError, match="state_changed_at"):
        QuestionTransition(
            question_id=queued.question_id,
            from_state=QuestionState.QUEUED,
            to_state=QuestionState.AI_WORKING,
            asked_at=NOW,
            state_changed_at=NOW - timedelta(milliseconds=1),
            reason_code="bad_clock",
        )
    with pytest.raises(ValidationError):
        QuestionTransition(
            question_id=queued.question_id,
            from_state=None,
            to_state=QuestionState.QUEUED,
            asked_at=datetime(2026, 8, 17, 12, 0),
            state_changed_at=NOW,
            reason_code="naive_time",
        )


def test_reply_task_rejects_foreign_evidence_and_uncertain_binding() -> None:
    with pytest.raises(ValidationError, match="seller"):
        _task(snapshot=_snapshot(seller_id="sel_vault_consign"))

    payload = _task().model_dump()
    payload["bound_listing"]["binding_status"] = BindingStatus.UNCERTAIN
    with pytest.raises(ValidationError, match="certain"):
        ReplyTask.model_validate(payload)


def test_projection_contains_only_bounded_model_input_and_safe_correlation() -> None:
    profile, digest = _reply_profile()
    agent_task = project_reply_task(
        _task(),
        profile=profile,
        profile_digest=digest,
    )
    model_input = agent_task.model_input.to_dict()
    correlation = agent_task.correlation_metadata.to_dict()

    assert model_input == {
        "answer_category": "price",
        "bound_listing": {
            "binding_basis": "source_epoch",
            "binding_status": "certain",
            "epoch_id": "epc_velocity_1",
            "listing_id": "lst_velocity_aero_dash",
            "sku": "VK-AD-RC-001",
        },
        "evidence": [
            {
                "evidence_id": "evd_price_1",
                "fact_type": "current_price",
                "observed_at": "2026-08-17T12:00:00Z",
                "provenance": "synthetic_seller_data",
                "source": "marketplace_state",
                "source_ref": "sqlite:listings/lst_velocity_aero_dash/price_cents",
                "source_version": 1,
                "value": "USD 160.00",
            }
        ],
        "question": {
            "asked_at": "2026-08-17T12:00:00Z",
            "question_id": "qst_contract_1",
            "text": "How much is this pair?",
        },
        "tone": {
            "emoji_mode": "light",
            "max_reply_chars": 180,
            "prohibited_phrases": ["cheapest anywhere"],
            "voice": "energetic_concise",
        },
    }
    assert correlation == {
        "analysis_id": "ana_contract_1",
        "question_id": "qst_contract_1",
        "snapshot_id": "snp_contract_1",
        "trace_id": "trc_contract_1",
    }
    forbidden = {
        "seller_id",
        "show_id",
        "customer_memory",
        "prior_chat",
        "r3_state",
        "credentials",
        "oracle",
        "send_authority",
    }
    assert forbidden.isdisjoint(model_input)
    assert forbidden.isdisjoint(correlation)
    assert agent_task.adapter_id == "sidestage.reply"
    assert agent_task.profile_digest == digest


def test_reply_receipt_requires_one_brokered_terminal_outcome() -> None:
    decision = BrokerDecision(
        outcome=BrokerOutcome.REVIEW,
        reason_code="supported_for_review",
        reply_text="It is $160.",
        evidence_ids=("evd_price_1",),
    )
    receipt = ReplyReceipt(
        receipt_id="rrc_contract_1",
        reply_id="rpl_contract_1",
        question_id="qst_contract_1",
        canonical_question_id="qst_contract_1",
        seller_id="sel_velocity_kicks",
        show_id="show_velocity_kicks",
        actor_id="demo_velocity_kicks",
        mode="r2",
        reply_text="It is $160.",
        evidence_ids=("evd_price_1",),
        broker_outcome=BrokerOutcome.REVIEW,
        guardrail_verdict="supported",
        created_at=NOW,
    )

    assert decision.reply_text == receipt.reply_text
    assert receipt.broker_outcome is BrokerOutcome.REVIEW
    assert ReplyRoute.ELIGIBLE.value == "eligible"
    with pytest.raises(ValidationError):
        ReplyReceipt.model_validate({**receipt.model_dump(), "model_authorized": True})
    with pytest.raises(ValidationError, match="reply text"):
        BrokerDecision(
            outcome=BrokerOutcome.AUTO_SEND,
            reason_code="missing_text",
            evidence_ids=("evd_price_1",),
        )
