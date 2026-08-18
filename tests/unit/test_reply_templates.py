from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sidestage.copilot.contracts import (
    BoundListing,
    EvidenceRecord,
    EvidenceSnapshot,
    EvidenceSource,
    ReplyTone,
    TemplateSelectionTask,
)
from sidestage.copilot.templates import (
    APPROVED_REPLY_TEMPLATE_VERSION,
    TemplateRenderError,
    render_approved_template,
)
from sidestage.domain.replies import (
    AnswerCategory,
    BindingBasis,
    BindingStatus,
    FactType,
    ListingIdentityField,
    ReplyTemplateId,
    TemplateSelectionIntent,
)


NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def _record(fact_type: FactType, value: str, *, suffix: str | None = None) -> EvidenceRecord:
    resolved_suffix = suffix or fact_type.value
    source = (
        EvidenceSource.MARKETPLACE_STATE
        if fact_type in {FactType.CURRENT_PRICE, FactType.VARIANT_AVAILABILITY}
        else EvidenceSource.SELLER_POLICY
        if fact_type in {
            FactType.SHIPPING_POLICY,
            FactType.PAYMENT_POLICY,
            FactType.RETURNS_POLICY,
        }
        else EvidenceSource.PRODUCT_CATALOG
        if fact_type is FactType.LISTING_IDENTITY
        else EvidenceSource.PRODUCT_RESEARCH
    )
    return EvidenceRecord(
        evidence_id=f"evd_{resolved_suffix}",
        seller_id="sel_velocity_kicks",
        listing_id="lst_velocity_aero_dash",
        fact_type=fact_type,
        value=value,
        source=source,
        source_ref=f"trusted:{resolved_suffix}",
        source_version=1,
        observed_at=NOW,
        provenance="synthetic_seller_data",
    )


def _task(*records: EvidenceRecord) -> TemplateSelectionTask:
    return TemplateSelectionTask(
        question_id="qst_template_1",
        trace_id="trc_template_1",
        seller_id="sel_velocity_kicks",
        show_id="show_velocity_kicks",
        asked_at=NOW,
        deadline_monotonic_s=105.0,
        question="What is the current price?",
        bound_listing=BoundListing(
            listing_id="lst_velocity_aero_dash",
            sku="VK-AD-RC-001",
            epoch_id="epc_velocity_1",
            binding_basis=BindingBasis.SOURCE_EPOCH,
            binding_status=BindingStatus.CERTAIN,
        ),
        evidence_snapshot=EvidenceSnapshot(
            snapshot_id="snp_template_1",
            seller_id="sel_velocity_kicks",
            show_id="show_velocity_kicks",
            listing_id="lst_velocity_aero_dash",
            epoch_id="epc_velocity_1",
            created_at=NOW,
            records=records,
        ),
        tone=ReplyTone(
            voice="energetic_concise",
            max_reply_chars=300,
            emoji_mode="light",
            prohibited_phrases=("cheapest anywhere",),
        ),
    )


@pytest.mark.parametrize(
    ("template_id", "fact_type", "value", "category"),
    [
        (ReplyTemplateId.CURRENT_PRICE, FactType.CURRENT_PRICE, "USD 160.00", AnswerCategory.PRICE),
        (ReplyTemplateId.SHIPPING_POLICY, FactType.SHIPPING_POLICY, "Ships in two business days.", AnswerCategory.SHIPPING),
        (ReplyTemplateId.PAYMENT_POLICY, FactType.PAYMENT_POLICY, "Payment is captured at checkout.", AnswerCategory.PAYMENT),
        (ReplyTemplateId.RETURNS_POLICY, FactType.RETURNS_POLICY, "Returns accepted within 14 days.", AnswerCategory.RETURNS),
        (ReplyTemplateId.RELEASE_DATE, FactType.RELEASE_DATE, "2024-02-15", AnswerCategory.PRODUCT_RESEARCH),
        (ReplyTemplateId.MSRP, FactType.MSRP, "USD 180.00", AnswerCategory.PRODUCT_RESEARCH),
        (ReplyTemplateId.MATERIALS, FactType.MATERIALS, "Mesh and synthetic suede", AnswerCategory.PRODUCT_RESEARCH),
        (ReplyTemplateId.SIZING_GUIDANCE, FactType.SIZING, "Fits true to size", AnswerCategory.SIZING),
        (ReplyTemplateId.AUTHENTICITY, FactType.AUTHENTICITY, "Authenticated by seller", AnswerCategory.AUTHENTICITY),
        (ReplyTemplateId.CONDITION, FactType.CONDITION, "New with original box", AnswerCategory.CONDITION),
    ],
)
def test_single_fact_templates_render_only_trusted_evidence(
    template_id: ReplyTemplateId,
    fact_type: FactType,
    value: str,
    category: AnswerCategory,
) -> None:
    rendered = render_approved_template(
        TemplateSelectionIntent(
            template_id=template_id,
            evidence_ids=(f"evd_{fact_type.value}",),
        ),
        _task(_record(FactType.LISTING_IDENTITY, "Aero Dash; SKU VK-AD-RC-001"), _record(fact_type, value)),
    )

    assert rendered.template_id is template_id
    assert rendered.template_version == APPROVED_REPLY_TEMPLATE_VERSION
    assert rendered.intent.answer_category is category
    assert value in rendered.intent.reply_text
    assert rendered.intent.claims[0].evidence_ids == (f"evd_{fact_type.value}",)


def test_exact_variant_and_availability_summary_use_only_selected_snapshot_records() -> None:
    size_9 = _record(FactType.VARIANT_AVAILABILITY, "US M 9: 2 available", suffix="stock_var_9")
    size_10 = _record(FactType.VARIANT_AVAILABILITY, "US M 10: 0 available", suffix="stock_var_10")
    task = _task(_record(FactType.LISTING_IDENTITY, "Aero Dash"), size_9, size_10)

    exact = render_approved_template(
        TemplateSelectionIntent(
            template_id=ReplyTemplateId.EXACT_VARIANT_AVAILABILITY,
            evidence_ids=("evd_stock_var_9",),
            variant_id="var_9",
        ),
        task,
    )
    summary = render_approved_template(
        TemplateSelectionIntent(
            template_id=ReplyTemplateId.AVAILABILITY_SUMMARY,
            evidence_ids=("evd_stock_var_9", "evd_stock_var_10"),
        ),
        task,
    )

    assert exact.intent.reply_text == "Availability: US M 9: 2 available"
    assert exact.intent.claims[0].evidence_ids == ("evd_stock_var_9",)
    assert "US M 9: 2 available" in summary.intent.reply_text
    assert "US M 10: 0 available" in summary.intent.reply_text
    assert tuple(claim.evidence_ids[0] for claim in summary.intent.claims) == (
        "evd_stock_var_9",
        "evd_stock_var_10",
    )


def test_listing_identity_records_the_requested_field_without_inventing_a_value() -> None:
    identity = _record(
        FactType.LISTING_IDENTITY,
        "Velocity Aero Dash Royal Current; SKU VK-AD-RC-001; listing Aero Dash Royal Current",
    )

    rendered = render_approved_template(
        TemplateSelectionIntent(
            template_id=ReplyTemplateId.LISTING_IDENTITY,
            evidence_ids=("evd_listing_identity",),
            identity_field=ListingIdentityField.SKU,
        ),
        _task(identity),
    )

    assert rendered.intent.reply_text == "SKU: VK-AD-RC-001"
    assert rendered.intent.claims[0].evidence_ids == ("evd_listing_identity",)


def test_template_selection_rejects_irrelevant_arguments_and_fabricated_variant() -> None:
    with pytest.raises(ValueError, match="variant_id"):
        TemplateSelectionIntent(
            template_id=ReplyTemplateId.CURRENT_PRICE,
            evidence_ids=("evd_current_price",),
            variant_id="var_9",
        )

    with pytest.raises(TemplateRenderError, match="variant"):
        render_approved_template(
            TemplateSelectionIntent(
                template_id=ReplyTemplateId.EXACT_VARIANT_AVAILABILITY,
                evidence_ids=("evd_stock_var_9",),
                variant_id="var_fabricated",
            ),
            _task(_record(FactType.VARIANT_AVAILABILITY, "US M 9: 2 available", suffix="stock_var_9")),
        )


def test_renderer_fails_closed_for_duplicate_fact_or_prohibited_output() -> None:
    with pytest.raises(TemplateRenderError, match="exactly one"):
        render_approved_template(
            TemplateSelectionIntent(
                template_id=ReplyTemplateId.CURRENT_PRICE,
                evidence_ids=("evd_price_1", "evd_price_2"),
            ),
            _task(
                _record(FactType.CURRENT_PRICE, "USD 160.00", suffix="price_1"),
                _record(FactType.CURRENT_PRICE, "USD 150.00", suffix="price_2"),
            ),
        )

    prohibited = _task(_record(FactType.CONDITION, "Cheapest anywhere"))
    with pytest.raises(TemplateRenderError, match="tone"):
        render_approved_template(
            TemplateSelectionIntent(
                template_id=ReplyTemplateId.CONDITION,
                evidence_ids=("evd_condition",),
            ),
            prohibited,
        )

    oversized = _task(_record(FactType.MATERIALS, "x" * 400))
    with pytest.raises(TemplateRenderError, match="length"):
        render_approved_template(
            TemplateSelectionIntent(
                template_id=ReplyTemplateId.MATERIALS,
                evidence_ids=("evd_materials",),
            ),
            oversized,
        )
