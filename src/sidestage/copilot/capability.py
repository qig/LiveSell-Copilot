"""Versioned per-show authorization for bounded R3 automatic replies."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field

from sidestage.marketplace.authority import SellerAuthority
from sidestage.storage.database import MarketplaceDatabase
from sidestage.streaming.hub import SseHub, StreamEventStore


class R3CapabilityChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    enabled: bool
    expected_version: int = Field(strict=True, gt=0)


class R3Capability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    seller_id: str
    show_id: str
    enabled: bool
    version: int = Field(strict=True, gt=0)
    updated_by: str
    updated_at: str


class R3CapabilityService:
    def __init__(
        self,
        database: MarketplaceDatabase,
        stream_store: StreamEventStore,
        hub: SseHub,
        *,
        wall_clock: Callable[[], datetime],
    ) -> None:
        self.database = database
        self.stream_store = stream_store
        self.hub = hub
        self.wall_clock = wall_clock

    def get(self, authority: SellerAuthority) -> R3Capability:
        with self.database.read() as connection:
            row = connection.execute(
                """SELECT * FROM copilot_r3_capabilities
                   WHERE seller_id = ? AND show_id = ?""",
                (authority.seller_id, authority.show_id),
            ).fetchone()
        if row is None:
            raise KeyError("R3 capability is not in the authenticated seller scope")
        return _from_row(row)

    async def change(
        self,
        authority: SellerAuthority,
        request: R3CapabilityChangeRequest,
    ) -> R3Capability:
        changed_at = _utc_text(self.wall_clock())
        with self.database.transaction() as connection:
            row = connection.execute(
                """SELECT * FROM copilot_r3_capabilities
                   WHERE seller_id = ? AND show_id = ?""",
                (authority.seller_id, authority.show_id),
            ).fetchone()
            if row is None:
                raise KeyError("R3 capability is not in the authenticated seller scope")
            if int(row["version"]) != request.expected_version:
                raise ValueError("stale R3 capability version")
            version = int(row["version"]) + 1
            connection.execute(
                """UPDATE copilot_r3_capabilities
                   SET enabled = ?, version = ?, updated_by = ?, updated_at = ?
                   WHERE seller_id = ? AND show_id = ?""",
                (
                    int(request.enabled),
                    version,
                    authority.actor_id,
                    changed_at,
                    authority.seller_id,
                    authority.show_id,
                ),
            )
            payload = {
                "enabled": request.enabled,
                "version": version,
            }
            self.stream_store.append(
                seller_id=authority.seller_id,
                show_id=authority.show_id,
                event_type="copilot.r3.changed",
                payload=payload,
                connection=connection,
                created_at=changed_at,
            )
            updated = connection.execute(
                "SELECT * FROM copilot_r3_capabilities WHERE show_id = ?",
                (authority.show_id,),
            ).fetchone()
        await self.hub.notify(authority.show_id)
        return _from_row(updated)


def _from_row(row) -> R3Capability:
    return R3Capability(
        seller_id=row["seller_id"],
        show_id=row["show_id"],
        enabled=bool(row["enabled"]),
        version=int(row["version"]),
        updated_by=row["updated_by"],
        updated_at=row["updated_at"],
    )


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("wall clock must return an aware datetime")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
