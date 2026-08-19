from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from sidestage.copilot.contracts import (
    AnalysisIntent,
    BoundListing,
    EvidenceRequest,
    EvidenceSource,
)
from sidestage.copilot.retrieval import (
    EvidenceRetriever,
    RetrievalContext,
    RetrievalFailureCode,
    RetrievalStatus,
    TemplateRetrievalContext,
)
from sidestage.domain.replies import (
    AnswerCategory,
    BindingBasis,
    BindingStatus,
    FactType,
)
from sidestage.fixtures.loader import load_seller_fixture
from sidestage.marketplace.authority import SellerAuthority
from sidestage.marketplace.service import (
    InventoryChangeRequest,
    MarketplaceService,
    PriceMarkdownRequest,
    PushRequest,
)
from sidestage.storage.database import MarketplaceDatabase


NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
IMPORTED_AT = "2026-08-17T11:00:00.000Z"
SELLER = "sel_velocity_kicks"
SHOW = "show_velocity_kicks"
LISTING = "lst_velocity_aero_dash"


@pytest.fixture()
def retrieval_runtime(tmp_path: Path):
    catalog = load_seller_fixture()
    database = MarketplaceDatabase(tmp_path / "sidestage.sqlite3")
    database.initialize(catalog, evidence_imported_at=IMPORTED_AT)
    marketplace = MarketplaceService(database)
    authority = SellerAuthority(
        seller_id=SELLER,
        show_id=SHOW,
        actor_id="demo_velocity_kicks",
    )
    marketplace.push(
        authority,
        PushRequest(target_listing_id=LISTING, expected_show_version=1),
        idempotency_key="push-aero",
    )
    epoch = marketplace.epochs(SHOW)[-1]
    context = RetrievalContext(
        question_id="qst_retrieval_1",
        trace_id="trc_retrieval_1",
        analysis_id="ana_retrieval_1",
        seller_id=SELLER,
        show_id=SHOW,
        bound_listing=BoundListing(
            listing_id=LISTING,
            sku="VK-AD-RC-001",
            epoch_id=epoch.epoch_id,
            binding_basis=BindingBasis.SOURCE_EPOCH,
            binding_status=BindingStatus.CERTAIN,
        ),
        observed_at=NOW,
        question="What is the current price?",
    )
    return database, marketplace, authority, EvidenceRetriever(database, catalog), context


def _request(*facts: FactType, queries: tuple[str, ...] = ()):
    return EvidenceRequest(
        intent=AnalysisIntent.ANSWERABLE,
        answer_category=(
            AnswerCategory.AVAILABILITY
            if FactType.VARIANT_AVAILABILITY in facts
            else AnswerCategory.PRODUCT_RESEARCH
            if any(
                fact
                in {
                    FactType.RELEASE_DATE,
                    FactType.MSRP,
                    FactType.MATERIALS,
                    FactType.SIZING,
                    FactType.AUTHENTICITY,
                    FactType.CONDITION,
                }
                for fact in facts
            )
            else AnswerCategory.PRICE
        ),
        product_mentions=("Aero Dash",),
        required_fact_types=facts,
        query_terms=queries,
    )


def _with_question(context: RetrievalContext, question: str) -> RetrievalContext:
    return context.model_copy(update={"question": question})


def test_retrieval_builds_one_fresh_tenant_scoped_sourced_snapshot(retrieval_runtime) -> None:
    _database, _marketplace, _authority, retriever, context = retrieval_runtime

    result = retriever.retrieve(
        _with_question(context, "Do you have 9 for man?"),
        _request(
            FactType.CURRENT_PRICE,
            FactType.VARIANT_AVAILABILITY,
            FactType.SHIPPING_POLICY,
        ),
    )

    assert result.status is RetrievalStatus.SUCCEEDED
    assert result.failure is None
    assert result.snapshot is not None
    assert result.snapshot.seller_id == SELLER
    assert result.snapshot.listing_id == LISTING
    assert {record.fact_type for record in result.snapshot.records} == {
        FactType.LISTING_IDENTITY,
        FactType.CURRENT_PRICE,
        FactType.VARIANT_AVAILABILITY,
        FactType.SHIPPING_POLICY,
    }
    for record in result.snapshot.records:
        assert record.seller_id == SELLER
        assert record.listing_id == LISTING
        assert record.evidence_id.startswith("evd_")
        assert record.source_ref.startswith(("/sellers/", "sqlite:"))
        assert record.source_version >= 1
        assert record.observed_at <= result.snapshot.created_at
        assert record.provenance == "synthetic_seller_data"

    price = next(
        record for record in result.snapshot.records if record.fact_type is FactType.CURRENT_PRICE
    )
    stock = next(
        record
        for record in result.snapshot.records
        if record.fact_type is FactType.VARIANT_AVAILABILITY
    )
    policy = next(
        record
        for record in result.snapshot.records
        if record.fact_type is FactType.SHIPPING_POLICY
    )
    assert price.value == "USD 160.00"
    assert stock.value == "US M 9: 2 available"
    assert policy.source is EvidenceSource.SELLER_POLICY


def test_template_bundle_exact_query_contains_only_python_resolved_variant(
    retrieval_runtime,
) -> None:
    _database, _marketplace, _authority, retriever, context = retrieval_runtime
    template_context = TemplateRetrievalContext(
        question_id=context.question_id,
        trace_id=context.trace_id,
        seller_id=context.seller_id,
        show_id=context.show_id,
        bound_listing=context.bound_listing,
        observed_at=context.observed_at,
        question="Is 9 M US available?",
    )

    first = retriever.retrieve_template_bundle(template_context)
    second = retriever.retrieve_template_bundle(template_context)

    assert first.status is RetrievalStatus.SUCCEEDED
    assert first.snapshot is not None
    assert second.snapshot is not None
    records = first.snapshot.records
    assert len(records) <= 24
    assert [record.evidence_id for record in records] == [
        record.evidence_id for record in second.snapshot.records
    ]
    assert [(record.fact_type.value, record.evidence_id) for record in records] == sorted(
        (record.fact_type.value, record.evidence_id) for record in records
    )
    assert {
        FactType.LISTING_IDENTITY,
        FactType.CURRENT_PRICE,
        FactType.VARIANT_AVAILABILITY,
        FactType.SHIPPING_POLICY,
        FactType.PAYMENT_POLICY,
        FactType.RETURNS_POLICY,
        FactType.RELEASE_DATE,
        FactType.MSRP,
        FactType.MATERIALS,
        FactType.SIZING,
        FactType.AUTHENTICITY,
        FactType.CONDITION,
    }.issubset({record.fact_type for record in records})
    stock = [record for record in records if record.fact_type is FactType.VARIANT_AVAILABILITY]
    assert len(stock) == 1
    assert stock[0].source_ref.endswith("/var_velocity_aero_dash_9")
    assert stock[0].value == "US M 9: 2 available"
    projected_stock = [
        record
        for record in first.snapshot.records
        if record.template_projection()["fact_type"] == FactType.VARIANT_AVAILABILITY.value
    ]
    assert len(projected_stock) == 1


@pytest.mark.parametrize(
    ("question", "expected_fragment"),
    (
        ("What sizes are available?", "Available sizes: US M 8, US M 9, US M 10"),
        ("How many pairs are left across all sizes?", "Total available: 7"),
    ),
)
def test_general_availability_uses_one_application_owned_summary_record(
    retrieval_runtime,
    question: str,
    expected_fragment: str,
) -> None:
    _database, _marketplace, _authority, retriever, context = retrieval_runtime
    result = retriever.retrieve_template_bundle(
        TemplateRetrievalContext(
            question_id=context.question_id,
            trace_id=context.trace_id,
            seller_id=context.seller_id,
            show_id=context.show_id,
            bound_listing=context.bound_listing,
            observed_at=context.observed_at,
            question=question,
        )
    )

    assert result.status is RetrievalStatus.SUCCEEDED
    assert result.snapshot is not None
    summaries = [
        record
        for record in result.snapshot.records
        if record.fact_type is FactType.AVAILABILITY_SUMMARY
    ]
    assert len(summaries) == 1
    assert expected_fragment in summaries[0].value
    assert not any(
        record.fact_type is FactType.VARIANT_AVAILABILITY
        for record in result.snapshot.records
    )


def test_product_research_uses_tenant_filtered_fts_and_preserves_provenance(
    retrieval_runtime,
) -> None:
    _database, _marketplace, _authority, retriever, context = retrieval_runtime

    result = retriever.retrieve(
        context,
        _request(
            FactType.MATERIALS,
            FactType.SIZING,
            queries=("Aero Dash mesh true size",),
        ),
    )

    assert result.snapshot is not None
    research = [
        record
        for record in result.snapshot.records
        if record.fact_type in {FactType.MATERIALS, FactType.SIZING}
    ]
    assert len(research) == 2
    assert all(record.source is EvidenceSource.PRODUCT_RESEARCH for record in research)
    assert all(record.source_ref.startswith("/sellers/") for record in research)
    assert "VaultConsign" not in " ".join(record.value for record in research)


def test_product_research_falls_back_to_exact_scoped_fact_when_terms_miss(
    retrieval_runtime,
) -> None:
    _database, _marketplace, _authority, retriever, context = retrieval_runtime

    result = retriever.retrieve(
        context,
        _request(
            FactType.SIZING,
            queries=("fit shape vocabulary not present in the indexed fact",),
        ),
    )

    assert result.status is RetrievalStatus.SUCCEEDED
    assert result.snapshot is not None
    sizing = next(
        record
        for record in result.snapshot.records
        if record.fact_type is FactType.SIZING
    )
    assert sizing.seller_id == SELLER
    assert sizing.listing_id == LISTING
    assert sizing.source is EvidenceSource.PRODUCT_RESEARCH


def test_wrong_sku_missing_variant_and_conflicting_evidence_are_typed(
    retrieval_runtime,
) -> None:
    database, _marketplace, _authority, retriever, context = retrieval_runtime

    wrong = EvidenceRequest(
        intent=AnalysisIntent.ANSWERABLE,
        answer_category=AnswerCategory.PRICE,
        product_mentions=("VC-HH-OC-101",),
        required_fact_types=(FactType.CURRENT_PRICE,),
    )
    wrong_result = retriever.retrieve(context, wrong)
    assert wrong_result.failure is not None
    assert wrong_result.failure.code is RetrievalFailureCode.WRONG_SKU

    wrong_name = EvidenceRequest(
        intent=AnalysisIntent.ANSWERABLE,
        answer_category=AnswerCategory.PRICE,
        product_mentions=("Court Pulse",),
        required_fact_types=(FactType.CURRENT_PRICE,),
    )
    wrong_name_result = retriever.retrieve(context, wrong_name)
    assert wrong_name_result.failure is not None
    assert wrong_name_result.failure.code is RetrievalFailureCode.WRONG_SKU

    missing_result = retriever.retrieve(
        _with_question(context, "Do you have US M size 99?"),
        _request(
            FactType.VARIANT_AVAILABILITY,
        ),
    )
    assert missing_result.failure is not None
    assert missing_result.failure.code is RetrievalFailureCode.MISSING_EVIDENCE

    with database.transaction() as connection:
        connection.execute(
            """INSERT INTO copilot_evidence_records(
                   evidence_id, seller_id, listing_id, fact_type, value,
                   source, source_ref, source_version, observed_at, provenance
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "evd_conflicting_materials",
                SELLER,
                LISTING,
                FactType.MATERIALS.value,
                "Conflicting material claim",
                EvidenceSource.PRODUCT_RESEARCH.value,
                "/sellers/2/products/0/facts/materials/conflict",
                1,
                IMPORTED_AT,
                "synthetic_seller_data",
            ),
        )
        connection.execute(
            """INSERT INTO copilot_research_fts(
                   evidence_id, seller_id, listing_id, fact_type, search_text
               ) VALUES (?, ?, ?, ?, ?)""",
            (
                "evd_conflicting_materials",
                SELLER,
                LISTING,
                FactType.MATERIALS.value,
                "Aero Dash mesh conflicting materials",
            ),
        )
    conflict = retriever.retrieve(
        context,
        _request(FactType.MATERIALS, queries=("Aero Dash mesh",)),
    )
    assert conflict.failure is not None
    assert conflict.failure.code is RetrievalFailureCode.CONFLICTING_EVIDENCE


def test_version_revalidation_detects_stale_mutable_evidence(retrieval_runtime) -> None:
    _database, marketplace, authority, retriever, context = retrieval_runtime
    result = retriever.retrieve(context, _request(FactType.CURRENT_PRICE))
    assert result.snapshot is not None

    marketplace.price_markdown(
        authority,
        PriceMarkdownRequest(
            listing_id=LISTING,
            new_price_cents=15000,
            expected_listing_version=1,
        ),
        idempotency_key="markdown-aero",
    )
    freshness = retriever.revalidate(result.snapshot)

    assert freshness.status is RetrievalStatus.FAILED
    assert freshness.failure is not None
    assert freshness.failure.code is RetrievalFailureCode.STALE_EVIDENCE


def test_aggregate_availability_revalidation_detects_any_inventory_change(
    retrieval_runtime,
) -> None:
    _database, marketplace, authority, retriever, context = retrieval_runtime
    result = retriever.retrieve_template_bundle(
        TemplateRetrievalContext(
            question_id=context.question_id,
            trace_id=context.trace_id,
            seller_id=context.seller_id,
            show_id=context.show_id,
            bound_listing=context.bound_listing,
            observed_at=context.observed_at,
            question="What sizes are available?",
        )
    )
    assert result.snapshot is not None

    marketplace.inventory_change(
        authority,
        InventoryChangeRequest(
            listing_id=LISTING,
            variant_id="var_velocity_aero_dash_8",
            new_available_quantity=0,
            expected_inventory_version=1,
        ),
        idempotency_key="stock-aero-8-zero",
    )
    freshness = retriever.revalidate(result.snapshot)

    assert freshness.status is RetrievalStatus.FAILED
    assert freshness.failure is not None
    assert freshness.failure.code is RetrievalFailureCode.STALE_EVIDENCE


def test_static_evidence_ids_are_stable_across_import_timestamps(tmp_path: Path) -> None:
    catalog = load_seller_fixture()
    first = MarketplaceDatabase(tmp_path / "first.sqlite3")
    second = MarketplaceDatabase(tmp_path / "second.sqlite3")
    first.initialize(catalog, evidence_imported_at="2026-08-17T10:00:00.000Z")
    second.initialize(catalog, evidence_imported_at="2026-08-17T11:00:00.000Z")

    def rows(database: MarketplaceDatabase):
        with database.read() as connection:
            return connection.execute(
                """SELECT evidence_id, observed_at FROM copilot_evidence_records
                   WHERE seller_id = ? AND listing_id = ? ORDER BY evidence_id""",
                (SELLER, LISTING),
            ).fetchall()

    first_rows = rows(first)
    second_rows = rows(second)
    assert [row["evidence_id"] for row in first_rows] == [
        row["evidence_id"] for row in second_rows
    ]
    assert {row["observed_at"] for row in first_rows} == {"2026-08-17T10:00:00.000Z"}
    assert {row["observed_at"] for row in second_rows} == {"2026-08-17T11:00:00.000Z"}
