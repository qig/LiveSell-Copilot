"""Versioned application-owned rendering for approved livesell reply templates."""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from sidestage.copilot.contracts import EvidenceRecord, TemplateSelectionTask
from sidestage.domain.replies import (
    AnswerCategory,
    EvidenceClaim,
    FactType,
    ListingIdentityField,
    RenderedTemplateReply,
    ReplyTemplateId,
    RequestReplySendIntent,
    TemplateSelectionIntent,
)


APPROVED_REPLY_TEMPLATE_VERSION = "1.0.0"


class TemplateRenderError(ValueError):
    """A semantic selection cannot be rendered safely from the trusted snapshot."""


_SINGLE_FACT_TEMPLATE = {
    ReplyTemplateId.CURRENT_PRICE: (FactType.CURRENT_PRICE, AnswerCategory.PRICE, "Current price"),
    ReplyTemplateId.SHIPPING_POLICY: (FactType.SHIPPING_POLICY, AnswerCategory.SHIPPING, "Shipping"),
    ReplyTemplateId.PAYMENT_POLICY: (FactType.PAYMENT_POLICY, AnswerCategory.PAYMENT, "Payment"),
    ReplyTemplateId.RETURNS_POLICY: (FactType.RETURNS_POLICY, AnswerCategory.RETURNS, "Returns"),
    ReplyTemplateId.RELEASE_DATE: (FactType.RELEASE_DATE, AnswerCategory.PRODUCT_RESEARCH, "Release date"),
    ReplyTemplateId.MSRP: (FactType.MSRP, AnswerCategory.PRODUCT_RESEARCH, "MSRP"),
    ReplyTemplateId.MATERIALS: (FactType.MATERIALS, AnswerCategory.PRODUCT_RESEARCH, "Materials"),
    ReplyTemplateId.SIZING_GUIDANCE: (FactType.SIZING, AnswerCategory.SIZING, "Sizing"),
    ReplyTemplateId.AUTHENTICITY: (FactType.AUTHENTICITY, AnswerCategory.AUTHENTICITY, "Authenticity"),
    ReplyTemplateId.CONDITION: (FactType.CONDITION, AnswerCategory.CONDITION, "Condition"),
}


def render_approved_template(
    selection: TemplateSelectionIntent,
    task: TemplateSelectionTask,
) -> RenderedTemplateReply:
    """Materialize customer text from trusted evidence; never from model prose."""

    if selection.template_id in {ReplyTemplateId.NEEDS_SELLER, ReplyTemplateId.NO_RESPONSE}:
        raise TemplateRenderError("safe terminal selection does not render a reply")

    selected_records = _selected_records(selection, task)

    if selection.template_id in _SINGLE_FACT_TEMPLATE:
        fact_type, category, label = _SINGLE_FACT_TEMPLATE[selection.template_id]
        record = _only_selected_fact(selected_records, fact_type)
        return _render(selection.template_id, task, category, f"{label}: {record.value}", (record,))

    if selection.template_id is ReplyTemplateId.EXACT_VARIANT_AVAILABILITY:
        record = _variant_record(selected_records, selection.variant_id or "")
        if len(selected_records) != 1:
            raise TemplateRenderError("exact variant template requires exactly one evidence record")
        return _render(
            selection.template_id,
            task,
            AnswerCategory.AVAILABILITY,
            f"Availability: {record.value}",
            (record,),
        )

    if selection.template_id is ReplyTemplateId.AVAILABILITY_SUMMARY:
        all_variant_records = tuple(
            sorted(
                _records(task.evidence_snapshot.records, FactType.VARIANT_AVAILABILITY),
                key=lambda item: _natural_key(item.value),
            )
        )
        selected_ids = {record.evidence_id for record in selected_records}
        expected_ids = {record.evidence_id for record in all_variant_records}
        if selected_ids != expected_ids:
            raise TemplateRenderError("availability summary must select every trusted variant record")
        records = all_variant_records
        if not records:
            raise TemplateRenderError("availability summary requires at least one variant")
        reply_text = "Available variants: " + "; ".join(record.value for record in records)
        return _render(
            selection.template_id,
            task,
            AnswerCategory.AVAILABILITY,
            reply_text,
            records,
            claim_values_only=True,
        )

    if selection.template_id is ReplyTemplateId.LISTING_IDENTITY:
        record = _only_selected_fact(selected_records, FactType.LISTING_IDENTITY)
        reply_text = _render_identity(record.value, selection.identity_field)
        return _render(
            selection.template_id,
            task,
            AnswerCategory.PRODUCT_RESEARCH,
            reply_text,
            (record,),
            claim_values_only=False,
        )

    raise TemplateRenderError("template is not registered by the approved renderer")


def _render(
    template_id: ReplyTemplateId,
    task: TemplateSelectionTask,
    category: AnswerCategory,
    reply_text: str,
    records: Sequence[EvidenceRecord],
    *,
    claim_values_only: bool = True,
) -> RenderedTemplateReply:
    if len(reply_text) > task.tone.max_reply_chars:
        raise TemplateRenderError("rendered reply exceeds the approved tone length")
    lowered = reply_text.casefold()
    if any(phrase.casefold() in lowered for phrase in task.tone.prohibited_phrases):
        raise TemplateRenderError("rendered reply violates the approved tone policy")
    claims = tuple(
        EvidenceClaim(
            reply_span=record.value if claim_values_only else reply_text,
            evidence_ids=(record.evidence_id,),
        )
        for record in records
    )
    return RenderedTemplateReply(
        template_id=template_id,
        template_version=APPROVED_REPLY_TEMPLATE_VERSION,
        intent=RequestReplySendIntent(
            reply_text=reply_text,
            answer_category=category,
            claims=claims,
        ),
    )


def _records(records: Iterable[EvidenceRecord], fact_type: FactType) -> tuple[EvidenceRecord, ...]:
    return tuple(record for record in records if record.fact_type is fact_type)


def _selected_records(
    selection: TemplateSelectionIntent,
    task: TemplateSelectionTask,
) -> tuple[EvidenceRecord, ...]:
    by_id = {record.evidence_id: record for record in task.evidence_snapshot.records}
    if any(evidence_id not in by_id for evidence_id in selection.evidence_ids):
        raise TemplateRenderError("selected evidence is absent from the trusted snapshot")
    return tuple(by_id[evidence_id] for evidence_id in selection.evidence_ids)


def _only_selected_fact(
    selected_records: Sequence[EvidenceRecord],
    fact_type: FactType,
) -> EvidenceRecord:
    if len(selected_records) != 1 or selected_records[0].fact_type is not fact_type:
        raise TemplateRenderError(f"{fact_type.value} requires exactly one selected trusted record")
    return selected_records[0]


def _variant_record(records: Iterable[EvidenceRecord], variant_id: str) -> EvidenceRecord:
    matches = tuple(
        record
        for record in _records(records, FactType.VARIANT_AVAILABILITY)
        if record.source_ref.endswith(f"/{variant_id}")
        or record.evidence_id.endswith(f"_{variant_id}")
    )
    if len(matches) != 1:
        raise TemplateRenderError("selected variant is absent or ambiguous in trusted evidence")
    return matches[0]


def _render_identity(value: str, field: ListingIdentityField | None) -> str:
    if field is ListingIdentityField.SKU:
        match = re.search(r"(?:^|;\s*)SKU\s+([^;]+)", value)
        if match is None:
            raise TemplateRenderError("listing identity does not contain a trusted SKU")
        return f"SKU: {match.group(1).strip()}"
    if field is ListingIdentityField.TITLE:
        match = re.search(r"(?:^|;\s*)listing\s+(.+)$", value)
        if match is None:
            raise TemplateRenderError("listing identity does not contain a trusted title")
        return f"Title: {match.group(1).strip()}"
    if field is ListingIdentityField.COLORWAY:
        return f"Product identity: {value}"
    raise TemplateRenderError("listing identity field is missing")


def _natural_key(value: str) -> tuple[tuple[int, object], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", value)
        if part
    )
