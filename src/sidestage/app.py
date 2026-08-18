"""Authoritative non-AI SideStage marketplace and chat application."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Callable, Dict, Optional
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from sidestage.config import (
    DEFAULT_RUNTIME_DATABASE,
    REPOSITORY_ROOT,
)
from sidestage.fixtures.import_trace import trace_seller_fixture_import
from sidestage.fixtures.loader import SellerCatalog, load_seller_fixture
from sidestage.marketplace.authority import SellerAuthority
from sidestage.marketplace.service import (
    AuditPersistenceError,
    InventoryChangeRequest,
    MarketplaceService,
    OperationReceipt,
    PriceMarkdownRequest,
    PushRequest,
    SwapRequest,
    UnlistRequest,
)
from sidestage.storage.database import MarketplaceDatabase
from sidestage.streaming.hub import SseHub, StreamEventStore
from sidestage.streaming.ingest import EventIngestor, PreparedChatSource


WallClock = Callable[[], datetime]


class ApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateSessionRequest(ApiRequest):
    seller_id: str


class CustomChatRequest(ApiRequest):
    raw_text: str = Field(min_length=1, max_length=240)


class PreparedChatRequest(ApiRequest):
    count: int = Field(default=1, ge=1, le=8)


@dataclass(frozen=True)
class DemoSession:
    token: str
    authority: SellerAuthority


class DemoSessionRegistry:
    def __init__(self, catalog: SellerCatalog) -> None:
        self.catalog = catalog
        self._sessions: Dict[str, DemoSession] = {}
        self._lock = Lock()

    def issue(self, seller_id: str) -> DemoSession:
        try:
            self.catalog.seller(seller_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="unknown demo seller") from error
        token = f"ses_{uuid4().hex}"
        session = DemoSession(
            token=token,
            authority=SellerAuthority(
                seller_id=seller_id,
                show_id=f"show_{seller_id.removeprefix('sel_')}",
                actor_id=f"demo_{seller_id.removeprefix('sel_')}",
            ),
        )
        with self._lock:
            self._sessions[token] = session
        return session

    def require(self, token: str) -> DemoSession:
        with self._lock:
            session = self._sessions.get(token)
        if session is None:
            raise HTTPException(status_code=404, detail="unknown or expired demo session")
        return session


def create_app(
    *,
    database_path: Path = DEFAULT_RUNTIME_DATABASE,
    wall_clock: Optional[WallClock] = None,
    prepared_seed: int = 20260817,
) -> FastAPI:
    catalog = load_seller_fixture()
    database = MarketplaceDatabase(database_path)
    database.initialize(catalog)
    marketplace = MarketplaceService(database)
    stream_store = StreamEventStore(database)
    hub = SseHub(stream_store)
    ingestor = EventIngestor(
        database,
        stream_store,
        wall_clock=wall_clock or (lambda: datetime.now(timezone.utc)),
    )
    prepared = PreparedChatSource(seed=prepared_seed)
    sessions = DemoSessionRegistry(catalog)

    application = FastAPI(
        title="SideStage M2.3",
        version="0.2.3",
        description="Synthetic non-AI live-selling marketplace emulator",
    )
    application.state.database = database
    application.state.marketplace = marketplace
    application.state.ingestor = ingestor
    application.state.stream_store = stream_store
    application.state.hub = hub
    application.state.sessions = sessions

    @application.get("/api/sellers")
    def list_sellers() -> dict:
        return {
            "sellers": [
                {
                    "seller_id": seller.seller_id,
                    "display_name": seller.display_name,
                    "persona": seller.persona,
                }
                for seller in catalog.document.sellers
            ]
        }

    @application.post("/api/demo/sessions", status_code=201)
    def create_session(request: CreateSessionRequest) -> dict:
        session = sessions.issue(request.seller_id)
        return {
            "session_token": session.token,
            "snapshot": _snapshot(
                catalog,
                marketplace,
                ingestor,
                stream_store,
                session.authority,
            ),
        }

    @application.get("/api/sessions/{session_token}/snapshot")
    def get_snapshot(session_token: str) -> dict:
        session = sessions.require(session_token)
        return _snapshot(
            catalog,
            marketplace,
            ingestor,
            stream_store,
            session.authority,
        )

    @application.post("/api/sessions/{session_token}/chat/custom", status_code=201)
    async def accept_custom_chat(session_token: str, request: CustomChatRequest) -> dict:
        session = sessions.require(session_token)
        event = ingestor.ingest(
            session.authority,
            customer_display_name="demo_tester",
            raw_text=request.raw_text,
            input_origin="custom",
        )
        await hub.notify(session.authority.show_id)
        return {"events": [event.model_dump(mode="json")]}

    @application.post("/api/sessions/{session_token}/chat/prepared", status_code=201)
    async def accept_prepared_chat(session_token: str, request: PreparedChatRequest) -> dict:
        session = sessions.require(session_token)
        events = [
            ingestor.ingest(
                session.authority,
                customer_display_name=display_name,
                raw_text=raw_text,
                input_origin="prepared",
            )
            for display_name, raw_text in prepared.take(session.authority.seller_id, request.count)
        ]
        await hub.notify(session.authority.show_id)
        return {"events": [event.model_dump(mode="json") for event in events]}

    @application.post("/api/sessions/{session_token}/actions/push")
    async def push(
        session_token: str,
        request: PushRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict:
        session = sessions.require(session_token)
        receipt = marketplace.push(
            session.authority,
            request,
            idempotency_key=idempotency_key,
        )
        return await _action_response(
            receipt,
            session.authority,
            catalog,
            marketplace,
            ingestor,
            stream_store,
            hub,
        )

    @application.post("/api/sessions/{session_token}/actions/swap")
    async def swap(
        session_token: str,
        request: SwapRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict:
        session = sessions.require(session_token)
        receipt = marketplace.swap(
            session.authority,
            request,
            idempotency_key=idempotency_key,
        )
        return await _action_response(
            receipt, session.authority, catalog, marketplace, ingestor, stream_store, hub
        )

    @application.post("/api/sessions/{session_token}/actions/unlist")
    async def unlist(
        session_token: str,
        request: UnlistRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict:
        session = sessions.require(session_token)
        receipt = marketplace.unlist(
            session.authority,
            request,
            idempotency_key=idempotency_key,
        )
        return await _action_response(
            receipt, session.authority, catalog, marketplace, ingestor, stream_store, hub
        )

    @application.post("/api/sessions/{session_token}/actions/price-markdown")
    async def price_markdown(
        session_token: str,
        request: PriceMarkdownRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict:
        session = sessions.require(session_token)
        receipt = marketplace.price_markdown(
            session.authority,
            request,
            idempotency_key=idempotency_key,
        )
        return await _action_response(
            receipt, session.authority, catalog, marketplace, ingestor, stream_store, hub
        )

    @application.post("/api/sessions/{session_token}/actions/inventory-change")
    async def inventory_change(
        session_token: str,
        request: InventoryChangeRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict:
        session = sessions.require(session_token)
        receipt = marketplace.inventory_change(
            session.authority,
            request,
            idempotency_key=idempotency_key,
        )
        return await _action_response(
            receipt, session.authority, catalog, marketplace, ingestor, stream_store, hub
        )

    @application.post(
        "/api/sessions/{session_token}/receipts/{receipt_id}/compensate"
    )
    async def compensate(
        session_token: str,
        receipt_id: str,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict:
        session = sessions.require(session_token)
        try:
            receipt = marketplace.compensate(
                session.authority,
                receipt_id,
                idempotency_key=idempotency_key,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return await _action_response(
            receipt, session.authority, catalog, marketplace, ingestor, stream_store, hub
        )

    @application.get("/api/sessions/{session_token}/events")
    async def stream_events(
        session_token: str,
        after: int = Query(default=0, ge=0),
        once: bool = Query(default=False),
        last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        session = sessions.require(session_token)
        cursor = after
        if last_event_id is not None:
            try:
                cursor = max(cursor, int(last_event_id))
            except ValueError as error:
                raise HTTPException(status_code=400, detail="invalid Last-Event-ID") from error
        return StreamingResponse(
            hub.stream(session.authority.show_id, after=cursor, once=once),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @application.get("/api/debug/marketplace")
    def debug_marketplace(session_token: str = Query(min_length=1)) -> dict:
        session = sessions.require(session_token)
        return {
            "runtime_source": "m2_3_sqlite",
            "snapshot": _snapshot(
                catalog,
                marketplace,
                ingestor,
                stream_store,
                session.authority,
            ),
        }

    @application.get("/api/debug/import-trace")
    def import_trace() -> dict:
        try:
            return trace_seller_fixture_import()
        except Exception as error:
            raise HTTPException(status_code=500, detail="IMPORT_TRACE_UNAVAILABLE") from error

    @application.exception_handler(AuditPersistenceError)
    async def audit_error(_request, _error: AuditPersistenceError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=500, content={"detail": "MARKETPLACE_PERSISTENCE_FAILED"})

    application.mount(
        "/fixtures",
        StaticFiles(directory=str(REPOSITORY_ROOT / "fixtures")),
        name="fixtures",
    )
    application.mount(
        "/app",
        StaticFiles(directory=str(REPOSITORY_ROOT / "src" / "sidestage" / "web" / "static"), html=True),
        name="app",
    )

    @application.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/app/")

    return application


async def _action_response(
    receipt: OperationReceipt,
    authority: SellerAuthority,
    catalog: SellerCatalog,
    marketplace: MarketplaceService,
    ingestor: EventIngestor,
    stream_store: StreamEventStore,
    hub: SseHub,
) -> dict:
    payload = {
        "receipt_id": receipt.receipt_id,
        "operation_type": receipt.operation_type.value,
        "status": receipt.status,
    }
    stream_store.append(
        seller_id=authority.seller_id,
        show_id=authority.show_id,
        event_type="marketplace.changed",
        payload=payload,
        created_at=receipt.recorded_at,
    )
    await hub.notify(authority.show_id)
    return {
        "receipt": receipt.model_dump(mode="json"),
        "snapshot": _snapshot(
            catalog,
            marketplace,
            ingestor,
            stream_store,
            authority,
        ),
    }


def _snapshot(
    catalog: SellerCatalog,
    marketplace: MarketplaceService,
    ingestor: EventIngestor,
    stream_store: StreamEventStore,
    authority: SellerAuthority,
) -> dict:
    seller = catalog.seller(authority.seller_id)
    show = marketplace.show_state(authority.show_id)
    listings = []
    for product in seller.products:
        listing = marketplace.listing_state(product.listing.listing_id)
        variants = []
        for fixture_variant in product.variants:
            inventory = marketplace.inventory_state(fixture_variant.variant_id)
            variants.append(
                {
                    "variant_id": inventory.variant_id,
                    "label": fixture_variant.label,
                    "available_quantity": inventory.available_quantity,
                    "version": inventory.version,
                }
            )
        listings.append(
            {
                "product_id": product.product_id,
                "listing_id": listing.listing_id,
                "sku": product.sku,
                "brand": product.brand,
                "model_name": product.model_name,
                "colorway": product.colorway,
                "title": product.listing.title,
                "condition": product.listing.condition,
                "condition_notes": product.listing.condition_notes,
                "price_cents": listing.price_cents,
                "floor_price_cents": listing.floor_price_cents,
                "status": "active" if show.active_listing_id == listing.listing_id else listing.status,
                "version": listing.version,
                "variants": variants,
                "facts": product.facts.model_dump(mode="json"),
            }
        )
    receipts = [receipt.model_dump(mode="json") for receipt in marketplace.receipts(authority.show_id)]
    latest_applied = next(
        (receipt for receipt in reversed(receipts) if receipt["status"] == "applied"),
        None,
    )
    latest_undoable = (
        latest_applied["receipt_id"]
        if latest_applied and latest_applied["compensation_for_receipt_id"] is None
        else None
    )
    return {
        "seller": seller.model_dump(mode="json"),
        "show": show.model_dump(mode="json"),
        "listings": listings,
        "chat_events": [
            event.model_dump(mode="json") for event in ingestor.events(authority)
        ],
        "epochs": [
            epoch.model_dump(mode="json") for epoch in marketplace.epochs(authority.show_id)
        ],
        "receipts": receipts,
        "latest_undoable_receipt_id": latest_undoable,
        "stream_offset": stream_store.latest_offset(authority.show_id),
        "copilot_enabled": False,
    }
