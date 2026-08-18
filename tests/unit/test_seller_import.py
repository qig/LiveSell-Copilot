from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Callable

import pytest

from sidestage.config import DEFAULT_SELLERS_FIXTURE
from sidestage.fixtures.loader import (
    SellerFixtureError,
    TenantScopeError,
    load_seller_fixture,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SELLER_FIXTURE = REPOSITORY_ROOT / "fixtures" / "sellers.json"
EXPECTED_SELLERS = {
    "sel_velocity_kicks": ("VelocityKicks", "high_volume_new"),
    "sel_vault_consign": ("VaultConsign", "rare_consign"),
    "sel_rotation_kicks": ("RotationKicks", "rapid_rotation"),
}


@pytest.fixture(scope="module")
def raw_fixture() -> dict:
    return json.loads(SELLER_FIXTURE.read_text(encoding="utf-8"))


def write_fixture(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "sellers.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_default_fixture_path_targets_the_repository_fixture() -> None:
    assert DEFAULT_SELLERS_FIXTURE == SELLER_FIXTURE


def test_imports_exact_approved_sellers_without_changing_source_values(raw_fixture: dict) -> None:
    catalog = load_seller_fixture()

    assert {
        seller.seller_id: (seller.display_name, seller.persona)
        for seller in catalog.document.sellers
    } == EXPECTED_SELLERS
    assert catalog.document.model_dump(mode="json") == raw_fixture
    assert catalog.counts.sellers == 3
    assert catalog.counts.products == 10
    assert catalog.counts.listings == 10
    assert catalog.counts.variants == 18
    assert catalog.counts.available_units == 21


def test_import_builds_tenant_scoped_entity_lookups() -> None:
    catalog = load_seller_fixture()

    product = catalog.product_for("sel_velocity_kicks", "prd_velocity_aero_dash")
    listing = catalog.listing_for("sel_velocity_kicks", "lst_velocity_aero_dash")
    variant = catalog.variant_for("sel_velocity_kicks", "var_velocity_aero_dash_9")

    assert product.sku == "VK-AD-RC-001"
    assert listing.price_cents == 16000
    assert variant.available_quantity == 2

    with pytest.raises(TenantScopeError):
        catalog.listing_for("sel_vault_consign", "lst_velocity_aero_dash")
    with pytest.raises(TenantScopeError):
        catalog.variant_for("sel_rotation_kicks", "var_velocity_aero_dash_9")


def _invalid_seller_id(payload: dict) -> None:
    payload["sellers"][0]["seller_id"] = "seller_invalid"


def _invalid_product_id(payload: dict) -> None:
    payload["sellers"][0]["products"][0]["product_id"] = "product_invalid"


def _invalid_listing_id(payload: dict) -> None:
    payload["sellers"][0]["products"][0]["listing"]["listing_id"] = "listing_invalid"


def _invalid_variant_id(payload: dict) -> None:
    payload["sellers"][0]["products"][0]["variants"][0]["variant_id"] = "variant_invalid"


def _invalid_sku(payload: dict) -> None:
    payload["sellers"][0]["products"][0]["sku"] = "invalid sku"


def _duplicate_seller_id(payload: dict) -> None:
    payload["sellers"][1]["seller_id"] = payload["sellers"][0]["seller_id"]


def _duplicate_product_id_across_sellers(payload: dict) -> None:
    payload["sellers"][1]["products"][0]["product_id"] = payload["sellers"][0]["products"][0]["product_id"]


def _duplicate_listing_id_across_sellers(payload: dict) -> None:
    payload["sellers"][1]["products"][0]["listing"]["listing_id"] = payload["sellers"][0]["products"][0]["listing"]["listing_id"]


def _duplicate_variant_id_across_sellers(payload: dict) -> None:
    payload["sellers"][1]["products"][0]["variants"][0]["variant_id"] = payload["sellers"][0]["products"][0]["variants"][0]["variant_id"]


def _duplicate_sku_case_insensitively(payload: dict) -> None:
    payload["sellers"][1]["products"][0]["sku"] = payload["sellers"][0]["products"][0]["sku"].lower()


def _negative_stock(payload: dict) -> None:
    payload["sellers"][0]["products"][0]["variants"][0]["available_quantity"] = -1


def _price_below_floor(payload: dict) -> None:
    listing = payload["sellers"][0]["products"][0]["listing"]
    listing["price_cents"] = listing["floor_price_cents"] - 1


def _available_listing_without_stock(payload: dict) -> None:
    for variant in payload["sellers"][0]["products"][0]["variants"]:
        variant["available_quantity"] = 0


def _missing_policy(payload: dict) -> None:
    del payload["sellers"][0]["policies"]["shipping"]


def _missing_product_fact(payload: dict) -> None:
    del payload["sellers"][0]["products"][0]["facts"]["materials"]


def _unexpected_runtime_field(payload: dict) -> None:
    payload["sellers"][0]["show_id"] = "show_injected"


def _wrong_approved_seller_mapping(payload: dict) -> None:
    payload["sellers"][0]["display_name"] = "ImposterSeller"


def _wrong_schema_version(payload: dict) -> None:
    payload["schema_version"] = "2.0"


def _not_synthetic(payload: dict) -> None:
    payload["synthetic"] = False


def _too_few_products(payload: dict) -> None:
    payload["sellers"][0]["products"] = payload["sellers"][0]["products"][:2]


def _unsupported_currency(payload: dict) -> None:
    payload["sellers"][0]["currency"] = "EUR"


def _string_stock(payload: dict) -> None:
    payload["sellers"][0]["products"][0]["variants"][0]["available_quantity"] = "1"


@pytest.mark.parametrize(
    "mutation",
    [
        _invalid_seller_id,
        _invalid_product_id,
        _invalid_listing_id,
        _invalid_variant_id,
        _invalid_sku,
        _duplicate_seller_id,
        _duplicate_product_id_across_sellers,
        _duplicate_listing_id_across_sellers,
        _duplicate_variant_id_across_sellers,
        _duplicate_sku_case_insensitively,
        _negative_stock,
        _price_below_floor,
        _available_listing_without_stock,
        _missing_policy,
        _missing_product_fact,
        _unexpected_runtime_field,
        _wrong_approved_seller_mapping,
        _wrong_schema_version,
        _not_synthetic,
        _too_few_products,
        _unsupported_currency,
        _string_stock,
    ],
    ids=lambda mutation: mutation.__name__.removeprefix("_"),
)
def test_rejects_invalid_or_cross_tenant_fixture_mutations(
    tmp_path: Path,
    raw_fixture: dict,
    mutation: Callable[[dict], None],
) -> None:
    payload = copy.deepcopy(raw_fixture)
    mutation(payload)

    with pytest.raises(SellerFixtureError):
        load_seller_fixture(write_fixture(tmp_path, payload))


def test_rejects_unknown_document_fields(tmp_path: Path, raw_fixture: dict) -> None:
    payload = copy.deepcopy(raw_fixture)
    payload["runtime"] = {"show_id": "show_injected"}

    with pytest.raises(SellerFixtureError):
        load_seller_fixture(write_fixture(tmp_path, payload))


def test_rejects_missing_or_non_json_fixture(tmp_path: Path) -> None:
    with pytest.raises(SellerFixtureError):
        load_seller_fixture(tmp_path / "missing.json")

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not-json", encoding="utf-8")
    with pytest.raises(SellerFixtureError):
        load_seller_fixture(malformed)
