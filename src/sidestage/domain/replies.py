"""Immutable reply lifecycle and effect-boundary contracts for SideStage."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


EntityId = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
NonEmptyText = Annotated[str, StringConstraints(strict=True, min_length=1)]
EvidenceId = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^evd_[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]


class FrozenReplyContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if value.utcoffset().total_seconds() != 0:
        raise ValueError(f"{field_name} must use UTC")
    return value


class QuestionState(str, Enum):
    QUEUED = "queued"
    AI_WORKING = "ai_working"
    AWAITING_REVIEW = "awaiting_review"
    AUTO_ANSWERED = "auto_answered"
    NEEDS_SELLER = "needs_seller"
    ANSWERED_BY_SELLER = "answered_by_seller"
    UNANSWERED = "unanswered"
    GROUPED = "grouped"


class ReplyRoute(str, Enum):
    ELIGIBLE = "eligible"
    NOISE = "noise"
    DUPLICATE = "duplicate"
    AMBIGUOUS_OR_UNSUPPORTED = "ambiguous_or_unsupported"
    ADVERSARIAL = "adversarial"


class BindingBasis(str, Enum):
    EXPLICIT = "explicit"
    SOURCE_EPOCH = "source_epoch"


class BindingStatus(str, Enum):
    CERTAIN = "certain"
    UNCERTAIN = "uncertain"


class AnswerCategory(str, Enum):
    PRICE = "price"
    AVAILABILITY = "availability"
    SHIPPING = "shipping"
    PAYMENT = "payment"
    RETURNS = "returns"
    CONDITION = "condition"
    AUTHENTICITY = "authenticity"
    SIZING = "sizing"
    PRODUCT_RESEARCH = "product_research"
    OTHER = "other"


class FactType(str, Enum):
    LISTING_IDENTITY = "listing_identity"
    CURRENT_PRICE = "current_price"
    VARIANT_AVAILABILITY = "variant_availability"
    AVAILABILITY_SUMMARY = "availability_summary"
    SHIPPING_POLICY = "shipping_policy"
    PAYMENT_POLICY = "payment_policy"
    RETURNS_POLICY = "returns_policy"
    RELEASE_DATE = "release_date"
    MSRP = "msrp"
    MATERIALS = "materials"
    SIZING = "sizing"
    AUTHENTICITY = "authenticity"
    CONDITION = "condition"


class ReplyTemplateId(str, Enum):
    CURRENT_PRICE = "reply_current_price"
    EXACT_VARIANT_AVAILABILITY = "reply_exact_variant_availability"
    SHIPPING_POLICY = "reply_shipping_policy"
    PAYMENT_POLICY = "reply_payment_policy"
    RETURNS_POLICY = "reply_returns_policy"
    AVAILABILITY_SUMMARY = "reply_availability_summary"
    LISTING_IDENTITY = "reply_listing_identity"
    RELEASE_DATE = "reply_release_date"
    MSRP = "reply_msrp"
    MATERIALS = "reply_materials"
    SIZING_GUIDANCE = "reply_sizing_guidance"
    AUTHENTICITY = "reply_authenticity"
    CONDITION = "reply_condition"
    NEEDS_SELLER = "needs_seller"
    NO_RESPONSE = "no_response"


class ListingIdentityField(str, Enum):
    TITLE = "title"
    SKU = "sku"
    COLORWAY = "colorway"


class AbstentionReason(str, Enum):
    NO_RESPONSE_NEEDED = "no_response_needed"
    AMBIGUOUS_QUESTION = "ambiguous_question"
    MISSING_EVIDENCE = "missing_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    PROMPT_INJECTION = "prompt_injection"
    UNSUPPORTED_REQUEST = "unsupported_request"
    PREVIOUS_LISTING = "previous_listing"
    STALE_STATE = "stale_state"
    GUARDRAIL_FAILURE = "guardrail_failure"
    CAPACITY = "capacity"
    TIMEOUT = "timeout"


class BrokerOutcome(str, Enum):
    DENY = "deny"
    REVIEW = "review"
    AUTO_SEND = "auto_send"
    NEEDS_SELLER = "needs_seller"
    NO_RESPONSE = "no_response"


_VALID_TRANSITIONS = {
    None: frozenset({QuestionState.QUEUED, QuestionState.GROUPED}),
    QuestionState.QUEUED: frozenset(
        {
            QuestionState.AI_WORKING,
            QuestionState.NEEDS_SELLER,
            QuestionState.GROUPED,
            QuestionState.UNANSWERED,
        }
    ),
    QuestionState.AI_WORKING: frozenset(
        {
            QuestionState.AWAITING_REVIEW,
            QuestionState.AUTO_ANSWERED,
            QuestionState.NEEDS_SELLER,
            QuestionState.UNANSWERED,
        }
    ),
    QuestionState.AWAITING_REVIEW: frozenset(
        {
            QuestionState.AI_WORKING,
            QuestionState.ANSWERED_BY_SELLER,
            QuestionState.NEEDS_SELLER,
            QuestionState.UNANSWERED,
        }
    ),
    QuestionState.NEEDS_SELLER: frozenset(
        {QuestionState.ANSWERED_BY_SELLER, QuestionState.UNANSWERED}
    ),
    QuestionState.AUTO_ANSWERED: frozenset(),
    QuestionState.ANSWERED_BY_SELLER: frozenset(),
    QuestionState.UNANSWERED: frozenset(),
    QuestionState.GROUPED: frozenset(),
}


class QuestionTransition(FrozenReplyContract):
    question_id: EntityId
    from_state: Optional[QuestionState]
    to_state: QuestionState
    asked_at: datetime
    state_changed_at: datetime
    reason_code: NonEmptyText

    @field_validator("asked_at")
    @classmethod
    def asked_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="asked_at")

    @field_validator("state_changed_at")
    @classmethod
    def state_changed_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="state_changed_at")

    @model_validator(mode="after")
    def validate_transition(self) -> "QuestionTransition":
        if self.to_state not in _VALID_TRANSITIONS[self.from_state]:
            source = self.from_state.value if self.from_state is not None else "initial"
            raise ValueError(f"invalid question transition {source} -> {self.to_state.value}")
        if self.state_changed_at < self.asked_at:
            raise ValueError("state_changed_at cannot precede asked_at")
        return self


class EvidenceClaim(FrozenReplyContract):
    reply_span: NonEmptyText
    evidence_ids: Annotated[Tuple[EvidenceId, ...], Field(min_length=1)]

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_are_unique(cls, values: Tuple[str, ...]) -> Tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("claim evidence IDs must be unique")
        return values


class RequestReplySendIntent(FrozenReplyContract):
    reply_text: NonEmptyText
    answer_category: AnswerCategory
    claims: Annotated[Tuple[EvidenceClaim, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def claim_spans_must_appear_in_reply(self) -> "RequestReplySendIntent":
        for claim in self.claims:
            if claim.reply_span not in self.reply_text:
                raise ValueError("every reply_span must be an exact substring of reply_text")
        return self


class TemplateSelectionIntent(FrozenReplyContract):
    """One semantic template choice; never customer-facing prose or factual values."""

    template_id: ReplyTemplateId
    evidence_ids: Annotated[Tuple[EvidenceId, ...], Field(max_length=8)] = ()
    identity_field: Optional[ListingIdentityField] = None
    reason_code: Optional[AbstentionReason] = None

    @model_validator(mode="after")
    def arguments_match_template(self) -> "TemplateSelectionIntent":
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("template evidence IDs must be unique")
        safe_terminal = self.template_id in {
            ReplyTemplateId.NEEDS_SELLER,
            ReplyTemplateId.NO_RESPONSE,
        }
        if safe_terminal and self.evidence_ids:
            raise ValueError("safe terminal template cannot select evidence")
        if not safe_terminal and not self.evidence_ids:
            raise ValueError("reply template requires selected evidence_ids")
        if self.template_id is ReplyTemplateId.EXACT_VARIANT_AVAILABILITY:
            if len(self.evidence_ids) != 1:
                raise ValueError("exact variant template requires one selected evidence ID")
            if self.identity_field is not None or self.reason_code is not None:
                raise ValueError("exact variant template accepts only evidence_ids")
            return self
        if self.template_id is ReplyTemplateId.AVAILABILITY_SUMMARY:
            if len(self.evidence_ids) != 1:
                raise ValueError("availability summary requires one aggregate evidence ID")
            if self.identity_field is not None or self.reason_code is not None:
                raise ValueError("availability summary accepts only evidence_ids")
            return self
        if self.template_id is ReplyTemplateId.LISTING_IDENTITY:
            if self.identity_field is None:
                raise ValueError("listing identity template requires identity_field")
            if self.reason_code is not None:
                raise ValueError("listing identity template accepts only identity_field")
            return self
        if safe_terminal:
            if self.reason_code is None:
                raise ValueError("safe terminal template requires reason_code")
            if self.identity_field is not None:
                raise ValueError("safe terminal template accepts only reason_code")
            if (
                self.template_id is ReplyTemplateId.NO_RESPONSE
                and self.reason_code
                not in {
                    AbstentionReason.NO_RESPONSE_NEEDED,
                    AbstentionReason.PROMPT_INJECTION,
                }
            ):
                raise ValueError("no_response requires a no-response reason")
            return self
        if any(value is not None for value in (self.identity_field, self.reason_code)):
            raise ValueError("selected template does not accept identity_field or reason_code")
        return self


class RenderedTemplateReply(FrozenReplyContract):
    template_id: ReplyTemplateId
    template_version: NonEmptyText
    intent: RequestReplySendIntent


class AbstainIntent(FrozenReplyContract):
    reason_code: AbstentionReason


class R3ValidatedFact(FrozenReplyContract):
    evidence_id: EvidenceId
    fact_type: Literal[
        FactType.CURRENT_PRICE,
        FactType.VARIANT_AVAILABILITY,
        FactType.SHIPPING_POLICY,
        FactType.PAYMENT_POLICY,
        FactType.RETURNS_POLICY,
    ]
    value: NonEmptyText
    source_ref: NonEmptyText
    source_version: Annotated[int, Field(strict=True, gt=0)]


class R3Authorization(FrozenReplyContract):
    capability_version: Annotated[int, Field(strict=True, gt=0)]
    seller_id: EntityId
    show_id: EntityId
    listing_id: EntityId
    sku: NonEmptyText
    epoch_id: EntityId
    answer_category: Literal[
        AnswerCategory.PRICE,
        AnswerCategory.AVAILABILITY,
        AnswerCategory.SHIPPING,
        AnswerCategory.PAYMENT,
        AnswerCategory.RETURNS,
    ]
    fact: R3ValidatedFact


class BrokerDecision(FrozenReplyContract):
    outcome: BrokerOutcome
    reason_code: NonEmptyText
    reply_text: Optional[NonEmptyText] = None
    evidence_ids: Tuple[EvidenceId, ...] = ()
    validated_category: Optional[AnswerCategory] = None
    r3_authorization: Optional[R3Authorization] = None
    template_id: Optional[ReplyTemplateId] = None
    template_version: Optional[NonEmptyText] = None

    @field_validator("evidence_ids")
    @classmethod
    def decision_evidence_ids_are_unique(cls, values: Tuple[str, ...]) -> Tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("broker decision evidence IDs must be unique")
        return values

    @model_validator(mode="after")
    def reply_text_matches_outcome(self) -> "BrokerDecision":
        exposes_reply = self.outcome in {BrokerOutcome.REVIEW, BrokerOutcome.AUTO_SEND}
        if exposes_reply and self.reply_text is None:
            raise ValueError("review or auto-send broker outcome requires reply text")
        if not exposes_reply and self.reply_text is not None:
            raise ValueError("deny or no-response broker outcome cannot expose reply text")
        if self.outcome is BrokerOutcome.AUTO_SEND and self.r3_authorization is None:
            raise ValueError("auto-send requires a versioned R3 authorization")
        if self.outcome is not BrokerOutcome.AUTO_SEND and self.r3_authorization is not None:
            raise ValueError("only auto-send may carry R3 authorization")
        if (self.template_id is None) != (self.template_version is None):
            raise ValueError("template ID and version must be recorded together")
        return self


class ReplyReceipt(FrozenReplyContract):
    receipt_id: EntityId
    reply_id: EntityId
    question_id: EntityId
    canonical_question_id: EntityId
    seller_id: EntityId
    show_id: EntityId
    actor_id: EntityId
    mode: Literal["r2", "r3"]
    reply_text: NonEmptyText
    evidence_ids: Tuple[EvidenceId, ...]
    broker_outcome: BrokerOutcome
    guardrail_verdict: NonEmptyText
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="created_at")

    @field_validator("evidence_ids")
    @classmethod
    def receipt_evidence_ids_are_unique(cls, values: Tuple[str, ...]) -> Tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("receipt evidence IDs must be unique")
        return values
