"""Deterministic typed variant parsing and bound-listing candidate resolution."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import re
from typing import Optional, Sequence

from sidestage.domain.models import Variant


class SizeSystem(str, Enum):
    US = "US"
    UK = "UK"
    EU = "EU"


class Audience(str, Enum):
    MEN = "men"
    WOMEN = "women"
    YOUTH = "youth"


class VariantResolutionStatus(str, Enum):
    EXACT = "exact"
    AMBIGUOUS = "ambiguous"
    MISSING_EVIDENCE = "missing_evidence"
    SUMMARY = "summary"
    NOT_APPLICABLE = "not_applicable"


class AvailabilitySummaryKind(str, Enum):
    AVAILABLE_SIZES = "available_sizes"
    TOTAL_AVAILABLE = "total_available"


class TrustedVariantLabelError(ValueError):
    """A trusted catalog label cannot be represented by the closed schema."""


@dataclass(frozen=True)
class TrustedVariantCandidate:
    variant_id: str
    label: str
    size_system: SizeSystem
    audience: Audience
    size: Decimal


@dataclass(frozen=True)
class VariantResolution:
    status: VariantResolutionStatus
    candidate: Optional[TrustedVariantCandidate] = None
    summary_kind: Optional[AvailabilitySummaryKind] = None
    size_system: Optional[SizeSystem] = None
    audience: Optional[Audience] = None
    size: Optional[Decimal] = None

    @property
    def variant_id(self) -> Optional[str]:
        return None if self.candidate is None else self.candidate.variant_id


@dataclass(frozen=True)
class _BuyerAttributes:
    size_system: Optional[SizeSystem]
    audience: Optional[Audience]
    size: Optional[Decimal]
    conflicting: bool = False
    has_size_context: bool = False


_SYSTEM_PATTERNS = {
    SizeSystem.US: re.compile(r"(?<![a-z0-9])(?:us|u\.s\.)(?![a-z0-9])", re.IGNORECASE),
    SizeSystem.UK: re.compile(r"(?<![a-z0-9])(?:uk|u\.k\.)(?![a-z0-9])", re.IGNORECASE),
    SizeSystem.EU: re.compile(r"(?<![a-z0-9])(?:eu|e\.u\.)(?![a-z0-9])", re.IGNORECASE),
}
_AUDIENCE_PATTERNS = {
    Audience.MEN: re.compile(
        r"(?<![a-z0-9])(?:men's|man's|mens|male|men|man|m)(?![a-z0-9])",
        re.IGNORECASE,
    ),
    Audience.WOMEN: re.compile(
        r"(?<![a-z0-9])(?:women's|woman's|womens|female|women|woman|w)(?![a-z0-9])",
        re.IGNORECASE,
    ),
    Audience.YOUTH: re.compile(
        r"(?<![a-z0-9])(?:y|youth|kid|kids|kid's|child|children)(?![a-z0-9])",
        re.IGNORECASE,
    ),
}
_SIZE_NUMBER = re.compile(
    r"(?<![A-Za-z0-9.\-])(?P<size>[0-9]{1,3}(?:\.[0-9])?)(?![A-Za-z0-9.\-])"
)
_SIZE_WORD = re.compile(r"\bsizes?\b", re.IGNORECASE)
_TOTAL_SUMMARY = re.compile(
    r"\b(?:how\s+many|total)\b.*\b(?:pairs?|units?|items?)\b.*\b(?:all|every)\b.*\bsizes\b",
    re.IGNORECASE,
)
_AVAILABLE_SIZES_SUMMARY = re.compile(
    r"\b(?:what|which|any|available|stocked|have)\b.*\bsizes\b|\bsizes\b.*\b(?:available|in\s+stock|left|have)\b",
    re.IGNORECASE,
)


def parse_trusted_variant(variant: Variant) -> TrustedVariantCandidate:
    """Parse a trusted catalog label; reject labels outside the closed schema."""

    text = _normalize(variant.label)
    systems = _matches(text, _SYSTEM_PATTERNS)
    audiences = _matches(text, _AUDIENCE_PATTERNS)
    sizes = _sizes(text)
    if len(systems) != 1 or len(audiences) != 1 or len(sizes) != 1:
        raise TrustedVariantLabelError(
            f"trusted variant {variant.variant_id!r} must contain one system, audience, and size"
        )
    return TrustedVariantCandidate(
        variant_id=variant.variant_id,
        label=variant.label,
        size_system=systems[0],
        audience=audiences[0],
        size=sizes[0],
    )


def resolve_variant_question(
    question: str,
    variants: Sequence[Variant],
) -> VariantResolution:
    """Resolve buyer wording only against trusted variants of one bound listing."""

    attributes = _parse_buyer_attributes(question)
    if attributes.conflicting:
        return VariantResolution(
            status=VariantResolutionStatus.AMBIGUOUS,
            size_system=attributes.size_system,
            audience=attributes.audience,
            size=attributes.size,
        )

    if attributes.size is not None:
        candidates = tuple(parse_trusted_variant(variant) for variant in variants)
        matches = tuple(
            candidate
            for candidate in candidates
            if candidate.size == attributes.size
            and (
                attributes.size_system is None
                or candidate.size_system is attributes.size_system
            )
            and (
                attributes.audience is None
                or candidate.audience is attributes.audience
            )
        )
        if len(matches) == 1:
            return VariantResolution(
                status=VariantResolutionStatus.EXACT,
                candidate=matches[0],
                size_system=attributes.size_system,
                audience=attributes.audience,
                size=attributes.size,
            )
        return VariantResolution(
            status=(
                VariantResolutionStatus.MISSING_EVIDENCE
                if not matches
                else VariantResolutionStatus.AMBIGUOUS
            ),
            size_system=attributes.size_system,
            audience=attributes.audience,
            size=attributes.size,
        )

    summary_kind = _summary_kind(question)
    if summary_kind is not None:
        return VariantResolution(
            status=VariantResolutionStatus.SUMMARY,
            summary_kind=summary_kind,
        )

    if attributes.has_size_context and _SIZE_NUMBER.search(_normalize(question)):
        return VariantResolution(status=VariantResolutionStatus.MISSING_EVIDENCE)
    return VariantResolution(status=VariantResolutionStatus.NOT_APPLICABLE)


def _parse_buyer_attributes(question: str) -> _BuyerAttributes:
    text = _normalize(question)
    systems = _matches(text, _SYSTEM_PATTERNS)
    audiences = _matches(text, _AUDIENCE_PATTERNS)
    explicit_size_context = bool(_SIZE_WORD.search(text) or systems)
    sizes = _sizes(text) if explicit_size_context else _audience_linked_sizes(text)
    has_size_context = bool(explicit_size_context or sizes)
    conflicting = len(systems) > 1 or len(audiences) > 1 or len(sizes) > 1
    return _BuyerAttributes(
        size_system=systems[0] if len(systems) == 1 else None,
        audience=audiences[0] if len(audiences) == 1 else None,
        size=sizes[0] if len(sizes) == 1 else None,
        conflicting=conflicting,
        has_size_context=has_size_context,
    )


def _matches(text: str, patterns: dict[Enum, re.Pattern]) -> tuple:
    return tuple(value for value, pattern in patterns.items() if pattern.search(text))


def _sizes(text: str) -> tuple[Decimal, ...]:
    values = []
    for match in _SIZE_NUMBER.finditer(text):
        try:
            value = Decimal(match.group("size"))
        except InvalidOperation:
            continue
        if Decimal("1") <= value <= Decimal("60") and value not in values:
            values.append(value)
    return tuple(values)


def _audience_linked_sizes(text: str) -> tuple[Decimal, ...]:
    linked_values = []
    audience_matches = [
        match
        for pattern in _AUDIENCE_PATTERNS.values()
        for match in pattern.finditer(text)
    ]
    for number_match in _SIZE_NUMBER.finditer(text):
        for audience_match in audience_matches:
            if number_match.end() <= audience_match.start():
                between = text[number_match.end() : audience_match.start()]
            elif audience_match.end() <= number_match.start():
                between = text[audience_match.end() : number_match.start()]
            else:
                continue
            if re.fullmatch(r"\s*(?:for\s+)?", between, re.IGNORECASE) is None:
                continue
            try:
                value = Decimal(number_match.group("size"))
            except InvalidOperation:
                continue
            if value not in linked_values:
                linked_values.append(value)
            break
    return tuple(linked_values)


def _summary_kind(question: str) -> Optional[AvailabilitySummaryKind]:
    text = _normalize(question)
    if _TOTAL_SUMMARY.search(text):
        return AvailabilitySummaryKind.TOTAL_AVAILABLE
    if _AVAILABLE_SIZES_SUMMARY.search(text):
        return AvailabilitySummaryKind.AVAILABLE_SIZES
    return None


def _normalize(text: str) -> str:
    return text.replace("’", "'").replace("‘", "'").strip()
