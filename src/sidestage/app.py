"""Authoritative SideStage marketplace, chat, and bounded copilot application."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Callable, Dict, Literal, Optional
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from sidestage.config import (
    DEFAULT_RUNTIME_DATABASE,
    REPOSITORY_ROOT,
)
from sidestage.agent_core import (
    ModelRunner,
    OpenAICompatibleModelConfig,
    OpenAICompatibleModelRunner,
    OpenRouterRoutingConfig,
    ScriptedModelRunner,
)
from sidestage.copilot.capability import R3CapabilityChangeRequest, R3CapabilityService
from sidestage.copilot.broker import (
    R2ResultHandler,
    ReplyEffectBroker,
    ReplyPersistenceError,
    SellerReplyDecisionRequest,
    SellerReplyService,
    copilot_projection,
)
from sidestage.copilot.pipeline import (
    PipelineServices,
    RawCustomerReplyEvent,
    process_customer_reply,
)
from sidestage.copilot.retrieval import EvidenceRetriever
from sidestage.copilot.routing import CopilotRouter
from sidestage.copilot.scheduling import LivesellWorkScheduler
from sidestage.copilot.workflows import (
    register_template_workflow,
    register_two_call_workflow,
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
from sidestage.trace.recorder import BufferedTraceSink, SqliteTraceSink, TraceRecorder
from sidestage.trace.projection import runtime_trace_projection


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
    monotonic_clock: Callable[[], float] = time.monotonic,
    prepared_seed: int = 20260817,
    model_runner: Optional[ModelRunner] = None,
    model_config_ref: str = "sidestage-model-v1",
    workflow_strategy: Literal["two_call_draft", "one_call_template"] = "two_call_draft",
    before_reply_receipt_insert: Optional[Callable[[], None]] = None,
    before_auto_send_commit: Optional[Callable[[], None]] = None,
) -> FastAPI:
    catalog = load_seller_fixture()
    clock = wall_clock or (lambda: datetime.now(timezone.utc))
    database = MarketplaceDatabase(database_path)
    database.initialize(catalog, evidence_imported_at=_utc_millis(clock()))
    marketplace = MarketplaceService(database)
    stream_store = StreamEventStore(database)
    hub = SseHub(stream_store)
    ingestor = EventIngestor(
        database,
        stream_store,
        wall_clock=clock,
    )
    prepared = PreparedChatSource(seed=prepared_seed)
    sessions = DemoSessionRegistry(catalog)
    configured_runner = model_runner or ScriptedModelRunner(())
    copilot_router = CopilotRouter(database, catalog)
    trace_sink = BufferedTraceSink(SqliteTraceSink(database))
    trace_recorder = TraceRecorder(
        sink=trace_sink,
        wall_clock=clock,
        monotonic=monotonic_clock,
    )
    if workflow_strategy == "one_call_template":
        workflow = register_template_workflow(
            configured_runner,
            model_config_ref=model_config_ref,
            monotonic=monotonic_clock,
            trace_sink=trace_sink,
        )
        analyzer = None
        reply_agent = workflow.evidence_template_agent
    else:
        workflow = register_two_call_workflow(
            configured_runner,
            model_config_ref=model_config_ref,
            monotonic=monotonic_clock,
            trace_sink=trace_sink,
        )
        analyzer = workflow.evidence_planner
        reply_agent = workflow.reply_drafter_agent
    retriever = EvidenceRetriever(database, catalog)
    work_scheduler = LivesellWorkScheduler(monotonic=monotonic_clock)
    broker = ReplyEffectBroker(database, catalog)
    result_handler = R2ResultHandler(
        database,
        catalog,
        stream_store,
        hub,
        wall_clock=clock,
        before_auto_send=before_auto_send_commit,
        before_receipt_insert=before_reply_receipt_insert,
    )
    r3_capability_service = R3CapabilityService(
        database,
        stream_store,
        hub,
        wall_clock=clock,
    )
    reply_service = SellerReplyService(
        database,
        catalog,
        stream_store,
        hub,
        wall_clock=clock,
        before_receipt_insert=before_reply_receipt_insert,
    )
    pipeline_services = PipelineServices(
        catalog=catalog,
        ingestor=ingestor,
        router=copilot_router,
        analyzer=analyzer,
        retriever=retriever,
        reply_agent=reply_agent,
        broker=broker,
        result_handler=result_handler,
        trace_recorder=trace_recorder,
        wall_clock=clock,
        monotonic=monotonic_clock,
        work_scheduler=work_scheduler,
        workflow=workflow,
    )

    application = FastAPI(
        title="SideStage M3B",
        version="0.3.2",
        description="Synthetic live-selling copilot with a closed registered agent workflow",
    )
    application.state.database = database
    application.state.marketplace = marketplace
    application.state.ingestor = ingestor
    application.state.stream_store = stream_store
    application.state.hub = hub
    application.state.sessions = sessions
    application.state.copilot_router = copilot_router
    application.state.model_runner = configured_runner
    application.state.analyzer = analyzer
    application.state.retriever = retriever
    application.state.reply_agent = reply_agent
    application.state.copilot_workflow = workflow
    application.state.workflow_strategy = workflow_strategy
    application.state.work_scheduler = work_scheduler
    application.state.reply_broker = broker
    application.state.reply_service = reply_service
    application.state.r3_capability_service = r3_capability_service
    application.state.pipeline_services = pipeline_services
    application.state.trace_sink = trace_sink
    application.add_event_handler("shutdown", trace_sink.close)

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
        result = await process_customer_reply(
            RawCustomerReplyEvent(
                authority=session.authority,
                customer_display_name="demo_tester",
                raw_text=request.raw_text,
                input_origin="custom",
            ),
            pipeline_services,
        )
        await hub.notify(session.authority.show_id)
        event = next(
            item
            for item in ingestor.events(session.authority)
            if item.event_id == result.event_id
        )
        return {
            "events": [event.model_dump(mode="json")],
            "pipeline_results": [result.model_dump(mode="json")],
            "snapshot": _snapshot(
                catalog,
                marketplace,
                ingestor,
                stream_store,
                session.authority,
            ),
        }

    @application.post("/api/sessions/{session_token}/chat/prepared", status_code=201)
    async def accept_prepared_chat(session_token: str, request: PreparedChatRequest) -> dict:
        session = sessions.require(session_token)
        selected = prepared.take(session.authority.seller_id, request.count)
        results = await asyncio.gather(
            *(
                process_customer_reply(
                    RawCustomerReplyEvent(
                        authority=session.authority,
                        customer_display_name=display_name,
                        raw_text=raw_text,
                        input_origin="prepared",
                    ),
                    pipeline_services,
                )
                for display_name, raw_text in selected
            )
        )
        result_ids = {result.event_id for result in results}
        events = [
            event for event in ingestor.events(session.authority) if event.event_id in result_ids
        ]
        await hub.notify(session.authority.show_id)
        return {
            "events": [event.model_dump(mode="json") for event in events],
            "pipeline_results": [result.model_dump(mode="json") for result in results],
            "snapshot": _snapshot(
                catalog,
                marketplace,
                ingestor,
                stream_store,
                session.authority,
            ),
        }

    @application.post("/api/sessions/{session_token}/copilot/questions/{question_id}/decision")
    async def decide_reply(
        session_token: str,
        question_id: str,
        request: SellerReplyDecisionRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ) -> dict:
        session = sessions.require(session_token)
        try:
            result = await reply_service.decide(
                session.authority,
                question_id,
                request,
                idempotency_key=idempotency_key,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        result["snapshot"] = _snapshot(
            catalog,
            marketplace,
            ingestor,
            stream_store,
            session.authority,
        )
        return result

    @application.post("/api/sessions/{session_token}/copilot/r3")
    async def change_r3_capability(
        session_token: str,
        request: R3CapabilityChangeRequest,
    ) -> dict:
        session = sessions.require(session_token)
        try:
            capability = await r3_capability_service.change(session.authority, request)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "capability": capability.model_dump(mode="json"),
            "snapshot": _snapshot(
                catalog,
                marketplace,
                ingestor,
                stream_store,
                session.authority,
            ),
        }

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

    @application.get("/api/debug/copilot")
    def debug_copilot(
        session_token: str = Query(min_length=1),
        actual_route: Optional[str] = Query(default=None),
    ) -> dict:
        session = sessions.require(session_token)
        trace_sink.flush()
        try:
            return runtime_trace_projection(
                database,
                seller_id=session.authority.seller_id,
                show_id=session.authority.show_id,
                actual_route=actual_route,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

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

    @application.exception_handler(ReplyPersistenceError)
    async def reply_persistence_error(_request, _error: ReplyPersistenceError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=500, content={"detail": "REPLY_PERSISTENCE_FAILED"})

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


def create_live_app(
    *,
    database_path: Path = DEFAULT_RUNTIME_DATABASE,
    wall_clock: Optional[WallClock] = None,
    monotonic_clock: Callable[[], float] = time.monotonic,
    prepared_seed: int = 20260817,
    model_provider: Optional[Literal["openai", "openrouter"]] = None,
    workflow_strategy: Optional[
        Literal["two_call_draft", "one_call_template"]
    ] = None,
) -> FastAPI:
    """Build the reviewer-facing app with one fail-fast live model configuration."""

    provider = model_provider or os.environ.get("SIDESTAGE_MODEL_PROVIDER", "openai")
    if provider not in {"openai", "openrouter"}:
        raise RuntimeError("SIDESTAGE_MODEL_PROVIDER must be openai or openrouter")
    strategy = workflow_strategy or os.environ.get(
        "SIDESTAGE_WORKFLOW_STRATEGY", "two_call_draft"
    )
    if strategy not in {"two_call_draft", "one_call_template"}:
        raise RuntimeError(
            "SIDESTAGE_WORKFLOW_STRATEGY must be two_call_draft or one_call_template"
        )
    if provider == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY")
        default_base_url = "https://openrouter.ai/api/v1"
        routing = OpenRouterRoutingConfig()
        missing_key_message = "live OpenRouter app requires OPENROUTER_API_KEY"
    else:
        api_key = os.environ.get("SIDESTAGE_MODEL_API_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        )
        default_base_url = "https://api.openai.com/v1"
        routing = None
        missing_key_message = (
            "live OpenAI app requires OPENAI_API_KEY or SIDESTAGE_MODEL_API_KEY"
        )
    model_id = os.environ.get("SIDESTAGE_MODEL_ID")
    if not api_key:
        raise RuntimeError(missing_key_message)
    if not model_id:
        raise RuntimeError("live app requires SIDESTAGE_MODEL_ID")

    model_config_ref = "sidestage-livesell-live-v1"
    runner = OpenAICompatibleModelRunner(
        OpenAICompatibleModelConfig(
            config_ref=model_config_ref,
            base_url=os.environ.get(
                "SIDESTAGE_MODEL_BASE_URL", default_base_url
            ),
            api_key=api_key,
            model_id=model_id,
            request_timeout_s=5.0,
            strict_function_tools=True,
            reasoning_effort=os.environ.get(
                "SIDESTAGE_MODEL_REASONING_EFFORT", "none"
            ),
            openrouter_routing=routing,
        )
    )
    application = create_app(
        database_path=database_path,
        wall_clock=wall_clock,
        monotonic_clock=monotonic_clock,
        prepared_seed=prepared_seed,
        model_runner=runner,
        model_config_ref=model_config_ref,
        workflow_strategy=strategy,
    )
    application.state.model_runtime = {
        "mode": "live",
        "provider": provider,
        "workflow_strategy": strategy,
        "model_id": runner.config.model_id,
        "model_config_ref": runner.config.config_ref,
        "base_url": runner.config.base_url,
        "reasoning_effort": runner.config.reasoning_effort,
        "request_timeout_s": runner.config.request_timeout_s,
        "strict_function_tools": runner.config.strict_function_tools,
        "openrouter_routing": (
            runner.config.openrouter_routing.model_dump(mode="json")
            if runner.config.openrouter_routing is not None
            else None
        ),
    }
    application.add_event_handler("shutdown", runner.aclose)
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
    projection = copilot_projection(
        marketplace.database,
        seller_id=authority.seller_id,
        show_id=authority.show_id,
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
        "copilot_enabled": True,
        **projection,
    }


def _utc_millis(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("wall clock must return an aware datetime")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )
