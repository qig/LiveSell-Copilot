"""One authoritative path for prepared and tester-entered chat."""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Annotated, Callable, Dict, List, Literal, Optional, Sequence, Tuple
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sidestage.config import DEFAULT_CHAT_FIXTURE
from sidestage.marketplace.authority import SellerAuthority
from sidestage.marketplace.service import MarketplaceAuthorityError
from sidestage.storage.database import MarketplaceDatabase
from sidestage.streaming.hub import StreamEventStore


Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=240)]
DisplayName = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=48)]
WallClock = Callable[[], datetime]


class AcceptedChatEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    seller_id: str
    show_id: str
    customer_display_name: DisplayName
    raw_text: Text
    input_origin: Literal["prepared", "custom"]
    accepted_at: str
    show_seq: int = Field(gt=0)
    trace_id: str
    source_epoch_id: Optional[str]
    source_listing_id: Optional[str]
    workflow_id: Optional[Literal["one_call_template", "two_call_draft"]] = None
    model_profile_id: Optional[str] = None
    requested_model_id: Optional[str] = None
    model_config_ref: Optional[str] = None
    model_provider: Optional[Literal["openai", "openrouter", "scripted"]] = None
    selection_version: Optional[int] = None
    selection_selected_at: Optional[str] = None


class EventIngestor:
    def __init__(
        self,
        database: MarketplaceDatabase,
        stream_store: StreamEventStore,
        *,
        wall_clock: WallClock,
    ) -> None:
        self.database = database
        self.stream_store = stream_store
        self.wall_clock = wall_clock

    def ingest(
        self,
        authority: SellerAuthority,
        *,
        customer_display_name: str,
        raw_text: str,
        input_origin: Literal["prepared", "custom"],
        trace_id: Optional[str] = None,
        runtime_selection=None,
    ) -> AcceptedChatEvent:
        event_values = {
            "event_id": f"evt_{uuid4().hex}",
            "seller_id": authority.seller_id,
            "show_id": authority.show_id,
            "customer_display_name": customer_display_name,
            "raw_text": raw_text,
            "input_origin": input_origin,
            "accepted_at": _utc_millis(self.wall_clock()),
            "trace_id": trace_id or f"trc_{uuid4().hex}",
            "workflow_id": (
                runtime_selection.workflow_id if runtime_selection is not None else None
            ),
            "model_profile_id": (
                runtime_selection.model_profile_id if runtime_selection is not None else None
            ),
            "requested_model_id": (
                runtime_selection.requested_model_id if runtime_selection is not None else None
            ),
            "model_config_ref": (
                runtime_selection.model_config_ref if runtime_selection is not None else None
            ),
            "model_provider": (
                runtime_selection.provider if runtime_selection is not None else None
            ),
            "selection_version": (
                runtime_selection.selection_version if runtime_selection is not None else None
            ),
            "selection_selected_at": (
                _utc_millis(runtime_selection.selected_at)
                if runtime_selection is not None
                else None
            ),
        }
        with self.database.transaction() as connection:
            show = connection.execute(
                "SELECT seller_id, show_seq FROM shows WHERE show_id = ?",
                (authority.show_id,),
            ).fetchone()
            if show is None or show["seller_id"] != authority.seller_id:
                raise MarketplaceAuthorityError("seller is not authorized for this show")
            epoch = connection.execute(
                """SELECT epoch_id, listing_id FROM listing_epochs
                   WHERE show_id = ? AND end_seq IS NULL""",
                (authority.show_id,),
            ).fetchone()
            show_seq = int(show["show_seq"]) + 1
            connection.execute(
                "UPDATE shows SET show_seq = ? WHERE show_id = ?",
                (show_seq, authority.show_id),
            )
            event = AcceptedChatEvent(
                **event_values,
                show_seq=show_seq,
                source_epoch_id=epoch["epoch_id"] if epoch else None,
                source_listing_id=epoch["listing_id"] if epoch else None,
            )
            payload = event.model_dump(mode="json")
            connection.execute(
                """INSERT INTO chat_events(
                       event_id, seller_id, show_id, customer_display_name, raw_text,
                       input_origin, accepted_at, show_seq, trace_id,
                       source_epoch_id, source_listing_id, workflow_id,
                       model_profile_id, requested_model_id, model_config_ref,
                       model_provider, selection_version, selection_selected_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id,
                    event.seller_id,
                    event.show_id,
                    event.customer_display_name,
                    event.raw_text,
                    event.input_origin,
                    event.accepted_at,
                    event.show_seq,
                    event.trace_id,
                    event.source_epoch_id,
                    event.source_listing_id,
                    event.workflow_id,
                    event.model_profile_id,
                    event.requested_model_id,
                    event.model_config_ref,
                    event.model_provider,
                    event.selection_version,
                    event.selection_selected_at,
                ),
            )
            self.stream_store.append(
                seller_id=authority.seller_id,
                show_id=authority.show_id,
                event_type="chat.accepted",
                payload=payload,
                connection=connection,
                created_at=event.accepted_at,
            )
        return event

    def events(self, authority: SellerAuthority) -> Tuple[AcceptedChatEvent, ...]:
        with self.database.read() as connection:
            rows = connection.execute(
                """SELECT event_id, seller_id, show_id, customer_display_name, raw_text,
                          input_origin, accepted_at, show_seq, trace_id,
                          source_epoch_id, source_listing_id, workflow_id,
                          model_profile_id, requested_model_id, model_config_ref,
                          model_provider, selection_version, selection_selected_at
                   FROM chat_events
                   WHERE seller_id = ? AND show_id = ? ORDER BY show_seq""",
                (authority.seller_id, authority.show_id),
            ).fetchall()
        return tuple(AcceptedChatEvent.model_validate(dict(row)) for row in rows)


class PreparedChatSource:
    """Seeded weighted selection whose fixture metadata never crosses ingestion."""

    def __init__(
        self,
        path: Path = DEFAULT_CHAT_FIXTURE,
        *,
        seed: int = 20260817,
    ) -> None:
        document = json.loads(path.read_text(encoding="utf-8"))
        self._names: Sequence[str] = tuple(document["customer_names"])
        self._pools: Sequence[Dict[str, object]] = tuple(document["pools"])
        self._seed = seed
        self._random: Dict[str, random.Random] = {}
        self._lock = Lock()

    def take(self, seller_id: str, count: int) -> List[Tuple[str, str]]:
        if count < 1 or count > 8:
            raise ValueError("prepared count must be between one and eight")
        with self._lock:
            rng = self._random.setdefault(seller_id, random.Random(self._seller_seed(seller_id)))
            eligible = [
                pool
                for pool in self._pools
                if pool.get("seller_scope") in {"all", seller_id}
                and isinstance(pool.get("messages"), list)
                and not pool.get("requirements")
            ]
            weights = [int(pool["weight"]) for pool in eligible]
            selected: List[Tuple[str, str]] = []
            for _ in range(count):
                pool = rng.choices(eligible, weights=weights, k=1)[0]
                raw_text = str(rng.choice(pool["messages"]))
                display_name = str(rng.choice(self._names))
                selected.append((display_name, raw_text))
            return selected

    def _seller_seed(self, seller_id: str) -> int:
        digest = hashlib.sha256(f"{self._seed}:{seller_id}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big")


def _utc_millis(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("wall clock must return an aware datetime")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
