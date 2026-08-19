from __future__ import annotations

from decimal import Decimal

import pytest

from sidestage.copilot.variants import (
    AvailabilitySummaryKind,
    Audience,
    SizeSystem,
    VariantResolutionStatus,
    parse_trusted_variant,
    resolve_variant_question,
)
from sidestage.domain.models import Variant


def _variant(variant_id: str, label: str) -> Variant:
    return Variant(variant_id=variant_id, label=label, available_quantity=1)


MEN_9 = _variant("var_us_m_9", "US M 9")


@pytest.mark.parametrize(
    "wording",
    (
        "US M 9",
        "9 M US",
        "Men's US 9",
        "9 for men",
        "9 for man",
    ),
)
def test_equivalent_size_wording_resolves_one_trusted_variant(wording: str) -> None:
    result = resolve_variant_question(
        wording,
        (
            _variant("var_us_m_8", "US M 8"),
            MEN_9,
            _variant("var_us_m_10", "US M 10"),
        ),
    )

    assert result.status is VariantResolutionStatus.EXACT
    assert result.variant_id == MEN_9.variant_id
    assert result.candidate is not None
    assert result.candidate.label == "US M 9"


def test_trusted_catalog_label_is_parsed_into_typed_attributes() -> None:
    candidate = parse_trusted_variant(_variant("var_eu_w_42_5", "EU W 42.5"))

    assert candidate.size_system is SizeSystem.EU
    assert candidate.audience is Audience.WOMEN
    assert candidate.size == Decimal("42.5")


def test_decimal_size_does_not_match_integer_size() -> None:
    variants = (
        MEN_9,
        _variant("var_us_m_9_5", "US M 9.5"),
    )

    integer = resolve_variant_question("Do you have men's size 9?", variants)
    decimal = resolve_variant_question("Do you have men's size 9.5?", variants)

    assert integer.status is VariantResolutionStatus.EXACT
    assert integer.variant_id == "var_us_m_9"
    assert decimal.status is VariantResolutionStatus.EXACT
    assert decimal.variant_id == "var_us_m_9_5"


def test_missing_system_and_audience_are_inferred_only_from_unique_candidates() -> None:
    result = resolve_variant_question(
        "Do you have size 9?",
        (
            _variant("var_us_m_8", "US M 8"),
            MEN_9,
            _variant("var_us_m_10", "US M 10"),
        ),
    )

    assert result.status is VariantResolutionStatus.EXACT
    assert result.variant_id == "var_us_m_9"


@pytest.mark.parametrize(
    ("wording", "variants"),
    (
        (
            "size 9",
            (
                _variant("var_us_m_9", "US M 9"),
                _variant("var_us_w_9", "US W 9"),
            ),
        ),
        (
            "men's 9",
            (
                _variant("var_us_m_9", "US M 9"),
                _variant("var_uk_m_9", "UK M 9"),
            ),
        ),
    ),
)
def test_missing_attributes_are_ambiguous_when_trusted_candidates_disagree(
    wording: str,
    variants: tuple[Variant, ...],
) -> None:
    result = resolve_variant_question(wording, variants)

    assert result.status is VariantResolutionStatus.AMBIGUOUS
    assert result.variant_id is None
    assert result.candidate is None


def test_exact_absent_decimal_size_is_a_typed_negative_fact() -> None:
    result = resolve_variant_question(
        "Is US M 6.5 available?",
        (
            _variant("var_us_m_8", "US M 8"),
            MEN_9,
            _variant("var_us_m_10", "US M 10"),
        ),
    )

    assert result.status is VariantResolutionStatus.ABSENT
    assert result.size_system is SizeSystem.US
    assert result.audience is Audience.MEN
    assert result.size == Decimal("6.5")
    assert result.variant_id is None


def test_absent_size_infers_attributes_only_when_the_catalog_agrees() -> None:
    inferred = resolve_variant_question(
        "Is size 6.5 available?",
        (
            _variant("var_us_m_8", "US M 8"),
            MEN_9,
        ),
    )
    mixed = resolve_variant_question(
        "Is size 6.5 available?",
        (
            _variant("var_us_m_8", "US M 8"),
            _variant("var_us_w_8", "US W 8"),
        ),
    )

    assert inferred.status is VariantResolutionStatus.ABSENT
    assert inferred.size_system is SizeSystem.US
    assert inferred.audience is Audience.MEN
    assert mixed.status is VariantResolutionStatus.AMBIGUOUS


@pytest.mark.parametrize("size", ("0", "99", "100"))
def test_unknown_size_fails_closed_as_missing_evidence(size: str) -> None:
    result = resolve_variant_question(f"Do you have US men's size {size}?", (MEN_9,))

    assert result.status is VariantResolutionStatus.MISSING_EVIDENCE
    assert result.variant_id is None


def test_unknown_audience_linked_size_fails_closed_as_missing_evidence() -> None:
    result = resolve_variant_question("Do you have men's 99?", (MEN_9,))

    assert result.status is VariantResolutionStatus.MISSING_EVIDENCE


@pytest.mark.parametrize(
    "wording",
    (
        "Is the Aero Dash 9 available?",
        "Do you stock the Air Max 90?",
        "Is the men's Air Jordan 1 available?",
        "What is model 550?",
        "Is SKU VK-AD-RC-001 current?",
    ),
)
def test_product_and_model_numbers_are_not_parsed_as_shoe_sizes(wording: str) -> None:
    result = resolve_variant_question(wording, (MEN_9,))

    assert result.status is VariantResolutionStatus.NOT_APPLICABLE
    assert result.variant_id is None


@pytest.mark.parametrize(
    ("wording", "summary_kind"),
    (
        ("What sizes are available?", AvailabilitySummaryKind.AVAILABLE_SIZES),
        (
            "How many pairs are left across all sizes?",
            AvailabilitySummaryKind.TOTAL_AVAILABLE,
        ),
    ),
)
def test_general_availability_has_a_typed_deterministic_summary_plan(
    wording: str,
    summary_kind: AvailabilitySummaryKind,
) -> None:
    result = resolve_variant_question(wording, (MEN_9,))

    assert result.status is VariantResolutionStatus.SUMMARY
    assert result.summary_kind is summary_kind
    assert result.variant_id is None
