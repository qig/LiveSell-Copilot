from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from sidestage.fixtures.loader import load_seller_fixture
from sidestage.marketplace.authority import SellerAuthority
from sidestage.marketplace.service import (
    AuditPersistenceError,
    MarketplaceAuthorityError,
    MarketplacePort,
    MarketplaceService,
    PushRequest,
    SwapRequest,
)
from sidestage.storage.database import MarketplaceDatabase


VELOCITY = "sel_velocity_kicks"
ROTATION = "sel_rotation_kicks"
VELOCITY_SHOW = "show_velocity_kicks"


@pytest.fixture()
def service(tmp_path: Path) -> MarketplaceService:
    database = MarketplaceDatabase(tmp_path / "marketplace.sqlite3")
    database.initialize(load_seller_fixture())
    return MarketplaceService(database)


@pytest.fixture()
def velocity() -> SellerAuthority:
    return SellerAuthority(
        seller_id=VELOCITY,
        show_id=VELOCITY_SHOW,
        actor_id="seller_velocity",
    )


def test_database_imports_catalog_with_empty_versioned_shows_and_wal(
    service: MarketplaceService,
) -> None:
    show = service.show_state(VELOCITY_SHOW)

    assert show.seller_id == VELOCITY
    assert show.active_listing_id is None
    assert show.version == 1
    assert service.database.journal_mode().lower() == "wal"
    assert isinstance(service, MarketplacePort)
    assert service.receipts(VELOCITY_SHOW) == ()


def test_request_contract_cannot_supply_trusted_authority() -> None:
    with pytest.raises(ValidationError):
        PushRequest.model_validate(
            {
                "target_listing_id": "lst_velocity_aero_dash",
                "expected_show_version": 1,
                "seller_id": VELOCITY,
            }
        )


def test_missing_or_wrong_tenant_authority_cannot_mutate(
    service: MarketplaceService,
    velocity: SellerAuthority,
) -> None:
    request = PushRequest(
        target_listing_id="lst_rotation_flash_arc",
        expected_show_version=1,
    )

    with pytest.raises(TypeError):
        service.push(None, request, idempotency_key="missing-auth")  # type: ignore[arg-type]

    receipt = service.push(velocity, request, idempotency_key="foreign-listing")

    assert receipt.status == "rejected"
    assert receipt.error_code == "listing_not_in_scope"
    assert service.show_state(VELOCITY_SHOW).active_listing_id is None

    mismatched_show = SellerAuthority(
        seller_id=VELOCITY,
        show_id="show_rotation_kicks",
        actor_id="seller_velocity",
    )
    with pytest.raises(MarketplaceAuthorityError):
        service.push(
            mismatched_show,
            PushRequest(
                target_listing_id="lst_velocity_aero_dash",
                expected_show_version=1,
            ),
            idempotency_key="wrong-show",
        )

    assert service.show_state("show_rotation_kicks").active_listing_id is None


def test_same_idempotency_request_returns_original_receipt_and_conflict_rejects(
    service: MarketplaceService,
    velocity: SellerAuthority,
) -> None:
    first = service.push(
        velocity,
        PushRequest(
            target_listing_id="lst_velocity_aero_dash",
            expected_show_version=1,
        ),
        idempotency_key="push-once",
    )
    replay = service.push(
        velocity,
        PushRequest(
            target_listing_id="lst_velocity_aero_dash",
            expected_show_version=1,
        ),
        idempotency_key="push-once",
    )
    conflict = service.swap(
        velocity,
        SwapRequest(
            target_listing_id="lst_velocity_court_pulse",
            expected_active_listing_id="lst_velocity_aero_dash",
            expected_show_version=2,
        ),
        idempotency_key="push-once",
    )

    assert first.status == "applied"
    assert replay.receipt_id == first.receipt_id
    assert conflict.status == "rejected"
    assert conflict.error_code == "idempotency_conflict"
    assert service.show_state(VELOCITY_SHOW).active_listing_id == "lst_velocity_aero_dash"


def test_idempotency_identity_includes_the_trusted_actor(
    service: MarketplaceService,
    velocity: SellerAuthority,
) -> None:
    request = PushRequest(
        target_listing_id="lst_velocity_aero_dash",
        expected_show_version=1,
    )
    service.push(velocity, request, idempotency_key="actor-owned-key")
    another_actor = SellerAuthority(
        seller_id=VELOCITY,
        show_id=VELOCITY_SHOW,
        actor_id="seller_velocity_other_device",
    )

    conflict = service.push(
        another_actor,
        request,
        idempotency_key="actor-owned-key",
    )

    assert conflict.status == "rejected"
    assert conflict.error_code == "idempotency_conflict"


@pytest.mark.parametrize("stage", ["before_effect", "after_effect"])
def test_effect_failure_rolls_back_state_and_records_failed_receipt(
    service: MarketplaceService,
    velocity: SellerAuthority,
    stage: str,
) -> None:
    service.fail_next(stage)

    receipt = service.push(
        velocity,
        PushRequest(
            target_listing_id="lst_velocity_aero_dash",
            expected_show_version=1,
        ),
        idempotency_key=f"effect-fails-{stage}",
    )

    assert receipt.status == "failed"
    assert receipt.error_code == f"injected_{stage}"
    assert receipt.before == receipt.after
    assert service.show_state(VELOCITY_SHOW).active_listing_id is None
    assert service.epochs(VELOCITY_SHOW) == ()
    assert receipt.requested_at <= receipt.recorded_at
    if receipt.executed_at is not None:
        assert receipt.requested_at <= receipt.executed_at <= receipt.recorded_at
    assert receipt.duration_ms >= 0


def test_verification_failure_rolls_back_state_and_records_failed_receipt(
    service: MarketplaceService,
    velocity: SellerAuthority,
) -> None:
    service.fail_next("verification")

    receipt = service.push(
        velocity,
        PushRequest(
            target_listing_id="lst_velocity_aero_dash",
            expected_show_version=1,
        ),
        idempotency_key="verification-fails",
    )

    assert receipt.status == "failed"
    assert receipt.error_code == "injected_verification"
    assert service.show_state(VELOCITY_SHOW).active_listing_id is None
    assert service.epochs(VELOCITY_SHOW) == ()


def test_receipt_persistence_failure_rolls_back_effect_and_promises_no_receipt(
    service: MarketplaceService,
    velocity: SellerAuthority,
) -> None:
    service.fail_next("before_receipt")

    with pytest.raises(AuditPersistenceError):
        service.push(
            velocity,
            PushRequest(
                target_listing_id="lst_velocity_aero_dash",
                expected_show_version=1,
            ),
            idempotency_key="audit-fails",
        )

    assert service.show_state(VELOCITY_SHOW).active_listing_id is None
    assert service.receipts(VELOCITY_SHOW) == ()


def test_out_of_stock_target_is_rejected_without_mutation(
    service: MarketplaceService,
    velocity: SellerAuthority,
) -> None:
    with service.database.transaction() as connection:
        connection.execute(
            """UPDATE inventory SET available_quantity = 0
               WHERE listing_id = 'lst_velocity_court_pulse'"""
        )

    receipt = service.push(
        velocity,
        PushRequest(
            target_listing_id="lst_velocity_court_pulse",
            expected_show_version=1,
        ),
        idempotency_key="out-of-stock",
    )

    assert receipt.status == "rejected"
    assert receipt.error_code == "listing_out_of_stock"
    assert receipt.before == receipt.after
    assert service.show_state(VELOCITY_SHOW).active_listing_id is None


def test_two_concurrent_swaps_from_one_version_have_one_winner(
    service: MarketplaceService,
    velocity: SellerAuthority,
) -> None:
    pushed = service.push(
        velocity,
        PushRequest(
            target_listing_id="lst_velocity_aero_dash",
            expected_show_version=1,
        ),
        idempotency_key="initial-push",
    )
    assert pushed.status == "applied"

    def swap(target: str) -> str:
        return service.swap(
            velocity,
            SwapRequest(
                target_listing_id=target,
                expected_active_listing_id="lst_velocity_aero_dash",
                expected_show_version=2,
            ),
            idempotency_key=f"swap-{target}",
        ).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(
            pool.map(
                swap,
                ["lst_velocity_court_pulse", "lst_velocity_terra_shift"],
            )
        )

    assert sorted(statuses) == ["applied", "rejected"]
    assert service.show_state(VELOCITY_SHOW).version == 3
