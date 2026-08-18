from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from sidestage.copilot.routing import CopilotRouter, canonicalize_question
from sidestage.domain.replies import BindingBasis, QuestionState, ReplyRoute
from sidestage.fixtures.loader import load_seller_fixture
from sidestage.marketplace.authority import SellerAuthority
from sidestage.marketplace.service import MarketplaceService, PushRequest, SwapRequest
from sidestage.storage.database import MarketplaceDatabase
from sidestage.streaming.hub import StreamEventStore
from sidestage.streaming.ingest import EventIngestor


SELLER = "sel_velocity_kicks"
SHOW = "show_velocity_kicks"
AERO = "lst_velocity_aero_dash"
COURT = "lst_velocity_court_pulse"
FIXED_TIME = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def runtime(tmp_path: Path):
    catalog = load_seller_fixture()
    database = MarketplaceDatabase(tmp_path / "sidestage.sqlite3")
    database.initialize(catalog)
    marketplace = MarketplaceService(database)
    authority = SellerAuthority(
        seller_id=SELLER,
        show_id=SHOW,
        actor_id="demo_velocity_kicks",
    )
    stream_store = StreamEventStore(database)
    ingestor = EventIngestor(database, stream_store, wall_clock=lambda: FIXED_TIME)
    counter = iter(range(1, 100))
    router = CopilotRouter(
        database,
        catalog,
        id_factory=lambda: f"qst_route_{next(counter)}",
    )
    marketplace.push(
        authority,
        PushRequest(target_listing_id=AERO, expected_show_version=1),
        idempotency_key="push-aero",
    )
    return database, marketplace, authority, ingestor, router


def _ingest(ingestor: EventIngestor, authority: SellerAuthority, text: str):
    return ingestor.ingest(
        authority,
        customer_display_name="tester",
        raw_text=text,
        input_origin="custom",
    )


def test_noise_bypasses_work_but_mixed_greeting_question_proceeds(runtime) -> None:
    _database, _marketplace, authority, ingestor, router = runtime

    emoji = router.route(_ingest(ingestor, authority, "🔥🔥"))
    greeting = router.route(_ingest(ingestor, authority, "  HELLO!!! "))
    mixed = router.route(_ingest(ingestor, authority, "Hi! How much is this pair?"))

    assert emoji.route is greeting.route is ReplyRoute.NOISE
    assert not emoji.should_process and not greeting.should_process
    assert mixed.route is ReplyRoute.ELIGIBLE
    assert mixed.state is QuestionState.QUEUED
    assert mixed.should_process

    reaction = router.route(_ingest(ingestor, authority, "Clean pair!"))
    assert reaction.route is ReplyRoute.NOISE
    assert not reaction.should_process


def test_normalization_and_deterministic_route_are_two_real_component_calls(runtime) -> None:
    database, _marketplace, authority, ingestor, router = runtime
    event = _ingest(ingestor, authority, "How much is this pair?")

    normalized = router.normalize_and_deduplicate(event)

    assert normalized.event_id == event.event_id
    assert normalized.preclassified_decision is None
    with database.read() as connection:
        pending = connection.execute(
            "SELECT route, state FROM copilot_questions WHERE event_id = ?",
            (event.event_id,),
        ).fetchone()
    assert pending["route"] == "pending"
    assert pending["state"] is None

    decision = router.route(normalized)

    assert decision.route is ReplyRoute.ELIGIBLE
    assert decision.state is QuestionState.QUEUED


def test_normalization_duplicates_group_within_epoch_but_paraphrases_do_not(runtime) -> None:
    database, _marketplace, authority, ingestor, router = runtime

    first = router.route(_ingest(ingestor, authority, "How much is this pair?"))
    duplicate = router.route(_ingest(ingestor, authority, "HOW MUCH... IS this pair?! 👟"))
    paraphrase = router.route(_ingest(ingestor, authority, "What is the price?"))
    replay = router.route(ingestor.events(authority)[0])

    assert canonicalize_question("HOW MUCH... IS this pair?! 👟") == "how much is this pair"
    assert first.route is ReplyRoute.ELIGIBLE
    assert duplicate.route is ReplyRoute.DUPLICATE
    assert duplicate.canonical_question_id == first.question_id
    assert duplicate.state is QuestionState.GROUPED
    assert paraphrase.route is ReplyRoute.ELIGIBLE
    assert paraphrase.canonical_question_id is None
    assert replay.question_id == first.question_id
    assert replay.event_replay
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM chat_events").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM copilot_questions").fetchone()[0] == 3


def test_question_before_swap_stays_bound_to_previous_listing_and_skips_work(runtime) -> None:
    _database, marketplace, authority, ingestor, router = runtime
    before_swap = _ingest(ingestor, authority, "How much is this pair?")
    marketplace.swap(
        authority,
        SwapRequest(
            target_listing_id=COURT,
            expected_active_listing_id=AERO,
            expected_show_version=2,
        ),
        idempotency_key="swap-court",
    )

    decision = router.route(before_swap)

    assert decision.route is ReplyRoute.ELIGIBLE
    assert decision.state is QuestionState.NEEDS_SELLER
    assert decision.reason_code == "previous_listing"
    assert decision.bound_listing is not None
    assert decision.bound_listing.listing_id == AERO
    assert decision.bound_listing.sku == "VK-AD-RC-001"
    assert not decision.should_process


def test_matching_text_on_opposite_sides_of_swap_is_not_grouped(runtime) -> None:
    _database, marketplace, authority, ingestor, router = runtime
    before = router.route(_ingest(ingestor, authority, "Is size 9 available?"))
    marketplace.swap(
        authority,
        SwapRequest(
            target_listing_id=COURT,
            expected_active_listing_id=AERO,
            expected_show_version=2,
        ),
        idempotency_key="swap-court",
    )
    after = router.route(_ingest(ingestor, authority, "Is size 9 available?"))

    assert before.route is after.route is ReplyRoute.ELIGIBLE
    assert before.bound_listing is not None and after.bound_listing is not None
    assert before.bound_listing.epoch_id != after.bound_listing.epoch_id
    assert after.canonical_question_id is None


def test_unique_explicit_sku_overrides_source_epoch_without_retargeting(runtime) -> None:
    _database, marketplace, authority, ingestor, router = runtime
    aero_question = _ingest(ingestor, authority, "What is VK-AD-RC-001 priced at?")
    marketplace.swap(
        authority,
        SwapRequest(
            target_listing_id=COURT,
            expected_active_listing_id=AERO,
            expected_show_version=2,
        ),
        idempotency_key="swap-court",
    )

    decision = router.route(aero_question)

    assert decision.bound_listing is not None
    assert decision.bound_listing.binding_basis is BindingBasis.EXPLICIT
    assert decision.bound_listing.listing_id == AERO
    assert decision.reason_code == "previous_listing"
    assert not decision.should_process


def test_unique_product_name_cannot_be_answered_from_the_wrong_active_listing(runtime) -> None:
    _database, marketplace, authority, ingestor, router = runtime

    never_shown = router.route(
        _ingest(ingestor, authority, "How much is the Court Pulse?")
    )
    assert never_shown.bound_listing is None
    assert never_shown.route is ReplyRoute.AMBIGUOUS_OR_UNSUPPORTED
    assert never_shown.reason_code == "uncertain_listing_binding"
    assert not never_shown.should_process

    marketplace.swap(
        authority,
        SwapRequest(
            target_listing_id=COURT,
            expected_active_listing_id=AERO,
            expected_show_version=2,
        ),
        idempotency_key="swap-court-for-name-binding",
    )
    previous = router.route(
        _ingest(ingestor, authority, "What did the Aero Dash cost?")
    )

    assert previous.bound_listing is not None
    assert previous.bound_listing.binding_basis is BindingBasis.EXPLICIT
    assert previous.bound_listing.listing_id == AERO
    assert previous.reason_code == "previous_listing"
    assert not previous.should_process
