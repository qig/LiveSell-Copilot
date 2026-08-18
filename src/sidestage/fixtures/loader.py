"""Strict import and tenant-scoped lookup for the M1 seller fixture."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Dict, Mapping, Tuple, TypeVar

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


def load_seller_fixture(path: Path = DEFAULT_SELLERS_FIXTURE) -> SellerCatalog:
    """Load the approved seller fixture without accepting runtime authority fields."""

    try:
        raw_json = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SellerFixtureError(f"seller fixture is unavailable: {path}") from error

    try:
        document = SellerFixtureDocument.model_validate_json(raw_json)
    except (ValidationError, ValueError) as error:
        count = error.error_count() if isinstance(error, ValidationError) else 1
        raise SellerFixtureError(
            f"seller fixture failed {count} contract validation error(s): {path}"
        ) from error

    actual_sellers = {
        seller.seller_id: (seller.display_name, seller.persona) for seller in document.sellers
    }
    if actual_sellers != EXPECTED_SELLERS:
        raise SellerFixtureError("seller fixture must contain the three approved seller personas")

    return SellerCatalog.from_document(document)
