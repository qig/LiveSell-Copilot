"""Typed analysis, evidence, and M3A projection contracts for M3B."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Tuple

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from sidestage.agent_core import AgentProfile, AgentTask
from sidestage.domain.replies import (
    AnswerCategory,
    BindingBasis,
    BindingStatus,
    EntityId,
    EvidenceId,
    FactType,
    NonEmptyText,
)


class FrozenCopilotContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if value.utcoffset().total_seconds() != 0:
        raise ValueError(f"{field_name} must use UTC")
    return value


class AnalysisIntent(str, Enum):
    ANSWERABLE = "answerable"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"
    ADVERSARIAL = "adversarial"
    NO_RESPONSE_NEEDED = "no_response_needed"


class EvidenceSource(str, Enum):
    MARKETPLACE_STATE = "marketplace_state"
    SELLER_POLICY = "seller_policy"
    PRODUCT_CATALOG = "product_catalog"
    PRODUCT_RESEARCH = "product_research"


class EvidenceRequest(FrozenCopilotContract):
    """Untrusted output of the bounded first LLM request."""

    intent: AnalysisIntent
    answer_category: AnswerCategory
    product_mentions: Annotated[Tuple[NonEmptyText, ...], Field(max_length=4)] = ()
    variant_mentions: Annotated[Tuple[NonEmptyText, ...], Field(max_length=4)] = ()
    required_fact_types: Annotated[Tuple[FactType, ...], Field(max_length=8)] = ()
    query_terms: Annotated[Tuple[NonEmptyText, ...], Field(max_length=6)] = ()

    @field_validator(
        "product_mentions",
        "variant_mentions",
        "required_fact_types",
        "query_terms",
    )
    @classmethod
    def entries_are_unique(cls, values: tuple) -> tuple:
        normalized = [str(value).casefold() for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("analysis request entries must be unique")
        return values

    @model_validator(mode="after")
    def answerable_requests_require_facts(self) -> "EvidenceRequest":
        if self.intent is AnalysisIntent.ANSWERABLE and not self.required_fact_types:
            raise ValueError("answerable analysis requires at least one fact type")
        return self


class BoundListing(FrozenCopilotContract):
    listing_id: EntityId
    sku: Annotated[
        str,
        StringConstraints(strict=True, pattern=r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+$"),
    ]
    epoch_id: EntityId
    binding_basis: BindingBasis
    binding_status: BindingStatus


class EvidenceRecord(FrozenCopilotContract):
    evidence_id: EvidenceId
    seller_id: EntityId
    listing_id: EntityId
    fact_type: FactType
    value: NonEmptyText
    source: EvidenceSource
    source_ref: NonEmptyText
    source_version: Annotated[int, Field(strict=True, gt=0)]
    observed_at: datetime
    provenance: Literal["synthetic_seller_data"]

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="observed_at")

    def model_projection(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "fact_type": self.fact_type.value,
            "value": self.value,
            "source": self.source.value,
            "source_ref": self.source_ref,
            "source_version": self.source_version,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "provenance": self.provenance,
        }


class EvidenceSnapshot(FrozenCopilotContract):
    snapshot_id: EntityId
    seller_id: EntityId
    show_id: EntityId
    listing_id: EntityId
    epoch_id: EntityId
    created_at: datetime
    records: Annotated[Tuple[EvidenceRecord, ...], Field(min_length=1)]

    @field_validator("created_at")
    @classmethod
    def created_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="created_at")

    @model_validator(mode="after")
    def records_match_snapshot_scope(self) -> "EvidenceSnapshot":
        evidence_ids = [record.evidence_id for record in self.records]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("snapshot evidence IDs must be unique")
        for record in self.records:
            if record.seller_id != self.seller_id:
                raise ValueError("evidence record seller does not match snapshot seller")
            if record.listing_id != self.listing_id:
                raise ValueError("evidence record listing does not match snapshot listing")
            if record.observed_at > self.created_at:
                raise ValueError("evidence cannot be observed after snapshot creation")
        return self


class ReplyTone(FrozenCopilotContract):
    voice: Literal["energetic_concise", "precise_reserved", "fast_direct"]
    max_reply_chars: Annotated[int, Field(strict=True, gt=0, le=500)]
    emoji_mode: Literal["none", "light"]
    prohibited_phrases: Annotated[Tuple[NonEmptyText, ...], Field(min_length=1)]


class ReplyTask(FrozenCopilotContract):
    """Adapter-owned task; projection strips tenant/effect authority before M3A."""

    question_id: EntityId
    trace_id: EntityId
    analysis_id: EntityId
    seller_id: EntityId
    show_id: EntityId
    asked_at: datetime
    deadline_monotonic_s: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
    question: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=240)]
    bound_listing: BoundListing
    evidence_snapshot: EvidenceSnapshot
    answer_category: AnswerCategory
    tone: ReplyTone

    @field_validator("asked_at")
    @classmethod
    def asked_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="asked_at")

    @model_validator(mode="after")
    def validate_trusted_scope(self) -> "ReplyTask":
        if self.bound_listing.binding_status is not BindingStatus.CERTAIN:
            raise ValueError("reply task requires certain listing binding")
        snapshot = self.evidence_snapshot
        if snapshot.seller_id != self.seller_id:
            raise ValueError("evidence snapshot seller does not match reply task seller")
        if snapshot.show_id != self.show_id:
            raise ValueError("evidence snapshot show does not match reply task show")
        if snapshot.listing_id != self.bound_listing.listing_id:
            raise ValueError("evidence snapshot listing does not match bound listing")
        if snapshot.epoch_id != self.bound_listing.epoch_id:
            raise ValueError("evidence snapshot epoch does not match bound epoch")
        return self

    def model_projection(self) -> dict:
        return {
            "question": {
                "question_id": self.question_id,
                "text": self.question,
                "asked_at": self.asked_at.isoformat().replace("+00:00", "Z"),
            },
            "bound_listing": self.bound_listing.model_dump(mode="json"),
            "evidence": [record.model_projection() for record in self.evidence_snapshot.records],
            "tone": self.tone.model_dump(mode="json"),
            "answer_category": self.answer_category.value,
        }


class TemplateSelectionTask(FrozenCopilotContract):
    """Adapter-owned challenger task; authority and tone stay outside model input."""

    question_id: EntityId
    trace_id: EntityId
    seller_id: EntityId
    show_id: EntityId
    asked_at: datetime
    deadline_monotonic_s: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
    question: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=240)]
    bound_listing: BoundListing
    evidence_snapshot: EvidenceSnapshot
    tone: ReplyTone

    @field_validator("asked_at")
    @classmethod
    def asked_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="asked_at")

    @model_validator(mode="after")
    def validate_trusted_scope(self) -> "TemplateSelectionTask":
        if self.bound_listing.binding_status is not BindingStatus.CERTAIN:
            raise ValueError("template selection task requires certain listing binding")
        snapshot = self.evidence_snapshot
        if snapshot.seller_id != self.seller_id:
            raise ValueError("evidence snapshot seller does not match template task seller")
        if snapshot.show_id != self.show_id:
            raise ValueError("evidence snapshot show does not match template task show")
        if snapshot.listing_id != self.bound_listing.listing_id:
            raise ValueError("evidence snapshot listing does not match bound listing")
        if snapshot.epoch_id != self.bound_listing.epoch_id:
            raise ValueError("evidence snapshot epoch does not match bound epoch")
        return self

    def model_projection(self) -> dict:
        return {
            "question": {
                "question_id": self.question_id,
                "text": self.question,
                "asked_at": self.asked_at.isoformat().replace("+00:00", "Z"),
            },
            "bound_listing": self.bound_listing.model_dump(mode="json"),
            "evidence": [
                record.model_projection()
                for record in sorted(
                    self.evidence_snapshot.records,
                    key=lambda item: item.evidence_id,
                )
            ],
        }


def project_reply_task(
    task: ReplyTask,
    *,
    profile: AgentProfile,
    profile_digest: str,
) -> AgentTask:
    """Project only model-visible reply data plus safe correlation identifiers."""

    if profile.adapter_id != "sidestage.reply":
        raise ValueError("reply task requires the sidestage.reply profile")
    return AgentTask(
        task_id=task.question_id,
        adapter_id=profile.adapter_id,
        profile_version=profile.profile_version,
        profile_digest=profile_digest,
        deadline_monotonic_s=task.deadline_monotonic_s,
        model_input=task.model_projection(),
        correlation_metadata={
            "trace_id": task.trace_id,
            "question_id": task.question_id,
            "analysis_id": task.analysis_id,
            "snapshot_id": task.evidence_snapshot.snapshot_id,
        },
    )


def project_template_selection_task(
    task: TemplateSelectionTask,
    *,
    profile: AgentProfile,
    profile_digest: str,
) -> AgentTask:
    """Project a one-call template task without seller authority or reply prose."""

    if profile.adapter_id != "sidestage.reply_template":
        raise ValueError("template task requires the sidestage.reply_template profile")
    return AgentTask(
        task_id=task.question_id,
        adapter_id=profile.adapter_id,
        profile_version=profile.profile_version,
        profile_digest=profile_digest,
        deadline_monotonic_s=task.deadline_monotonic_s,
        model_input=task.model_projection(),
        correlation_metadata={
            "trace_id": task.trace_id,
            "question_id": task.question_id,
            "snapshot_id": task.evidence_snapshot.snapshot_id,
        },
    )
