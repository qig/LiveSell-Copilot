from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sidestage.domain.events import CustomerInputType
from sidestage.domain.models import Listing, Product, SellerProfile, Variant
from sidestage.domain.operations import OperationType, SELLER_OPERATION_TYPES


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SELLER_FIXTURE = REPOSITORY_ROOT / "fixtures" / "sellers.json"


@pytest.fixture(scope="module")
def raw_fixture() -> dict:
    return json.loads(SELLER_FIXTURE.read_text(encoding="utf-8"))


def test_operation_types_are_exactly_the_five_authenticated_seller_operations() -> None:
    expected = {
        "push",
        "swap",
        "unlist",
        "price_markdown",
        "inventory_change",
    }

    assert {operation.value for operation in OperationType} == expected
    assert {operation.value for operation in SELLER_OPERATION_TYPES} == expected
    assert "rollback" not in expected


def test_customer_input_surface_is_chat_only() -> None:
    assert [input_type.value for input_type in CustomerInputType] == ["chat_message"]


def test_imported_models_are_frozen_and_forbid_runtime_fields(raw_fixture: dict) -> None:
    seller = SellerProfile.model_validate(raw_fixture["sellers"][0])

    with pytest.raises(ValidationError):
        seller.display_name = "Changed"  # type: ignore[misc]

    for trusted_field in (
        "show_id",
        "accepted_at",
        "show_seq",
        "source_epoch_id",
        "trace_id",
        "actor_authority",
        "idempotency_key",
        "version",
    ):
        mutated = dict(raw_fixture["sellers"][0])
        mutated[trusted_field] = "untrusted_fixture_value"
        with pytest.raises(ValidationError):
            SellerProfile.model_validate(mutated)


def test_listing_rejects_price_below_floor(raw_fixture: dict) -> None:
    listing = dict(raw_fixture["sellers"][0]["products"][0]["listing"])
    listing["price_cents"] = listing["floor_price_cents"] - 1

    with pytest.raises(ValidationError, match="floor"):
        Listing.model_validate(listing, strict=True)


def test_variant_rejects_negative_inventory(raw_fixture: dict) -> None:
    variant = dict(raw_fixture["sellers"][0]["products"][0]["variants"][0])
    variant["available_quantity"] = -1

    with pytest.raises(ValidationError):
        Variant.model_validate(variant, strict=True)


def test_available_product_requires_positive_aggregate_stock(raw_fixture: dict) -> None:
    product = json.loads(json.dumps(raw_fixture["sellers"][0]["products"][0]))
    for variant in product["variants"]:
        variant["available_quantity"] = 0

    with pytest.raises(ValidationError, match="stock"):
        Product.model_validate(product)
