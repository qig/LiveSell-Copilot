"""Tenant-first evidence retrieval and immutable snapshot assembly."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import re
from typing import Annotated, Callable, Optional, Sequence, Tuple, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from sidestage.copilot.contracts import (
    AnalysisIntent,
    BoundListing,
    EvidenceRecord,
    EvidenceRequest,
    EvidenceSnapshot,
    EvidenceSource,
)
from sidestage.domain.replies import FactType
from sidestage.fixtures.loader import SellerCatalog
from sidestage.storage.database import MarketplaceDatabase
from sidestage.storage.repositories import _evidence_id
from sidestage.copilot.routing import explicit_product_matches


class RetrievalStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RetrievalFailureCode(str, Enum):
    MISSING_EVIDENCE = "missing_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    STALE_EVIDENCE = "stale_evidence"
    WRONG_SKU = "wrong_sku"
    UNSUPPORTED_ANALYSIS = "unsupported_analysis"


class RetrievalContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if value.utcoffset().total_seconds() != 0:
        raise ValueError(f"{field_name} must use UTC")
    return value


class RetrievalContext(RetrievalContract):
    question_id: str
    trace_id: str
    analysis_id: str
    seller_id: str
    show_id: str
    bound_listing: BoundListing
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="observed_at")


class TemplateRetrievalContext(RetrievalContract):
    """Trusted scope for Workflow 1's deterministic pre-call evidence bundle."""

    question_id: str
    trace_id: str
    seller_id: str
    show_id: str
    bound_listing: BoundListing
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="observed_at")


class RetrievalFailure(RetrievalContract):
    code: RetrievalFailureCode
    message: Annotated[str, StringConstraints(strict=True, min_length=1)]


class RetrievalResult(RetrievalContract):
    status: RetrievalStatus
    snapshot: Optional[EvidenceSnapshot] = None
    failure: Optional[RetrievalFailure] = None

    @model_validator(mode="after")
    def exactly_one_outcome(self) -> "RetrievalResult":
        if int(self.snapshot is not None) + int(self.failure is not None) != 1:
            raise ValueError("retrieval result requires exactly one snapshot or failure")
        if self.status is RetrievalStatus.SUCCEEDED and self.snapshot is None:
            raise ValueError("successful retrieval requires a snapshot")
        if self.status is RetrievalStatus.FAILED and self.failure is None:
            raise ValueError("failed retrieval requires a failure")
        return self


_RESEARCH_FACTS = frozenset(
    {
        FactType.RELEASE_DATE,
        FactType.MSRP,
        FactType.MATERIALS,
        FactType.SIZING,
        FactType.AUTHENTICITY,
        FactType.CONDITION,
    }
)
_POLICY_FACTS = frozenset(
    {FactType.SHIPPING_POLICY, FactType.PAYMENT_POLICY, FactType.RETURNS_POLICY}
)
_SKU_PATTERN = re.compile(r"\b[A-Za-z0-9]{2,}(?:-[A-Za-z0-9]{2,}){2,}\b")


class EvidenceRetriever:
    def __init__(
        self,
        database: MarketplaceDatabase,
        catalog: SellerCatalog,
        *,
        id_factory: Callable[[], str] = lambda: f"snp_{uuid4().hex}",
    ) -> None:
        self.database = database
        self.catalog = catalog
        self.id_factory = id_factory

    def retrieve(
        self,
        context: RetrievalContext,
        request: EvidenceRequest,
    ) -> RetrievalResult:
        if request.intent is not AnalysisIntent.ANSWERABLE:
            return self._failure(
                RetrievalFailureCode.UNSUPPORTED_ANALYSIS,
                "analysis did not request an answerable evidence plan",
            )
        if self._mentions_wrong_product(context, request):
            return self._failure(
                RetrievalFailureCode.WRONG_SKU,
                "analysis references a product other than the immutable bound listing",
            )

        with self.database.read() as connection:
            # Establish tenant/listing scope before any exact or FTS lookup.
            listing = connection.execute(
                """SELECT listing_id, seller_id, price_cents, version
                   FROM listings WHERE seller_id = ? AND listing_id = ?""",
                (context.seller_id, context.bound_listing.listing_id),
            ).fetchone()
            show = connection.execute(
                "SELECT seller_id FROM shows WHERE seller_id = ? AND show_id = ?",
                (context.seller_id, context.show_id),
            ).fetchone()
            if listing is None or show is None:
                return self._failure(
                    RetrievalFailureCode.WRONG_SKU,
                    "bound listing is not in the trusted tenant scope",
                )

            records: list[EvidenceRecord] = []
            identity_rows = self._stored_rows(
                connection,
                context,
                FactType.LISTING_IDENTITY,
            )
            identity_result = self._one_record(identity_rows)
            if isinstance(identity_result, RetrievalResult):
                return identity_result
            records.append(identity_result)

            for fact_type in request.required_fact_types:
                if fact_type is FactType.LISTING_IDENTITY:
                    continue
                if fact_type is FactType.CURRENT_PRICE:
                    records.append(self._price_record(context, listing))
                    continue
                if fact_type is FactType.VARIANT_AVAILABILITY:
                    stock_result = self._stock_record(connection, context, request)
                    if isinstance(stock_result, RetrievalResult):
                        return stock_result
                    records.append(stock_result)
                    continue
                if fact_type in _POLICY_FACTS:
                    stored = self._one_record(self._stored_rows(connection, context, fact_type))
                    if isinstance(stored, RetrievalResult):
                        return stored
                    records.append(stored)
                    continue
                if fact_type in _RESEARCH_FACTS:
                    rows = self._research_rows(connection, context, request, fact_type)
                    stored = self._one_record(rows)
                    if isinstance(stored, RetrievalResult):
                        return stored
                    records.append(stored)
                    continue
                return self._failure(
                    RetrievalFailureCode.MISSING_EVIDENCE,
                    "requested fact type has no approved retrieval source",
                )

        return RetrievalResult(
            status=RetrievalStatus.SUCCEEDED,
            snapshot=EvidenceSnapshot(
                snapshot_id=self.id_factory(),
                seller_id=context.seller_id,
                show_id=context.show_id,
                listing_id=context.bound_listing.listing_id,
                epoch_id=context.bound_listing.epoch_id,
                created_at=context.observed_at,
                records=tuple(records),
            ),
        )

    def retrieve_template_bundle(
        self,
        context: TemplateRetrievalContext,
    ) -> RetrievalResult:
        """Load Workflow 1's complete bounded candidate set in one read boundary."""

        with self.database.read() as connection:
            listing = connection.execute(
                """SELECT listing_id, seller_id, price_cents, version
                   FROM listings WHERE seller_id = ? AND listing_id = ?""",
                (context.seller_id, context.bound_listing.listing_id),
            ).fetchone()
            show = connection.execute(
                "SELECT seller_id FROM shows WHERE seller_id = ? AND show_id = ?",
                (context.seller_id, context.show_id),
            ).fetchone()
            if listing is None or show is None:
                return self._failure(
                    RetrievalFailureCode.WRONG_SKU,
                    "bound listing is not in the trusted tenant scope",
                )

            identity = self._one_record(
                self._stored_rows(connection, context, FactType.LISTING_IDENTITY)
            )
            if isinstance(identity, RetrievalResult):
                return identity
            records: list[EvidenceRecord] = [identity, self._price_record(context, listing)]

            stock = self._all_stock_records(connection, context)
            if isinstance(stock, RetrievalResult):
                return stock
            records.extend(stock)

            for fact_type in sorted((*_POLICY_FACTS, *_RESEARCH_FACTS), key=lambda item: item.value):
                rows = self._stored_rows(connection, context, fact_type)
                if not rows:
                    continue
                record = self._one_record(rows)
                if isinstance(record, RetrievalResult):
                    return record
                records.append(record)

        records.sort(key=lambda record: (record.fact_type.value, record.evidence_id))
        if len(records) > 24:
            return self._failure(
                RetrievalFailureCode.CONFLICTING_EVIDENCE,
                "template evidence bundle exceeds the approved bounded size",
            )
        return RetrievalResult(
            status=RetrievalStatus.SUCCEEDED,
            snapshot=EvidenceSnapshot(
                snapshot_id=self.id_factory(),
                seller_id=context.seller_id,
                show_id=context.show_id,
                listing_id=context.bound_listing.listing_id,
                epoch_id=context.bound_listing.epoch_id,
                created_at=context.observed_at,
                records=tuple(records),
            ),
        )

    def revalidate(self, snapshot: EvidenceSnapshot) -> RetrievalResult:
        with self.database.read() as connection:
            active_epoch = connection.execute(
                """SELECT epoch_id FROM listing_epochs
                   WHERE seller_id = ? AND show_id = ? AND end_seq IS NULL""",
                (snapshot.seller_id, snapshot.show_id),
            ).fetchone()
            if active_epoch is None or active_epoch["epoch_id"] != snapshot.epoch_id:
                return self._failure(
                    RetrievalFailureCode.STALE_EVIDENCE,
                    "bound listing epoch is no longer active",
                )
            for record in snapshot.records:
                if record.fact_type is FactType.CURRENT_PRICE:
                    row = connection.execute(
                        """SELECT version FROM listings
                           WHERE seller_id = ? AND listing_id = ?""",
                        (snapshot.seller_id, snapshot.listing_id),
                    ).fetchone()
                    if row is None or int(row["version"]) != record.source_version:
                        return self._failure(
                            RetrievalFailureCode.STALE_EVIDENCE,
                            "listing price version changed after retrieval",
                        )
                if record.fact_type is FactType.VARIANT_AVAILABILITY:
                    variant_id = record.source_ref.rsplit("/", 1)[-1]
                    row = connection.execute(
                        """SELECT version FROM inventory
                           WHERE seller_id = ? AND listing_id = ? AND variant_id = ?""",
                        (snapshot.seller_id, snapshot.listing_id, variant_id),
                    ).fetchone()
                    if row is None or int(row["version"]) != record.source_version:
                        return self._failure(
                            RetrievalFailureCode.STALE_EVIDENCE,
                            "inventory version changed after retrieval",
                        )
        return RetrievalResult(status=RetrievalStatus.SUCCEEDED, snapshot=snapshot)

    def _mentions_wrong_product(
        self,
        context: RetrievalContext,
        request: EvidenceRequest,
    ) -> bool:
        mentions = " ".join((*request.product_mentions, *request.query_terms))
        candidates = _SKU_PATTERN.findall(mentions)
        if any(
            candidate.casefold() != context.bound_listing.sku.casefold()
            for candidate in candidates
        ):
            return True
        seller = self.catalog.seller(context.seller_id)
        recognized = explicit_product_matches(seller, mentions)
        if any(
            product.listing.listing_id != context.bound_listing.listing_id
            for product in recognized
        ):
            return True
        if request.product_mentions:
            named = explicit_product_matches(seller, " ".join(request.product_mentions))
            if len(named) != 1:
                return True
            return named[0].listing.listing_id != context.bound_listing.listing_id
        return False

    @staticmethod
    def _stored_rows(
        connection,
        context: Union[RetrievalContext, TemplateRetrievalContext],
        fact_type: FactType,
    ):
        return connection.execute(
            """SELECT * FROM copilot_evidence_records
               WHERE seller_id = ? AND listing_id = ? AND fact_type = ?
               ORDER BY evidence_id""",
            (context.seller_id, context.bound_listing.listing_id, fact_type.value),
        ).fetchall()

    def _research_rows(
        self,
        connection,
        context: RetrievalContext,
        request: EvidenceRequest,
        fact_type: FactType,
    ):
        scoped_rows = self._stored_rows(connection, context, fact_type)
        if len(scoped_rows) != 1:
            return scoped_rows
        tokens = re.findall(r"[A-Za-z0-9]+", " ".join(request.query_terms))[:16]
        if not tokens:
            return scoped_rows
        expression = " OR ".join(f'"{token}"' for token in tokens)
        matched_rows = connection.execute(
            """SELECT e.* FROM copilot_research_fts f
               JOIN copilot_evidence_records e ON e.evidence_id = f.evidence_id
               WHERE f.seller_id = ? AND f.listing_id = ? AND f.fact_type = ?
                 AND copilot_research_fts MATCH ?
               ORDER BY e.evidence_id""",
            (
                context.seller_id,
                context.bound_listing.listing_id,
                fact_type.value,
                expression,
            ),
        ).fetchall()
        return matched_rows or scoped_rows

    def _one_record(self, rows: Sequence) -> EvidenceRecord | RetrievalResult:
        if not rows:
            return self._failure(
                RetrievalFailureCode.MISSING_EVIDENCE,
                "required evidence is missing",
            )
        distinct = {(row["value"], int(row["source_version"])) for row in rows}
        if len(distinct) != 1 or len(rows) != 1:
            return self._failure(
                RetrievalFailureCode.CONFLICTING_EVIDENCE,
                "required evidence has conflicting sources",
            )
        return self._record_from_row(rows[0])

    @staticmethod
    def _record_from_row(row) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=row["evidence_id"],
            seller_id=row["seller_id"],
            listing_id=row["listing_id"],
            fact_type=FactType(row["fact_type"]),
            value=row["value"],
            source=EvidenceSource(row["source"]),
            source_ref=row["source_ref"],
            source_version=int(row["source_version"]),
            observed_at=_parse_utc(row["observed_at"]),
            provenance=row["provenance"],
        )

    @staticmethod
    def _price_record(
        context: Union[RetrievalContext, TemplateRetrievalContext],
        listing,
    ) -> EvidenceRecord:
        return EvidenceRecord(
            evidence_id=_evidence_id(
                context.seller_id,
                context.bound_listing.listing_id,
                "current_price",
            ),
            seller_id=context.seller_id,
            listing_id=context.bound_listing.listing_id,
            fact_type=FactType.CURRENT_PRICE,
            value=f"USD {int(listing['price_cents']) / 100:.2f}",
            source=EvidenceSource.MARKETPLACE_STATE,
            source_ref=f"sqlite:listings/{context.bound_listing.listing_id}/price_cents",
            source_version=int(listing["version"]),
            observed_at=context.observed_at,
            provenance="synthetic_seller_data",
        )

    def _stock_record(
        self,
        connection,
        context: RetrievalContext,
        request: EvidenceRequest,
    ) -> EvidenceRecord | RetrievalResult:
        product = next(
            product
            for product in self.catalog.seller(context.seller_id).products
            if product.listing.listing_id == context.bound_listing.listing_id
        )
        requested_labels = {label.casefold() for label in request.variant_mentions}
        matches = [
            variant
            for variant in product.variants
            if variant.label.casefold() in requested_labels
        ]
        if len(matches) != 1:
            return self._failure(
                RetrievalFailureCode.MISSING_EVIDENCE,
                "exact requested variant is missing or ambiguous",
            )
        variant = matches[0]
        row = connection.execute(
            """SELECT available_quantity, version FROM inventory
               WHERE seller_id = ? AND listing_id = ? AND variant_id = ?""",
            (context.seller_id, context.bound_listing.listing_id, variant.variant_id),
        ).fetchone()
        if row is None:
            return self._failure(
                RetrievalFailureCode.MISSING_EVIDENCE,
                "exact requested variant is unavailable in trusted state",
            )
        return EvidenceRecord(
            evidence_id=_evidence_id(
                context.seller_id,
                context.bound_listing.listing_id,
                f"variant_availability:{variant.variant_id}",
            ),
            seller_id=context.seller_id,
            listing_id=context.bound_listing.listing_id,
            fact_type=FactType.VARIANT_AVAILABILITY,
            value=f"{variant.label}: {int(row['available_quantity'])} available",
            source=EvidenceSource.MARKETPLACE_STATE,
            source_ref=f"sqlite:inventory/{variant.variant_id}",
            source_version=int(row["version"]),
            observed_at=context.observed_at,
            provenance="synthetic_seller_data",
        )

    def _all_stock_records(
        self,
        connection,
        context: TemplateRetrievalContext,
    ) -> list[EvidenceRecord] | RetrievalResult:
        product = next(
            product
            for product in self.catalog.seller(context.seller_id).products
            if product.listing.listing_id == context.bound_listing.listing_id
        )
        rows = connection.execute(
            """SELECT variant_id, available_quantity, version FROM inventory
               WHERE seller_id = ? AND listing_id = ? ORDER BY variant_id""",
            (context.seller_id, context.bound_listing.listing_id),
        ).fetchall()
        by_variant = {row["variant_id"]: row for row in rows}
        if set(by_variant) != {variant.variant_id for variant in product.variants}:
            return self._failure(
                RetrievalFailureCode.MISSING_EVIDENCE,
                "current variant inventory is incomplete for the bound listing",
            )
        records = []
        for variant in sorted(product.variants, key=lambda item: item.variant_id):
            row = by_variant[variant.variant_id]
            records.append(
                EvidenceRecord(
                    evidence_id=_evidence_id(
                        context.seller_id,
                        context.bound_listing.listing_id,
                        f"variant_availability:{variant.variant_id}",
                    ),
                    seller_id=context.seller_id,
                    listing_id=context.bound_listing.listing_id,
                    fact_type=FactType.VARIANT_AVAILABILITY,
                    value=f"{variant.label}: {int(row['available_quantity'])} available",
                    source=EvidenceSource.MARKETPLACE_STATE,
                    source_ref=f"sqlite:inventory/{variant.variant_id}",
                    source_version=int(row["version"]),
                    observed_at=context.observed_at,
                    provenance="synthetic_seller_data",
                )
            )
        return records

    @staticmethod
    def _failure(code: RetrievalFailureCode, message: str) -> RetrievalResult:
        return RetrievalResult(
            status=RetrievalStatus.FAILED,
            failure=RetrievalFailure(code=code, message=message),
        )


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _require_utc(parsed, field_name="observed_at")
