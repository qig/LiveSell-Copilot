from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from sidestage.domain.operations import OperationType
from sidestage.fixtures.loader import load_seller_fixture
from sidestage.marketplace.authority import SellerAuthority
from sidestage.marketplace.service import (
    InventoryChangeRequest,
    MarketplaceService,
    PriceMarkdownRequest,
    PushRequest,
    SwapRequest,
    UnlistRequest,
)
from sidestage.storage.database import MarketplaceDatabase


SELLER = "sel_velocity_kicks"
SHOW = "show_velocity_kicks"
AERO = "lst_velocity_aero_dash"
COURT = "lst_velocity_court_pulse"
TERRA = "lst_velocity_terra_shift"
AERO_8 = "var_velocity_aero_dash_8"


@pytest.fixture()
def service(tmp_path: Path) -> MarketplaceService:
    database = MarketplaceDatabase(tmp_path / "marketplace.sqlite3")
    database.initialize(load_seller_fixture())
    return MarketplaceService(database)


@pytest.fixture()
def authority() -> SellerAuthority:
    return SellerAuthority(seller_id=SELLER, show_id=SHOW, actor_id="seller_velocity")


def push_aero(service: MarketplaceService, authority: SellerAuthority):
    receipt = service.push(
        authority,
        PushRequest(target_listing_id=AERO, expected_show_version=1),
        idempotency_key="push-aero",
    )
    assert receipt.status == "applied"
    return receipt


def test_push_swap_and_compensation_append_epoch_history(
    service: MarketplaceService,
    authority: SellerAuthority,
) -> None:
    push = push_aero(service, authority)
    assert push.operation_type == OperationType.PUSH
    assert service.show_state(SHOW).active_listing_id == AERO
    assert [(epoch.listing_id, epoch.end_seq) for epoch in service.epochs(SHOW)] == [
        (AERO, None)
    ]

    swap = service.swap(
        authority,
        SwapRequest(
            target_listing_id=COURT,
            expected_active_listing_id=AERO,
            expected_show_version=2,
        ),
        idempotency_key="swap-to-court",
    )
    assert swap.status == "applied"
    assert service.show_state(SHOW).active_listing_id == COURT

    undo = service.compensate(
        authority,
        swap.receipt_id,
        idempotency_key="undo-swap",
    )
    assert undo.status == "applied"
    assert undo.operation_type == OperationType.SWAP
    assert undo.compensation_for_receipt_id == swap.receipt_id
    assert service.show_state(SHOW).active_listing_id == AERO

    epochs = service.epochs(SHOW)
    assert [(item.listing_id, item.start_seq, item.end_seq) for item in epochs] == [
        (AERO, 1, 2),
        (COURT, 2, 3),
        (AERO, 3, None),
    ]


def test_old_compensation_refuses_after_newer_show_change(
    service: MarketplaceService,
    authority: SellerAuthority,
) -> None:
    push = push_aero(service, authority)
    service.swap(
        authority,
        SwapRequest(
            target_listing_id=COURT,
            expected_active_listing_id=AERO,
            expected_show_version=2,
        ),
        idempotency_key="newer-swap",
    )

    undo = service.compensate(
        authority,
        push.receipt_id,
        idempotency_key="stale-undo",
    )

    assert undo.status == "rejected"
    assert undo.error_code == "stale_compensation"
    assert service.show_state(SHOW).active_listing_id == COURT


def test_push_can_be_conditionally_undone_to_empty_slot(
    service: MarketplaceService,
    authority: SellerAuthority,
) -> None:
    push = push_aero(service, authority)

    undo = service.compensate(
        authority,
        push.receipt_id,
        idempotency_key="undo-push",
    )

    assert undo.status == "applied"
    assert undo.operation_type == OperationType.PUSH
    assert undo.compensation_for_receipt_id == push.receipt_id
    assert undo.before["show"]["active_listing_id"] == AERO
    assert undo.after["show"]["active_listing_id"] is None
    assert service.show_state(SHOW).active_listing_id is None
    assert service.epochs(SHOW)[0].end_seq == 2


def test_unlist_and_undo_are_explicit_and_version_checked(
    service: MarketplaceService,
    authority: SellerAuthority,
) -> None:
    push_aero(service, authority)
    unlist = service.unlist(
        authority,
        UnlistRequest(expected_active_listing_id=AERO, expected_show_version=2),
        idempotency_key="unlist-aero",
    )

    assert unlist.status == "applied"
    assert unlist.before["listing"]["status"] == "available"
    assert unlist.after["listing"]["status"] == "unlisted"
    assert service.show_state(SHOW).active_listing_id is None
    assert service.listing_state(AERO).status == "unlisted"

    undo = service.compensate(
        authority,
        unlist.receipt_id,
        idempotency_key="undo-unlist",
    )
    assert undo.status == "applied"
    assert service.show_state(SHOW).active_listing_id == AERO
    assert service.listing_state(AERO).status == "available"


def test_markdown_enforces_active_lower_and_floor_then_undoes(
    service: MarketplaceService,
    authority: SellerAuthority,
) -> None:
    push_aero(service, authority)
    before = service.listing_state(AERO)

    same_price = service.price_markdown(
        authority,
        PriceMarkdownRequest(
            listing_id=AERO,
            new_price_cents=before.price_cents,
            expected_listing_version=before.version,
        ),
        idempotency_key="same-price",
    )
    assert same_price.status == "rejected"
    assert same_price.error_code == "markdown_must_lower_price"

    too_low = service.price_markdown(
        authority,
        PriceMarkdownRequest(
            listing_id=AERO,
            new_price_cents=before.floor_price_cents - 1,
            expected_listing_version=before.version,
        ),
        idempotency_key="below-floor",
    )
    assert too_low.status == "rejected"
    assert too_low.error_code == "below_price_floor"

    markdown = service.price_markdown(
        authority,
        PriceMarkdownRequest(
            listing_id=AERO,
            new_price_cents=before.price_cents - 500,
            expected_listing_version=before.version,
        ),
        idempotency_key="markdown-aero",
    )
    assert markdown.status == "applied"

    stale = service.price_markdown(
        authority,
        PriceMarkdownRequest(
            listing_id=AERO,
            new_price_cents=before.price_cents - 1000,
            expected_listing_version=before.version,
        ),
        idempotency_key="stale-markdown",
    )
    assert stale.status == "rejected"
    assert stale.error_code == "stale_listing_version"

    undo = service.compensate(
        authority,
        markdown.receipt_id,
        idempotency_key="undo-markdown",
    )
    assert undo.status == "applied"
    assert service.listing_state(AERO).price_cents == before.price_cents


def test_inventory_change_zero_does_not_unlist_and_can_be_undone(
    service: MarketplaceService,
    authority: SellerAuthority,
) -> None:
    push_aero(service, authority)
    before = service.inventory_state(AERO_8)
    with pytest.raises(ValidationError):
        InventoryChangeRequest(
            listing_id=AERO,
            variant_id=AERO_8,
            new_available_quantity=-1,
            expected_inventory_version=before.version,
        )

    wrong_variant = service.inventory_change(
        authority,
        InventoryChangeRequest(
            listing_id=AERO,
            variant_id="var_velocity_court_pulse_8",
            new_available_quantity=0,
            expected_inventory_version=1,
        ),
        idempotency_key="variant-from-other-listing",
    )
    assert wrong_variant.status == "rejected"
    assert wrong_variant.error_code == "variant_not_in_listing"

    change = service.inventory_change(
        authority,
        InventoryChangeRequest(
            listing_id=AERO,
            variant_id=AERO_8,
            new_available_quantity=0,
            expected_inventory_version=before.version,
        ),
        idempotency_key="zero-size-eight",
    )

    assert change.status == "applied"
    assert service.inventory_state(AERO_8).available_quantity == 0
    assert service.show_state(SHOW).active_listing_id == AERO
    assert service.listing_state(AERO).status == "available"

    undo = service.compensate(
        authority,
        change.receipt_id,
        idempotency_key="undo-inventory",
    )
    assert undo.status == "applied"
    assert service.inventory_state(AERO_8).available_quantity == before.available_quantity


def test_concurrent_inventory_changes_from_one_version_have_one_winner(
    service: MarketplaceService,
    authority: SellerAuthority,
) -> None:
    push_aero(service, authority)
    version = service.inventory_state(AERO_8).version

    def set_quantity(quantity: int) -> str:
        return service.inventory_change(
            authority,
            InventoryChangeRequest(
                listing_id=AERO,
                variant_id=AERO_8,
                new_available_quantity=quantity,
                expected_inventory_version=version,
            ),
            idempotency_key=f"inventory-{quantity}",
        ).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(set_quantity, [1, 2]))

    assert sorted(statuses) == ["applied", "rejected"]


def test_invalid_action_matrix_has_zero_mutation_and_exact_five_vocabulary(
    service: MarketplaceService,
    authority: SellerAuthority,
) -> None:
    assert {item.value for item in OperationType} == {
        "push",
        "swap",
        "unlist",
        "price_markdown",
        "inventory_change",
    }
    before = service.show_state(SHOW)

    swap_empty = service.swap(
        authority,
        SwapRequest(
            target_listing_id=COURT,
            expected_active_listing_id=AERO,
            expected_show_version=1,
        ),
        idempotency_key="swap-empty",
    )
    unlist_empty = service.unlist(
        authority,
        UnlistRequest(expected_active_listing_id=AERO, expected_show_version=1),
        idempotency_key="unlist-empty",
    )

    assert swap_empty.status == unlist_empty.status == "rejected"
    assert service.show_state(SHOW) == before
    assert not hasattr(service, "clear")
    assert not hasattr(service, "relist")


def test_push_and_swap_reject_invalid_slot_transitions_without_mutation(
    service: MarketplaceService,
    authority: SellerAuthority,
) -> None:
    push_aero(service, authority)
    before = service.show_state(SHOW)

    second_push = service.push(
        authority,
        PushRequest(target_listing_id=COURT, expected_show_version=2),
        idempotency_key="push-nonempty",
    )
    same_target_swap = service.swap(
        authority,
        SwapRequest(
            target_listing_id=AERO,
            expected_active_listing_id=AERO,
            expected_show_version=2,
        ),
        idempotency_key="swap-same-target",
    )

    assert second_push.error_code == "active_slot_not_empty"
    assert same_target_swap.error_code == "swap_target_is_active"
    assert service.show_state(SHOW) == before


def test_unlisted_listing_cannot_be_pushed_without_compensation(
    service: MarketplaceService,
    authority: SellerAuthority,
) -> None:
    push_aero(service, authority)
    service.unlist(
        authority,
        UnlistRequest(expected_active_listing_id=AERO, expected_show_version=2),
        idempotency_key="make-unlisted",
    )

    rejected = service.push(
        authority,
        PushRequest(target_listing_id=AERO, expected_show_version=3),
        idempotency_key="cannot-relist",
    )

    assert rejected.status == "rejected"
    assert rejected.error_code == "listing_unavailable"
    assert service.show_state(SHOW).active_listing_id is None


def test_swap_rejects_an_out_of_stock_target_without_changing_active_listing(
    service: MarketplaceService,
    authority: SellerAuthority,
) -> None:
    push_aero(service, authority)
    with service.database.transaction() as connection:
        connection.execute(
            "UPDATE inventory SET available_quantity = 0 WHERE listing_id = ?",
            (COURT,),
        )

    rejected = service.swap(
        authority,
        SwapRequest(
            target_listing_id=COURT,
            expected_active_listing_id=AERO,
            expected_show_version=2,
        ),
        idempotency_key="swap-out-of-stock",
    )

    assert rejected.status == "rejected"
    assert rejected.error_code == "listing_out_of_stock"
    assert service.show_state(SHOW).active_listing_id == AERO


def test_scalar_compensations_refuse_after_newer_versions(
    service: MarketplaceService,
    authority: SellerAuthority,
) -> None:
    push_aero(service, authority)
    listing = service.listing_state(AERO)
    first_markdown = service.price_markdown(
        authority,
        PriceMarkdownRequest(
            listing_id=AERO,
            new_price_cents=listing.price_cents - 500,
            expected_listing_version=listing.version,
        ),
        idempotency_key="first-markdown",
    )
    service.price_markdown(
        authority,
        PriceMarkdownRequest(
            listing_id=AERO,
            new_price_cents=listing.price_cents - 1000,
            expected_listing_version=listing.version + 1,
        ),
        idempotency_key="newer-markdown",
    )
    stale_markdown_undo = service.compensate(
        authority,
        first_markdown.receipt_id,
        idempotency_key="stale-markdown-undo",
    )

    inventory = service.inventory_state(AERO_8)
    first_inventory = service.inventory_change(
        authority,
        InventoryChangeRequest(
            listing_id=AERO,
            variant_id=AERO_8,
            new_available_quantity=3,
            expected_inventory_version=inventory.version,
        ),
        idempotency_key="first-inventory",
    )
    service.inventory_change(
        authority,
        InventoryChangeRequest(
            listing_id=AERO,
            variant_id=AERO_8,
            new_available_quantity=2,
            expected_inventory_version=inventory.version + 1,
        ),
        idempotency_key="newer-inventory",
    )
    stale_inventory_undo = service.compensate(
        authority,
        first_inventory.receipt_id,
        idempotency_key="stale-inventory-undo",
    )

    for original, undo in (
        (first_markdown, stale_markdown_undo),
        (first_inventory, stale_inventory_undo),
    ):
        assert undo.status == "rejected"
        assert undo.error_code == "stale_compensation"
        assert undo.operation_type == original.operation_type
        assert undo.compensation_for_receipt_id == original.receipt_id


def test_all_five_operations_have_complete_idempotent_receipts(
    service: MarketplaceService,
    authority: SellerAuthority,
) -> None:
    actions = []

    push_request = PushRequest(target_listing_id=AERO, expected_show_version=1)
    actions.append(
        (
            service.push(authority, push_request, idempotency_key="all-push"),
            service.push(authority, push_request, idempotency_key="all-push"),
        )
    )

    listing = service.listing_state(AERO)
    markdown_request = PriceMarkdownRequest(
        listing_id=AERO,
        new_price_cents=listing.price_cents - 500,
        expected_listing_version=listing.version,
    )
    actions.append(
        (
            service.price_markdown(
                authority, markdown_request, idempotency_key="all-markdown"
            ),
            service.price_markdown(
                authority, markdown_request, idempotency_key="all-markdown"
            ),
        )
    )

    inventory = service.inventory_state(AERO_8)
    inventory_request = InventoryChangeRequest(
        listing_id=AERO,
        variant_id=AERO_8,
        new_available_quantity=inventory.available_quantity - 1,
        expected_inventory_version=inventory.version,
    )
    actions.append(
        (
            service.inventory_change(
                authority, inventory_request, idempotency_key="all-inventory"
            ),
            service.inventory_change(
                authority, inventory_request, idempotency_key="all-inventory"
            ),
        )
    )

    swap_request = SwapRequest(
        target_listing_id=COURT,
        expected_active_listing_id=AERO,
        expected_show_version=2,
    )
    actions.append(
        (
            service.swap(authority, swap_request, idempotency_key="all-swap"),
            service.swap(authority, swap_request, idempotency_key="all-swap"),
        )
    )

    unlist_request = UnlistRequest(
        expected_active_listing_id=COURT,
        expected_show_version=3,
    )
    actions.append(
        (
            service.unlist(authority, unlist_request, idempotency_key="all-unlist"),
            service.unlist(authority, unlist_request, idempotency_key="all-unlist"),
        )
    )

    assert {first.operation_type for first, _ in actions} == set(OperationType)
    for first, replay in actions:
        assert first.status == "applied"
        assert replay.receipt_id == first.receipt_id
        assert first.before != first.after
        assert first.request
        assert first.authorization_verdict == "authorized"
        assert first.policy_verdict == "allowed"
        assert first.requested_at <= first.executed_at <= first.recorded_at
        assert first.duration_ms >= 0
