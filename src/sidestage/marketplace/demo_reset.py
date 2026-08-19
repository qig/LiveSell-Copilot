"""Developer-only authority and concurrency boundary for synthetic demo reset."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Callable

from sidestage.fixtures.loader import SellerCatalog
from sidestage.marketplace.authority import SellerAuthority
from sidestage.storage.database import MarketplaceDatabase
from sidestage.streaming.hub import StreamEventStore


@dataclass
class _ShowGate:
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    active_mutations: int = 0
    reset_pending: bool = False


class DemoMutationGate:
    """Allow concurrent normal mutations while giving reset exclusive access."""

    def __init__(self) -> None:
        self._shows: dict[tuple[str, str], _ShowGate] = {}

    @asynccontextmanager
    async def mutation(self, authority: SellerAuthority) -> AsyncIterator[None]:
        state = self._state(authority)
        async with state.condition:
            while state.reset_pending:
                await state.condition.wait()
            state.active_mutations += 1
        try:
            yield
        finally:
            async with state.condition:
                state.active_mutations -= 1
                state.condition.notify_all()

    @asynccontextmanager
    async def reset(self, authority: SellerAuthority) -> AsyncIterator[None]:
        state = self._state(authority)
        async with state.condition:
            while state.reset_pending:
                await state.condition.wait()
            state.reset_pending = True
            while state.active_mutations:
                await state.condition.wait()
        try:
            yield
        finally:
            async with state.condition:
                state.reset_pending = False
                state.condition.notify_all()

    def _state(self, authority: SellerAuthority) -> _ShowGate:
        key = (authority.seller_id, authority.show_id)
        state = self._shows.get(key)
        if state is None:
            state = _ShowGate()
            self._shows[key] = state
        return state


class DemoResetService:
    """Restore one authenticated synthetic seller/show to fixture-visible state."""

    def __init__(
        self,
        database: MarketplaceDatabase,
        catalog: SellerCatalog,
        stream_store: StreamEventStore,
        *,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.database = database
        self.catalog = catalog
        self.stream_store = stream_store
        self.wall_clock = wall_clock

    def reset(self, authority: SellerAuthority) -> dict:
        seller = self.catalog.seller(authority.seller_id)
        reset_at = _utc_millis(self.wall_clock())
        with self.database.transaction() as connection:
            show = connection.execute(
                "SELECT * FROM shows WHERE show_id = ? AND seller_id = ?",
                (authority.show_id, authority.seller_id),
            ).fetchone()
            if show is None:
                raise KeyError("unknown seller show")

            question_scope = (
                "SELECT question_id FROM copilot_questions "
                "WHERE seller_id = ? AND show_id = ?"
            )
            event_scope = (
                "SELECT event_id FROM chat_events WHERE seller_id = ? AND show_id = ?"
            )
            trace_scope = (
                "SELECT trace_id FROM chat_events WHERE seller_id = ? AND show_id = ?"
            )
            scope = (authority.seller_id, authority.show_id)

            connection.execute(
                "DELETE FROM copilot_reply_idempotency WHERE seller_id = ? AND show_id = ?",
                scope,
            )
            connection.execute(
                "DELETE FROM copilot_reply_receipts WHERE seller_id = ? AND show_id = ?",
                scope,
            )
            connection.execute(
                "DELETE FROM copilot_outbound_replies WHERE seller_id = ? AND show_id = ?",
                scope,
            )
            connection.execute(
                "DELETE FROM copilot_suggestions WHERE seller_id = ? AND show_id = ?",
                scope,
            )
            connection.execute(
                f"DELETE FROM copilot_question_transitions WHERE question_id IN ({question_scope})",
                scope,
            )
            connection.execute(
                f"DELETE FROM copilot_trace_oracle_labels WHERE event_id IN ({event_scope})",
                scope,
            )
            connection.execute(
                f"DELETE FROM copilot_trace_artifacts WHERE trace_id IN ({trace_scope})",
                scope,
            )
            connection.execute(
                "DELETE FROM copilot_trace_observations "
                "WHERE seller_id = ? AND show_id = ?",
                scope,
            )
            connection.execute(
                "DELETE FROM copilot_questions WHERE seller_id = ? AND show_id = ?",
                scope,
            )
            connection.execute(
                "DELETE FROM chat_events WHERE seller_id = ? AND show_id = ?",
                scope,
            )
            connection.execute(
                "DELETE FROM stream_events WHERE seller_id = ? AND show_id = ?",
                scope,
            )
            connection.execute(
                "DELETE FROM idempotency_registry WHERE seller_id = ? AND show_id = ?",
                scope,
            )
            connection.execute(
                "DELETE FROM operation_receipts WHERE seller_id = ? AND show_id = ?",
                scope,
            )
            connection.execute(
                "DELETE FROM listing_epochs WHERE seller_id = ? AND show_id = ?",
                scope,
            )

            for product in seller.products:
                listing = product.listing
                connection.execute(
                    """UPDATE listings
                       SET price_cents = ?, floor_price_cents = ?, status = ?,
                           version = version + 1
                       WHERE listing_id = ? AND seller_id = ?""",
                    (
                        listing.price_cents,
                        listing.floor_price_cents,
                        listing.status,
                        listing.listing_id,
                        authority.seller_id,
                    ),
                )
                for variant in product.variants:
                    connection.execute(
                        """UPDATE inventory
                           SET available_quantity = ?, version = version + 1
                           WHERE variant_id = ? AND listing_id = ? AND seller_id = ?""",
                        (
                            variant.available_quantity,
                            variant.variant_id,
                            listing.listing_id,
                            authority.seller_id,
                        ),
                    )

            connection.execute(
                """UPDATE shows
                   SET active_listing_id = NULL, version = version + 1, show_seq = 0
                   WHERE show_id = ? AND seller_id = ?""",
                (authority.show_id, authority.seller_id),
            )
            connection.execute(
                """UPDATE copilot_r3_capabilities
                   SET enabled = 0, version = version + 1,
                       updated_by = ?, updated_at = ?
                   WHERE show_id = ? AND seller_id = ?""",
                (authority.actor_id, reset_at, authority.show_id, authority.seller_id),
            )
            offset = self.stream_store.append(
                seller_id=authority.seller_id,
                show_id=authority.show_id,
                event_type="demo.reset",
                payload={"reset_at": reset_at, "actor_id": authority.actor_id},
                connection=connection,
                created_at=reset_at,
            )
        return {"reset_at": reset_at, "stream_offset": offset}


def _utc_millis(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("reset wall clock must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
