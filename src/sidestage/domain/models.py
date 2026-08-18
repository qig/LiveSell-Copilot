"""Immutable typed records for the directly authored seller fixture."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Tuple

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


SellerId = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^sel_[a-z0-9]+(?:_[a-z0-9]+)*$"),
]
ProductId = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^prd_[a-z0-9]+(?:_[a-z0-9]+)*$"),
]
ListingId = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^lst_[a-z0-9]+(?:_[a-z0-9]+)*$"),
]
VariantId = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^var_[a-z0-9]+(?:_[a-z0-9]+)*$"),
]
Sku = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+$"),
]
NonEmptyText = Annotated[str, StringConstraints(strict=True, min_length=1)]
CurrencyCode = Literal["USD"]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]

Persona = Literal["high_volume_new", "rare_consign", "rapid_rotation"]
ToneVoice = Literal["energetic_concise", "precise_reserved", "fast_direct"]
EmojiMode = Literal["none", "light"]
ListingCondition = Literal["new", "used", "consignment"]
ListingStatus = Literal["available", "unlisted"]


class FrozenModel(BaseModel):
    """Shared strict boundary for imported fixture records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ToneConfig(FrozenModel):
    voice: ToneVoice
    max_reply_chars: PositiveInt
    emoji_mode: EmojiMode
    prohibited_phrases: Annotated[Tuple[NonEmptyText, ...], Field(min_length=1)]

    @field_validator("prohibited_phrases")
    @classmethod
    def reject_duplicate_phrases(cls, phrases: Tuple[str, ...]) -> Tuple[str, ...]:
        if len({phrase.casefold() for phrase in phrases}) != len(phrases):
            raise ValueError("prohibited phrases must be unique")
        return phrases


class SellerPolicies(FrozenModel):
    shipping: NonEmptyText
    payment: NonEmptyText
    returns: NonEmptyText
    price_floor: NonEmptyText
    reply_rule: NonEmptyText


class ProductFacts(FrozenModel):
    release_date: date
    msrp_cents: PositiveInt
    materials: NonEmptyText
    sizing: NonEmptyText
    authenticity_status: NonEmptyText
    condition: NonEmptyText


class Listing(FrozenModel):
    listing_id: ListingId
    title: NonEmptyText
    condition: ListingCondition
    condition_notes: NonEmptyText
    price_cents: PositiveInt
    floor_price_cents: PositiveInt
    status: ListingStatus

    @model_validator(mode="after")
    def enforce_price_floor(self) -> "Listing":
        if self.price_cents < self.floor_price_cents:
            raise ValueError("listing price cannot be below the seller floor")
        return self


class Variant(FrozenModel):
    variant_id: VariantId
    label: NonEmptyText
    available_quantity: NonNegativeInt


class Product(FrozenModel):
    product_id: ProductId
    sku: Sku
    brand: NonEmptyText
    model_name: NonEmptyText
    colorway: NonEmptyText
    listing: Listing
    variants: Annotated[Tuple[Variant, ...], Field(min_length=1)]
    facts: ProductFacts

    @model_validator(mode="after")
    def validate_variants_and_stock(self) -> "Product":
        variant_ids = [variant.variant_id for variant in self.variants]
        if len(set(variant_ids)) != len(variant_ids):
            raise ValueError("variant IDs must be unique within a product")

        labels = [variant.label.casefold() for variant in self.variants]
        if len(set(labels)) != len(labels):
            raise ValueError("variant labels must be unique within a product")

        if self.listing.status == "available" and sum(
            variant.available_quantity for variant in self.variants
        ) <= 0:
            raise ValueError("an available listing must have positive aggregate stock")
        return self


class SellerProfile(FrozenModel):
    seller_id: SellerId
    display_name: NonEmptyText
    persona: Persona
    currency: CurrencyCode
    tone: ToneConfig
    policies: SellerPolicies
    products: Annotated[Tuple[Product, ...], Field(min_length=3)]

    @model_validator(mode="after")
    def validate_seller_catalog(self) -> "SellerProfile":
        product_ids = [product.product_id for product in self.products]
        listing_ids = [product.listing.listing_id for product in self.products]
        skus = [product.sku.casefold() for product in self.products]
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("product IDs must be unique within a seller")
        if len(set(listing_ids)) != len(listing_ids):
            raise ValueError("listing IDs must be unique within a seller")
        if len(set(skus)) != len(skus):
            raise ValueError("SKUs must be unique case-insensitively within a seller")
        return self


class SellerFixtureDocument(FrozenModel):
    schema_version: Literal["1.0"]
    synthetic: Literal[True]
    sellers: Annotated[Tuple[SellerProfile, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_global_identity(self) -> "SellerFixtureDocument":
        seller_ids = [seller.seller_id for seller in self.sellers]
        product_ids = [product.product_id for seller in self.sellers for product in seller.products]
        listing_ids = [
            product.listing.listing_id for seller in self.sellers for product in seller.products
        ]
        variant_ids = [
            variant.variant_id
            for seller in self.sellers
            for product in seller.products
            for variant in product.variants
        ]
        skus = [product.sku.casefold() for seller in self.sellers for product in seller.products]

        for label, values in (
            ("seller IDs", seller_ids),
            ("product IDs", product_ids),
            ("listing IDs", listing_ids),
            ("variant IDs", variant_ids),
            ("SKUs", skus),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must be globally unique")
        return self
