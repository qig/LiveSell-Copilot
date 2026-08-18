"""Strict import and tenant-scoped lookup for the M1 seller fixture."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Dict, Mapping, Optional, Tuple, TypeVar

from pydantic import ValidationError

from sidestage.config import DEFAULT_SELLERS_FIXTURE
from sidestage.domain.models import Listing, Product, SellerFixtureDocument, SellerProfile, Variant


EXPECTED_SELLERS = {
    "sel_velocity_kicks": ("VelocityKicks", "high_volume_new"),
    "sel_vault_consign": ("VaultConsign", "rare_consign"),
    "sel_rotation_kicks": ("RotationKicks", "rapid_rotation"),
}


class SellerFixtureError(ValueError):
    """The seller fixture cannot be imported into the approved contract."""


class TenantScopeError(LookupError):
    """An entity exists but is not owned by the requested seller."""


@dataclass(frozen=True)
class CatalogCounts:
    sellers: int
    products: int
    listings: int
    variants: int
    available_units: int


Entity = TypeVar("Entity")
OwnedEntity = Tuple[str, Entity]
ImportObserver = Callable[[str, str, Mapping[str, object]], None]


@dataclass(frozen=True)
class SellerCatalog:
    """Immutable imported records plus server-owned tenant indexes."""

    document: SellerFixtureDocument
    _sellers: Mapping[str, SellerProfile]
    _products: Mapping[str, OwnedEntity[Product]]
    _listings: Mapping[str, OwnedEntity[Listing]]
    _variants: Mapping[str, OwnedEntity[Variant]]

    @classmethod
    def from_document(cls, document: SellerFixtureDocument) -> "SellerCatalog":
        sellers: Dict[str, SellerProfile] = {}
        products: Dict[str, OwnedEntity[Product]] = {}
        listings: Dict[str, OwnedEntity[Listing]] = {}
        variants: Dict[str, OwnedEntity[Variant]] = {}

        for seller in document.sellers:
            sellers[seller.seller_id] = seller
            for product in seller.products:
                products[product.product_id] = (seller.seller_id, product)
                listings[product.listing.listing_id] = (seller.seller_id, product.listing)
                for variant in product.variants:
                    variants[variant.variant_id] = (seller.seller_id, variant)

        return cls(
            document=document,
            _sellers=MappingProxyType(sellers),
            _products=MappingProxyType(products),
            _listings=MappingProxyType(listings),
            _variants=MappingProxyType(variants),
        )

    @property
    def counts(self) -> CatalogCounts:
        return CatalogCounts(
            sellers=len(self._sellers),
            products=len(self._products),
            listings=len(self._listings),
            variants=len(self._variants),
            available_units=sum(
                variant.available_quantity for _, variant in self._variants.values()
            ),
        )

    def seller(self, seller_id: str) -> SellerProfile:
        try:
            return self._sellers[seller_id]
        except KeyError as error:
            raise KeyError(f"unknown seller: {seller_id}") from error

    def product_for(self, seller_id: str, product_id: str) -> Product:
        return _tenant_entity(self._products, seller_id, product_id, "product")

    def listing_for(self, seller_id: str, listing_id: str) -> Listing:
        return _tenant_entity(self._listings, seller_id, listing_id, "listing")

    def variant_for(self, seller_id: str, variant_id: str) -> Variant:
        return _tenant_entity(self._variants, seller_id, variant_id, "variant")


def _tenant_entity(
    index: Mapping[str, OwnedEntity[Entity]],
    seller_id: str,
    entity_id: str,
    entity_name: str,
) -> Entity:
    try:
        owner_id, entity = index[entity_id]
    except KeyError as error:
        raise KeyError(f"unknown {entity_name}: {entity_id}") from error
    if owner_id != seller_id:
        raise TenantScopeError(f"{entity_name} is not owned by seller {seller_id}")
    return entity


def _observe(
    observer: Optional[ImportObserver],
    stage: str,
    state: str,
    details: Optional[Mapping[str, object]] = None,
) -> None:
    """Emit diagnostic metadata without granting the sink import authority."""

    if observer is None:
        return
    try:
        observer(stage, state, details or {})
    except Exception:
        # Diagnostics must never alter the authoritative import result.
        return


def load_seller_fixture(
    path: Path = DEFAULT_SELLERS_FIXTURE,
    *,
    observer: Optional[ImportObserver] = None,
) -> SellerCatalog:
    """Load the approved seller fixture without accepting runtime authority fields."""

    _observe(observer, "source_read", "started")
    try:
        raw_json = path.read_text(encoding="utf-8")
    except OSError as error:
        _observe(
            observer,
            "source_read",
            "failed",
            {"reason_code": "FIXTURE_UNAVAILABLE"},
        )
        raise SellerFixtureError(f"seller fixture is unavailable: {path}") from error
    _observe(
        observer,
        "source_read",
        "passed",
        {
            "byte_count": len(raw_json.encode("utf-8")),
            "sha256": hashlib.sha256(raw_json.encode("utf-8")).hexdigest(),
        },
    )

    _observe(observer, "contract_validation", "started")
    try:
        document = SellerFixtureDocument.model_validate_json(raw_json)
    except (ValidationError, ValueError) as error:
        count = error.error_count() if isinstance(error, ValidationError) else 1
        _observe(
            observer,
            "contract_validation",
            "failed",
            {
                "reason_code": "FIXTURE_CONTRACT_INVALID",
                "validation_error_count": count,
            },
        )
        raise SellerFixtureError(
            f"seller fixture failed {count} contract validation error(s): {path}"
        ) from error
    _observe(
        observer,
        "contract_validation",
        "passed",
        {"seller_count": len(document.sellers)},
    )

    _observe(observer, "approved_seller_set", "started")
    actual_sellers = {
        seller.seller_id: (seller.display_name, seller.persona) for seller in document.sellers
    }
    if actual_sellers != EXPECTED_SELLERS:
        _observe(
            observer,
            "approved_seller_set",
            "failed",
            {"reason_code": "SELLER_SET_NOT_APPROVED"},
        )
        raise SellerFixtureError("seller fixture must contain the three approved seller personas")
    _observe(
        observer,
        "approved_seller_set",
        "passed",
        {"seller_ids": list(actual_sellers)},
    )

    _observe(observer, "tenant_index_build", "started")
    try:
        catalog = SellerCatalog.from_document(document)
    except Exception:
        _observe(
            observer,
            "tenant_index_build",
            "failed",
            {"reason_code": "TENANT_INDEX_BUILD_FAILED"},
        )
        raise
    _observe(
        observer,
        "tenant_index_build",
        "passed",
        {
            "products": catalog.counts.products,
            "listings": catalog.counts.listings,
            "variants": catalog.counts.variants,
        },
    )
    return catalog
