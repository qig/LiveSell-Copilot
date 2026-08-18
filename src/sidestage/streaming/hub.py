"""Persisted SSE replay with a small in-process wake-up hub."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, AsyncIterator, DefaultDict, Dict, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict

from sidestage.storage.database import MarketplaceDatabase


class StreamEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    stream_offset: int
    seller_id: str
    show_id: str
    event_type: str
    payload: Dict[str, Any]
    created_at: str


class StreamEventStore:
    def __init__(self, database: MarketplaceDatabase) -> None:
        self.database = database

    def append(
        self,
        *,
        seller_id: str,
        show_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        connection: Optional[sqlite3.Connection] = None,
        created_at: Optional[str] = None,
    ) -> int:
        timestamp = created_at or _utc_millis()
        body = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
        if connection is not None:
            cursor = connection.execute(
                """INSERT INTO stream_events(
                       seller_id, show_id, event_type, payload_json, created_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (seller_id, show_id, event_type, body, timestamp),
            )
            return int(cursor.lastrowid)
        with self.database.transaction() as transaction:
            return self.append(
                seller_id=seller_id,
                show_id=show_id,
                event_type=event_type,
                payload=payload,
                connection=transaction,
                created_at=timestamp,
            )

    def after(self, show_id: str, offset: int, *, limit: int = 100) -> Tuple[StreamEvent, ...]:
        with self.database.read() as connection:
            rows = connection.execute(
                """SELECT stream_offset, seller_id, show_id, event_type, payload_json, created_at
                   FROM stream_events
                   WHERE show_id = ? AND stream_offset > ?
                   ORDER BY stream_offset LIMIT ?""",
                (show_id, offset, limit),
            ).fetchall()
        return tuple(
            StreamEvent(
                stream_offset=row["stream_offset"],
                seller_id=row["seller_id"],
                show_id=row["show_id"],
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        )

    def latest_offset(self, show_id: str) -> int:
        with self.database.read() as connection:
            value = connection.execute(
                "SELECT COALESCE(MAX(stream_offset), 0) FROM stream_events WHERE show_id = ?",
                (show_id,),
            ).fetchone()[0]
        return int(value)


class SseHub:
    """Wake live listeners while retaining SQLite as replay authority."""

    def __init__(self, store: StreamEventStore) -> None:
        self.store = store
        self._conditions: DefaultDict[str, asyncio.Condition] = defaultdict(asyncio.Condition)

    async def notify(self, show_id: str) -> None:
        condition = self._conditions[show_id]
        async with condition:
            condition.notify_all()

    async def stream(
        self,
        show_id: str,
        *,
        after: int,
        once: bool = False,
    ) -> AsyncIterator[str]:
        cursor = max(0, after)
        while True:
            events = self.store.after(show_id, cursor)
            if events:
                for event in events:
                    cursor = event.stream_offset
                    yield _format_sse(event)
                if once:
                    return
                continue
            if once:
                return

            condition = self._conditions[show_id]
            try:
                async with condition:
                    # Close the read-to-wait race: a producer commits first, then
                    # takes this same lock to notify. If it committed before this
                    # lock was acquired, the second read observes the event; if it
                    # commits after, wait() registers before releasing the lock.
                    if self.store.after(show_id, cursor):
                        continue
                    await asyncio.wait_for(condition.wait(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"


def _format_sse(event: StreamEvent) -> str:
    body = json.dumps(event.payload, sort_keys=True, separators=(",", ":"))
    return f"id: {event.stream_offset}\nevent: {event.event_type}\ndata: {body}\n\n"


def _utc_millis() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
