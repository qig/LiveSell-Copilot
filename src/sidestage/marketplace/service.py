"""Atomic, version-checked seller operations with durable outcome receipts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable, Dict, Literal, Mapping, Optional, Protocol, Tuple, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from sidestage.domain.models import ListingId, VariantId
from sidestage.domain.operations import OperationType
from sidestage.marketplace.authority import SellerAuthority
from sidestage.storage.database import MarketplaceDatabase


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PushRequest(StrictRequest):
    target_listing_id: ListingId
    expected_show_version: int = Field(strict=True, gt=0)


class SwapRequest(StrictRequest):
    target_listing_id: ListingId
    expected_active_listing_id: ListingId
    expected_show_version: int = Field(strict=True, gt=0)


class UnlistRequest(StrictRequest):
    expected_active_listing_id: ListingId
    expected_show_version: int = Field(strict=True, gt=0)


class PriceMarkdownRequest(StrictRequest):
    listing_id: ListingId
    new_price_cents: int = Field(strict=True, gt=0)
    expected_listing_version: int = Field(strict=True, gt=0)


class InventoryChangeRequest(StrictRequest):
    listing_id: ListingId
    variant_id: VariantId
    new_available_quantity: int = Field(strict=True, ge=0)
    expected_inventory_version: int = Field(strict=True, gt=0)


class ShowState(BaseModel):
    model_config = ConfigDict(frozen=True)
    show_id: str
    seller_id: str
    active_listing_id: Optional[str]
    version: int
    show_seq: int


class ListingState(BaseModel):
    model_config = ConfigDict(frozen=True)
    listing_id: str
    seller_id: str
    price_cents: int
    floor_price_cents: int
    status: Literal["available", "unlisted"]
    version: int


class InventoryState(BaseModel):
    model_config = ConfigDict(frozen=True)
    variant_id: str
    listing_id: str
    seller_id: str
    available_quantity: int
    version: int


class ListingEpoch(BaseModel):
    model_config = ConfigDict(frozen=True)
    epoch_id: str
    seller_id: str
    show_id: str
    listing_id: str
    start_seq: int
    end_seq: Optional[int]


class OperationReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    receipt_id: str
    operation_id: str
    operation_type: OperationType
    status: Literal["applied", "rejected", "failed"]
    actor_type: Literal["seller"]
    actor_id: str
    seller_id: str
    show_id: str
    listing_id: Optional[str] = None
    variant_id: Optional[str] = None
    request: Dict[str, Any]
    before: Dict[str, Any]
    after: Dict[str, Any]
    expected_versions: Dict[str, int]
    resulting_versions: Dict[str, int]
    authorization_verdict: Literal["authorized"]
    policy_verdict: Literal["allowed", "rejected", "not_executed"]
    idempotency_key: str
    compensation_for_receipt_id: Optional[str] = None
    requested_at: str
    executed_at: Optional[str] = None
    recorded_at: str
    duration_ms: float
    error_code: Optional[str] = None


@runtime_checkable
class MarketplacePort(Protocol):
    """The minimal write boundary a future marketplace adapter must implement."""

    def push(
        self,
        authority: SellerAuthority,
        request: PushRequest,
        *,
        idempotency_key: str,
    ) -> OperationReceipt: ...

    def swap(
        self,
        authority: SellerAuthority,
        request: SwapRequest,
        *,
        idempotency_key: str,
    ) -> OperationReceipt: ...

    def unlist(
        self,
        authority: SellerAuthority,
        request: UnlistRequest,
        *,
        idempotency_key: str,
    ) -> OperationReceipt: ...

    def price_markdown(
        self,
        authority: SellerAuthority,
        request: PriceMarkdownRequest,
        *,
        idempotency_key: str,
    ) -> OperationReceipt: ...

    def inventory_change(
        self,
        authority: SellerAuthority,
        request: InventoryChangeRequest,
        *,
        idempotency_key: str,
    ) -> OperationReceipt: ...

    def compensate(
        self,
        authority: SellerAuthority,
        receipt_id: str,
        *,
        idempotency_key: str,
    ) -> OperationReceipt: ...


class MarketplaceAuthorityError(PermissionError):
    pass


class AuditPersistenceError(RuntimeError):
    pass


class _Rejected(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


class _InjectedFailure(Exception):
    def __init__(self, stage: str) -> None:
        self.stage = stage


Effect = Callable[[sqlite3.Connection, SellerAuthority], Tuple[Optional[str], Optional[str]]]


class MarketplaceService:
    """The application-owned authorization and audit boundary for all five writes."""

    def __init__(self, database: MarketplaceDatabase) -> None:
        self.database = database
        self._failure_lock = Lock()
        self._next_failure: Optional[str] = None

    def fail_next(self, stage: str) -> None:
        if stage not in {"before_effect", "after_effect", "verification", "before_receipt"}:
            raise ValueError(f"unknown failure stage: {stage}")
        with self._failure_lock:
            self._next_failure = stage

    def push(
        self,
        authority: SellerAuthority,
        request: PushRequest,
        *,
        idempotency_key: str,
    ) -> OperationReceipt:
        return self._execute(
            authority,
            OperationType.PUSH,
            request.model_dump(),
            idempotency_key,
            lambda connection, auth: self._apply_push(connection, auth, request),
        )

    def swap(
        self,
        authority: SellerAuthority,
        request: SwapRequest,
        *,
        idempotency_key: str,
    ) -> OperationReceipt:
        return self._execute(
            authority,
            OperationType.SWAP,
            request.model_dump(),
            idempotency_key,
            lambda connection, auth: self._apply_swap(connection, auth, request),
        )

    def unlist(
        self,
        authority: SellerAuthority,
        request: UnlistRequest,
        *,
        idempotency_key: str,
    ) -> OperationReceipt:
        return self._execute(
            authority,
            OperationType.UNLIST,
            request.model_dump(),
            idempotency_key,
            lambda connection, auth: self._apply_unlist(connection, auth, request),
        )

    def price_markdown(
        self,
        authority: SellerAuthority,
        request: PriceMarkdownRequest,
        *,
        idempotency_key: str,
    ) -> OperationReceipt:
        return self._execute(
            authority,
            OperationType.PRICE_MARKDOWN,
            request.model_dump(),
            idempotency_key,
            lambda connection, auth: self._apply_markdown(connection, auth, request),
        )

    def inventory_change(
        self,
        authority: SellerAuthority,
        request: InventoryChangeRequest,
        *,
        idempotency_key: str,
    ) -> OperationReceipt:
        return self._execute(
            authority,
            OperationType.INVENTORY_CHANGE,
            request.model_dump(),
            idempotency_key,
            lambda connection, auth: self._apply_inventory(connection, auth, request),
        )

    def compensate(
        self,
        authority: SellerAuthority,
        receipt_id: str,
        *,
        idempotency_key: str,
    ) -> OperationReceipt:
        self._validate_authority_type(authority)
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT * FROM operation_receipts WHERE receipt_id = ? AND seller_id = ? AND show_id = ?",
                (receipt_id, authority.seller_id, authority.show_id),
            ).fetchone()
        if row is None:
            raise ValueError("unknown compensable receipt")
        original = self._receipt_from_row(row)
        if original.status != "applied" or original.compensation_for_receipt_id is not None:
            raise ValueError("only an applied original operation can be compensated")

        return self._execute(
            authority,
            original.operation_type,
            {"receipt_id": receipt_id},
            idempotency_key,
            lambda connection, auth: self._apply_compensation(connection, auth, original),
            compensation_for_receipt_id=receipt_id,
            snapshot_listing_id=original.listing_id,
            snapshot_variant_id=original.variant_id,
        )

    def show_state(self, show_id: str) -> ShowState:
        with self.database.read() as connection:
            row = connection.execute("SELECT * FROM shows WHERE show_id = ?", (show_id,)).fetchone()
        if row is None:
            raise KeyError(show_id)
        return ShowState.model_validate(dict(row))

    def listing_state(self, listing_id: str) -> ListingState:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT * FROM listings WHERE listing_id = ?", (listing_id,)
            ).fetchone()
        if row is None:
            raise KeyError(listing_id)
        return ListingState.model_validate(dict(row))

    def inventory_state(self, variant_id: str) -> InventoryState:
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT * FROM inventory WHERE variant_id = ?", (variant_id,)
            ).fetchone()
        if row is None:
            raise KeyError(variant_id)
        return InventoryState.model_validate(dict(row))

    def epochs(self, show_id: str) -> Tuple[ListingEpoch, ...]:
        with self.database.read() as connection:
            rows = connection.execute(
                """SELECT epoch_id, seller_id, show_id, listing_id, start_seq, end_seq
                   FROM listing_epochs WHERE show_id = ? ORDER BY epoch_number""",
                (show_id,),
            ).fetchall()
        return tuple(ListingEpoch.model_validate(dict(row)) for row in rows)

    def receipts(self, show_id: str) -> Tuple[OperationReceipt, ...]:
        with self.database.read() as connection:
            rows = connection.execute(
                "SELECT * FROM operation_receipts WHERE show_id = ? ORDER BY row_number",
                (show_id,),
            ).fetchall()
        return tuple(self._receipt_from_row(row) for row in rows)

    def _execute(
        self,
        authority: SellerAuthority,
        operation_type: OperationType,
        request: Dict[str, Any],
        idempotency_key: str,
        effect: Effect,
        *,
        compensation_for_receipt_id: Optional[str] = None,
        snapshot_listing_id: Optional[str] = None,
        snapshot_variant_id: Optional[str] = None,
    ) -> OperationReceipt:
        self._validate_authority_type(authority)
        if not idempotency_key.strip():
            raise ValueError("idempotency key must not be empty")

        fingerprint = self._fingerprint(
            authority,
            operation_type,
            request,
            compensation_for_receipt_id,
        )
        requested_at = _utc_millis()
        started = time.monotonic()
        try:
            with self.database.transaction() as connection:
                self._require_authority(connection, authority)
                prior = connection.execute(
                    """SELECT request_fingerprint, receipt_id FROM idempotency_registry
                       WHERE seller_id = ? AND show_id = ? AND idempotency_key = ?""",
                    (authority.seller_id, authority.show_id, idempotency_key),
                ).fetchone()
                if prior is not None and prior["request_fingerprint"] == fingerprint:
                    row = connection.execute(
                        "SELECT * FROM operation_receipts WHERE receipt_id = ?",
                        (prior["receipt_id"],),
                    ).fetchone()
                    return self._receipt_from_row(row)

                before = self._snapshot(
                    connection,
                    authority,
                    request,
                    snapshot_listing_id,
                    snapshot_variant_id,
                )
                expected_versions = _expected_versions(request)
                executed_at: Optional[str] = None
                listing_id = _request_listing_id(request)
                variant_id = request.get("variant_id")

                if prior is not None:
                    receipt = self._make_receipt(
                        authority=authority,
                        operation_type=operation_type,
                        request=request,
                        before=before,
                        after=before,
                        expected_versions=expected_versions,
                        resulting_versions=_state_versions(before),
                        status="rejected",
                        policy_verdict="not_executed",
                        idempotency_key=idempotency_key,
                        requested_at=requested_at,
                        executed_at=None,
                        started=started,
                        error_code="idempotency_conflict",
                        listing_id=listing_id,
                        variant_id=variant_id,
                        compensation_for_receipt_id=compensation_for_receipt_id,
                    )
                    self._insert_receipt(connection, receipt)
                    return receipt

                connection.execute("SAVEPOINT marketplace_effect")
                try:
                    self._inject("before_effect")
                    executed_at = _utc_millis()
                    listing_id, variant_id = effect(connection, authority)
                    self._inject("after_effect")
                    after = self._snapshot(connection, authority, request, listing_id, variant_id)
                    self._inject("verification")
                    self._verify_effect(
                        operation_type,
                        request,
                        before,
                        after,
                        compensation_for_receipt_id,
                    )
                except _Rejected as error:
                    connection.execute("ROLLBACK TO marketplace_effect")
                    connection.execute("RELEASE marketplace_effect")
                    status: Literal["applied", "rejected", "failed"] = "rejected"
                    error_code = error.code
                    policy_verdict: Literal["allowed", "rejected", "not_executed"] = "rejected"
                    after = self._snapshot(connection, authority, request)
                except _InjectedFailure as error:
                    connection.execute("ROLLBACK TO marketplace_effect")
                    connection.execute("RELEASE marketplace_effect")
                    status = "failed"
                    error_code = f"injected_{error.stage}"
                    policy_verdict = "not_executed"
                    after = self._snapshot(connection, authority, request)
                else:
                    connection.execute("RELEASE marketplace_effect")
                    status = "applied"
                    error_code = None
                    policy_verdict = "allowed"

                receipt = self._make_receipt(
                    authority=authority,
                    operation_type=operation_type,
                    request=request,
                    before=before,
                    after=after,
                    expected_versions=expected_versions,
                    resulting_versions=_state_versions(after),
                    status=status,
                    policy_verdict=policy_verdict,
                    idempotency_key=idempotency_key,
                    requested_at=requested_at,
                    executed_at=executed_at,
                    started=started,
                    error_code=error_code,
                    listing_id=listing_id,
                    variant_id=variant_id,
                    compensation_for_receipt_id=compensation_for_receipt_id,
                )
                self._inject("before_receipt")
                self._insert_receipt(connection, receipt)
                connection.execute(
                    """INSERT INTO idempotency_registry(
                           seller_id, show_id, idempotency_key, request_fingerprint, receipt_id
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        authority.seller_id,
                        authority.show_id,
                        idempotency_key,
                        fingerprint,
                        receipt.receipt_id,
                    ),
                )
                return receipt
        except _InjectedFailure as error:
            if error.stage == "before_receipt":
                raise AuditPersistenceError("receipt persistence failed; effect rolled back") from error
            raise
        except sqlite3.Error as error:
            raise AuditPersistenceError("marketplace transaction could not be persisted") from error

    def _apply_push(
        self, connection: sqlite3.Connection, authority: SellerAuthority, request: PushRequest
    ) -> Tuple[str, None]:
        show = self._show_row(connection, authority.show_id)
        self._expect_show_version(show, request.expected_show_version)
        if show["active_listing_id"] is not None:
            raise _Rejected("active_slot_not_empty")
        self._require_activatable(connection, authority, request.target_listing_id)
        seq = int(show["show_seq"]) + 1
        connection.execute(
            "UPDATE shows SET active_listing_id = ?, version = version + 1, show_seq = ? WHERE show_id = ?",
            (request.target_listing_id, seq, authority.show_id),
        )
        self._open_epoch(connection, authority, request.target_listing_id, seq)
        return request.target_listing_id, None

    def _apply_swap(
        self, connection: sqlite3.Connection, authority: SellerAuthority, request: SwapRequest
    ) -> Tuple[str, None]:
        show = self._show_row(connection, authority.show_id)
        self._expect_show_version(show, request.expected_show_version)
        if show["active_listing_id"] is None:
            raise _Rejected("active_slot_empty")
        if show["active_listing_id"] != request.expected_active_listing_id:
            raise _Rejected("stale_active_listing")
        if request.target_listing_id == show["active_listing_id"]:
            raise _Rejected("swap_target_is_active")
        self._require_activatable(connection, authority, request.target_listing_id)
        seq = int(show["show_seq"]) + 1
        self._close_epoch(connection, authority.show_id, seq)
        connection.execute(
            "UPDATE shows SET active_listing_id = ?, version = version + 1, show_seq = ? WHERE show_id = ?",
            (request.target_listing_id, seq, authority.show_id),
        )
        self._open_epoch(connection, authority, request.target_listing_id, seq)
        return request.target_listing_id, None

    def _apply_unlist(
        self, connection: sqlite3.Connection, authority: SellerAuthority, request: UnlistRequest
    ) -> Tuple[str, None]:
        show = self._show_row(connection, authority.show_id)
        self._expect_show_version(show, request.expected_show_version)
        if show["active_listing_id"] is None:
            raise _Rejected("active_slot_empty")
        if show["active_listing_id"] != request.expected_active_listing_id:
            raise _Rejected("stale_active_listing")
        listing = self._scoped_listing(connection, authority, request.expected_active_listing_id)
        seq = int(show["show_seq"]) + 1
        connection.execute(
            "UPDATE listings SET status = 'unlisted', version = version + 1 WHERE listing_id = ?",
            (listing["listing_id"],),
        )
        self._close_epoch(connection, authority.show_id, seq)
        connection.execute(
            "UPDATE shows SET active_listing_id = NULL, version = version + 1, show_seq = ? WHERE show_id = ?",
            (seq, authority.show_id),
        )
        return str(listing["listing_id"]), None

    def _apply_markdown(
        self,
        connection: sqlite3.Connection,
        authority: SellerAuthority,
        request: PriceMarkdownRequest,
    ) -> Tuple[str, None]:
        show = self._show_row(connection, authority.show_id)
        if show["active_listing_id"] != request.listing_id:
            raise _Rejected("listing_not_active")
        listing = self._scoped_listing(connection, authority, request.listing_id)
        if listing["version"] != request.expected_listing_version:
            raise _Rejected("stale_listing_version")
        if request.new_price_cents >= listing["price_cents"]:
            raise _Rejected("markdown_must_lower_price")
        if request.new_price_cents < listing["floor_price_cents"]:
            raise _Rejected("below_price_floor")
        connection.execute(
            "UPDATE listings SET price_cents = ?, version = version + 1 WHERE listing_id = ?",
            (request.new_price_cents, request.listing_id),
        )
        connection.execute(
            "UPDATE shows SET show_seq = show_seq + 1 WHERE show_id = ?",
            (authority.show_id,),
        )
        return request.listing_id, None

    def _apply_inventory(
        self,
        connection: sqlite3.Connection,
        authority: SellerAuthority,
        request: InventoryChangeRequest,
    ) -> Tuple[str, str]:
        show = self._show_row(connection, authority.show_id)
        if show["active_listing_id"] != request.listing_id:
            raise _Rejected("listing_not_active")
        self._scoped_listing(connection, authority, request.listing_id)
        inventory = self._scoped_inventory(connection, authority, request.variant_id)
        if inventory["listing_id"] != request.listing_id:
            raise _Rejected("variant_not_in_listing")
        if inventory["version"] != request.expected_inventory_version:
            raise _Rejected("stale_inventory_version")
        connection.execute(
            """UPDATE inventory SET available_quantity = ?, version = version + 1
               WHERE variant_id = ?""",
            (request.new_available_quantity, request.variant_id),
        )
        connection.execute(
            "UPDATE shows SET show_seq = show_seq + 1 WHERE show_id = ?",
            (authority.show_id,),
        )
        return request.listing_id, request.variant_id

    def _apply_compensation(
        self,
        connection: sqlite3.Connection,
        authority: SellerAuthority,
        original: OperationReceipt,
    ) -> Tuple[Optional[str], Optional[str]]:
        before = original.before
        after = original.after
        operation = original.operation_type
        show = self._show_row(connection, authority.show_id)

        if operation in {OperationType.PUSH, OperationType.SWAP, OperationType.UNLIST}:
            expected_show = after["show"]
            if (
                show["version"] != expected_show["version"]
                or show["active_listing_id"] != expected_show["active_listing_id"]
            ):
                raise _Rejected("stale_compensation")

        if operation == OperationType.PUSH:
            seq = int(show["show_seq"]) + 1
            self._close_epoch(connection, authority.show_id, seq)
            connection.execute(
                "UPDATE shows SET active_listing_id = NULL, version = version + 1, show_seq = ? WHERE show_id = ?",
                (seq, authority.show_id),
            )
            return original.listing_id, None

        if operation == OperationType.SWAP:
            previous = before["show"]["active_listing_id"]
            seq = int(show["show_seq"]) + 1
            self._close_epoch(connection, authority.show_id, seq)
            connection.execute(
                "UPDATE shows SET active_listing_id = ?, version = version + 1, show_seq = ? WHERE show_id = ?",
                (previous, seq, authority.show_id),
            )
            self._open_epoch(connection, authority, previous, seq)
            return previous, None

        if operation == OperationType.UNLIST:
            listing_id = original.listing_id
            current = self._scoped_listing(connection, authority, listing_id)
            expected_listing = after["listing"]
            if current["version"] != expected_listing["version"] or current["status"] != "unlisted":
                raise _Rejected("stale_compensation")
            seq = int(show["show_seq"]) + 1
            connection.execute(
                "UPDATE listings SET status = 'available', version = version + 1 WHERE listing_id = ?",
                (listing_id,),
            )
            connection.execute(
                "UPDATE shows SET active_listing_id = ?, version = version + 1, show_seq = ? WHERE show_id = ?",
                (listing_id, seq, authority.show_id),
            )
            self._open_epoch(connection, authority, listing_id, seq)
            return listing_id, None

        if operation == OperationType.PRICE_MARKDOWN:
            listing_id = original.listing_id
            current = self._scoped_listing(connection, authority, listing_id)
            if (
                current["version"] != after["listing"]["version"]
                or current["price_cents"] != after["listing"]["price_cents"]
            ):
                raise _Rejected("stale_compensation")
            connection.execute(
                "UPDATE listings SET price_cents = ?, version = version + 1 WHERE listing_id = ?",
                (before["listing"]["price_cents"], listing_id),
            )
            connection.execute(
                "UPDATE shows SET show_seq = show_seq + 1 WHERE show_id = ?",
                (authority.show_id,),
            )
            return listing_id, None

        if operation == OperationType.INVENTORY_CHANGE:
            variant_id = original.variant_id
            current = self._scoped_inventory(connection, authority, variant_id)
            if (
                current["version"] != after["inventory"]["version"]
                or current["available_quantity"] != after["inventory"]["available_quantity"]
            ):
                raise _Rejected("stale_compensation")
            connection.execute(
                """UPDATE inventory SET available_quantity = ?, version = version + 1
                   WHERE variant_id = ?""",
                (before["inventory"]["available_quantity"], variant_id),
            )
            connection.execute(
                "UPDATE shows SET show_seq = show_seq + 1 WHERE show_id = ?",
                (authority.show_id,),
            )
            return original.listing_id, variant_id

        raise _Rejected("unsupported_compensation")

    def _snapshot(
        self,
        connection: sqlite3.Connection,
        authority: SellerAuthority,
        request: Mapping[str, Any],
        listing_id: Optional[str] = None,
        variant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        show = dict(self._show_row(connection, authority.show_id))
        snapshot: Dict[str, Any] = {"show": show}
        candidate_listing = listing_id or _request_listing_id(request)
        if candidate_listing:
            row = connection.execute(
                "SELECT * FROM listings WHERE listing_id = ? AND seller_id = ?",
                (candidate_listing, authority.seller_id),
            ).fetchone()
            if row is not None:
                snapshot["listing"] = dict(row)
        candidate_variant = variant_id or request.get("variant_id")
        if candidate_variant:
            row = connection.execute(
                "SELECT * FROM inventory WHERE variant_id = ? AND seller_id = ?",
                (candidate_variant, authority.seller_id),
            ).fetchone()
            if row is not None:
                snapshot["inventory"] = dict(row)
        return snapshot

    def _verify_effect(
        self,
        operation_type: OperationType,
        request: Mapping[str, Any],
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        compensation_for_receipt_id: Optional[str],
    ) -> None:
        if before == after:
            raise _InjectedFailure("verification")
        if compensation_for_receipt_id is None:
            if operation_type in {OperationType.PUSH, OperationType.SWAP}:
                if after["show"]["version"] != before["show"]["version"] + 1:
                    raise _InjectedFailure("verification")
                if after["show"]["active_listing_id"] != request["target_listing_id"]:
                    raise _InjectedFailure("verification")
            elif operation_type == OperationType.UNLIST:
                if after["show"]["version"] != before["show"]["version"] + 1:
                    raise _InjectedFailure("verification")
                if after["show"]["active_listing_id"] is not None:
                    raise _InjectedFailure("verification")
                if after["listing"]["status"] != "unlisted":
                    raise _InjectedFailure("verification")
            elif operation_type == OperationType.PRICE_MARKDOWN:
                if after["listing"]["version"] != before["listing"]["version"] + 1:
                    raise _InjectedFailure("verification")
                if after["listing"]["price_cents"] != request["new_price_cents"]:
                    raise _InjectedFailure("verification")
            elif operation_type == OperationType.INVENTORY_CHANGE:
                if after["inventory"]["version"] != before["inventory"]["version"] + 1:
                    raise _InjectedFailure("verification")
                if (
                    after["inventory"]["available_quantity"]
                    != request["new_available_quantity"]
                ):
                    raise _InjectedFailure("verification")

    def _require_authority(
        self, connection: sqlite3.Connection, authority: SellerAuthority
    ) -> None:
        row = connection.execute(
            "SELECT seller_id FROM shows WHERE show_id = ?", (authority.show_id,)
        ).fetchone()
        if row is None or row["seller_id"] != authority.seller_id:
            raise MarketplaceAuthorityError("seller is not authorized for this show")

    @staticmethod
    def _validate_authority_type(authority: SellerAuthority) -> None:
        if not isinstance(authority, SellerAuthority):
            raise TypeError("trusted SellerAuthority is required")

    @staticmethod
    def _show_row(connection: sqlite3.Connection, show_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM shows WHERE show_id = ?", (show_id,)).fetchone()
        if row is None:
            raise MarketplaceAuthorityError("unknown show")
        return row

    @staticmethod
    def _expect_show_version(show: sqlite3.Row, expected: int) -> None:
        if show["version"] != expected:
            raise _Rejected("stale_show_version")

    @staticmethod
    def _scoped_listing(
        connection: sqlite3.Connection, authority: SellerAuthority, listing_id: Optional[str]
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM listings WHERE listing_id = ? AND seller_id = ?",
            (listing_id, authority.seller_id),
        ).fetchone()
        if row is None:
            raise _Rejected("listing_not_in_scope")
        return row

    @staticmethod
    def _scoped_inventory(
        connection: sqlite3.Connection, authority: SellerAuthority, variant_id: Optional[str]
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM inventory WHERE variant_id = ? AND seller_id = ?",
            (variant_id, authority.seller_id),
        ).fetchone()
        if row is None:
            raise _Rejected("variant_not_in_scope")
        return row

    def _require_activatable(
        self, connection: sqlite3.Connection, authority: SellerAuthority, listing_id: str
    ) -> None:
        listing = self._scoped_listing(connection, authority, listing_id)
        if listing["status"] != "available":
            raise _Rejected("listing_unavailable")
        units = connection.execute(
            "SELECT COALESCE(SUM(available_quantity), 0) FROM inventory WHERE listing_id = ?",
            (listing_id,),
        ).fetchone()[0]
        if units <= 0:
            raise _Rejected("listing_out_of_stock")

    @staticmethod
    def _open_epoch(
        connection: sqlite3.Connection,
        authority: SellerAuthority,
        listing_id: str,
        start_seq: int,
    ) -> None:
        cursor = connection.execute(
            """INSERT INTO listing_epochs(
                   epoch_id, seller_id, show_id, listing_id, start_seq, end_seq
               ) VALUES (NULL, ?, ?, ?, ?, NULL)""",
            (authority.seller_id, authority.show_id, listing_id, start_seq),
        )
        epoch_id = f"epc_{cursor.lastrowid}"
        connection.execute(
            "UPDATE listing_epochs SET epoch_id = ? WHERE epoch_number = ?",
            (epoch_id, cursor.lastrowid),
        )

    @staticmethod
    def _close_epoch(connection: sqlite3.Connection, show_id: str, end_seq: int) -> None:
        changed = connection.execute(
            "UPDATE listing_epochs SET end_seq = ? WHERE show_id = ? AND end_seq IS NULL",
            (end_seq, show_id),
        ).rowcount
        if changed != 1:
            raise _InjectedFailure("verification")

    def _inject(self, stage: str) -> None:
        with self._failure_lock:
            if self._next_failure == stage:
                self._next_failure = None
                raise _InjectedFailure(stage)

    @staticmethod
    def _fingerprint(
        authority: SellerAuthority,
        operation_type: OperationType,
        request: Mapping[str, Any],
        compensation_for_receipt_id: Optional[str],
    ) -> str:
        body = {
            "operation_type": operation_type.value,
            "request": request,
            "compensation_for_receipt_id": compensation_for_receipt_id,
            "actor_type": authority.actor_type,
            "actor_id": authority.actor_id,
        }
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _make_receipt(
        self,
        *,
        authority: SellerAuthority,
        operation_type: OperationType,
        request: Dict[str, Any],
        before: Dict[str, Any],
        after: Dict[str, Any],
        expected_versions: Dict[str, int],
        resulting_versions: Dict[str, int],
        status: Literal["applied", "rejected", "failed"],
        policy_verdict: Literal["allowed", "rejected", "not_executed"],
        idempotency_key: str,
        requested_at: str,
        executed_at: Optional[str],
        started: float,
        error_code: Optional[str],
        listing_id: Optional[str],
        variant_id: Optional[str],
        compensation_for_receipt_id: Optional[str],
    ) -> OperationReceipt:
        return OperationReceipt(
            receipt_id=f"rcpt_{uuid4().hex}",
            operation_id=f"op_{uuid4().hex}",
            operation_type=operation_type,
            status=status,
            actor_type=authority.actor_type,
            actor_id=authority.actor_id,
            seller_id=authority.seller_id,
            show_id=authority.show_id,
            listing_id=listing_id,
            variant_id=variant_id,
            request=request,
            before=before,
            after=after,
            expected_versions=expected_versions,
            resulting_versions=resulting_versions,
            authorization_verdict="authorized",
            policy_verdict=policy_verdict,
            idempotency_key=idempotency_key,
            compensation_for_receipt_id=compensation_for_receipt_id,
            requested_at=requested_at,
            executed_at=executed_at,
            recorded_at=_utc_millis(),
            duration_ms=max(0.0, (time.monotonic() - started) * 1000),
            error_code=error_code,
        )

    @staticmethod
    def _insert_receipt(connection: sqlite3.Connection, receipt: OperationReceipt) -> None:
        payload = receipt.model_dump(mode="json")
        connection.execute(
            """INSERT INTO operation_receipts(
                   receipt_id, operation_id, operation_type, status, actor_type, actor_id,
                   seller_id, show_id, listing_id, variant_id, request_json, before_json,
                   after_json, expected_versions_json, resulting_versions_json,
                   authorization_verdict, policy_verdict, idempotency_key,
                   compensation_for_receipt_id, requested_at, executed_at, recorded_at,
                   duration_ms, error_code
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload["receipt_id"], payload["operation_id"], payload["operation_type"],
                payload["status"], payload["actor_type"], payload["actor_id"],
                payload["seller_id"], payload["show_id"], payload["listing_id"],
                payload["variant_id"], json.dumps(payload["request"], sort_keys=True),
                json.dumps(payload["before"], sort_keys=True),
                json.dumps(payload["after"], sort_keys=True),
                json.dumps(payload["expected_versions"], sort_keys=True),
                json.dumps(payload["resulting_versions"], sort_keys=True),
                payload["authorization_verdict"], payload["policy_verdict"],
                payload["idempotency_key"], payload["compensation_for_receipt_id"],
                payload["requested_at"], payload["executed_at"], payload["recorded_at"],
                payload["duration_ms"], payload["error_code"],
            ),
        )

    @staticmethod
    def _receipt_from_row(row: sqlite3.Row) -> OperationReceipt:
        return OperationReceipt(
            receipt_id=row["receipt_id"],
            operation_id=row["operation_id"],
            operation_type=row["operation_type"],
            status=row["status"],
            actor_type=row["actor_type"],
            actor_id=row["actor_id"],
            seller_id=row["seller_id"],
            show_id=row["show_id"],
            listing_id=row["listing_id"],
            variant_id=row["variant_id"],
            request=json.loads(row["request_json"]),
            before=json.loads(row["before_json"]),
            after=json.loads(row["after_json"]),
            expected_versions=json.loads(row["expected_versions_json"]),
            resulting_versions=json.loads(row["resulting_versions_json"]),
            authorization_verdict=row["authorization_verdict"],
            policy_verdict=row["policy_verdict"],
            idempotency_key=row["idempotency_key"],
            compensation_for_receipt_id=row["compensation_for_receipt_id"],
            requested_at=row["requested_at"],
            executed_at=row["executed_at"],
            recorded_at=row["recorded_at"],
            duration_ms=row["duration_ms"],
            error_code=row["error_code"],
        )


def _request_listing_id(request: Mapping[str, Any]) -> Optional[str]:
    value = (
        request.get("listing_id")
        or request.get("target_listing_id")
        or request.get("expected_active_listing_id")
    )
    return str(value) if value is not None else None


def _expected_versions(request: Mapping[str, Any]) -> Dict[str, int]:
    return {
        key: int(value)
        for key, value in request.items()
        if key.startswith("expected_") and key.endswith("_version")
    }


def _state_versions(snapshot: Mapping[str, Any]) -> Dict[str, int]:
    versions: Dict[str, int] = {}
    for key in ("show", "listing", "inventory"):
        state = snapshot.get(key)
        if isinstance(state, Mapping) and "version" in state:
            versions[f"{key}_version"] = int(state["version"])
    return versions


def _utc_millis() -> str:
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
