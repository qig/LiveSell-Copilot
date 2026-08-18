from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from sidestage.agent_core import (
    AgentRunResult,
    LatencyBreakdown,
    RunStatus,
    TerminalIntent,
)
from sidestage.copilot.analysis import AnalysisInput, AnalysisResult, AnalysisStatus
from sidestage.copilot.contracts import (
    AnalysisIntent,
    BoundListing,
    EvidenceRecord,
    EvidenceRequest,
    EvidenceSnapshot,
    EvidenceSource,
    ReplyTask,
)
from sidestage.copilot.pipeline import (
    PipelineServices,
    PipelineStatus,
    RawCustomerReplyEvent,
    process_customer_reply,
)
from sidestage.copilot.retrieval import RetrievalResult, RetrievalStatus
from sidestage.copilot.routing import NormalizedQuestion, RoutingDecision
from sidestage.domain.replies import (
    AnswerCategory,
    BindingBasis,
    BindingStatus,
    BrokerDecision,
    BrokerOutcome,
    FactType,
    QuestionState,
    ReplyRoute,
)
from sidestage.fixtures.loader import load_seller_fixture
from sidestage.marketplace.authority import SellerAuthority
from sidestage.storage.database import MarketplaceDatabase
from sidestage.streaming.ingest import AcceptedChatEvent
from sidestage.trace.recorder import (
    InMemoryTraceSink,
    SqliteTraceSink,
    TraceObservationStatus,
    TraceRecorder,
    TraceStage,
)


NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
TRACE = "trc_pipeline_1"
SELLER = "sel_velocity_kicks"
SHOW = "show_velocity_kicks"
LISTING = "lst_velocity_aero_dash"
EPOCH = "epc_velocity_1"


def _accepted() -> AcceptedChatEvent:
    return AcceptedChatEvent(
        event_id="evt_pipeline_1",
        seller_id=SELLER,
        show_id=SHOW,
        customer_display_name="tester",
        raw_text="How much is this pair?",
        input_origin="custom",
        accepted_at="2026-08-17T12:00:00.000Z",
        show_seq=2,
        trace_id=TRACE,
        source_epoch_id=EPOCH,
        source_listing_id=LISTING,
    )


def _bound() -> BoundListing:
    return BoundListing(
        listing_id=LISTING,
        sku="VK-AD-RC-001",
        epoch_id=EPOCH,
        binding_basis=BindingBasis.SOURCE_EPOCH,
        binding_status=BindingStatus.CERTAIN,
    )


def _normalized(event: AcceptedChatEvent) -> NormalizedQuestion:
    return NormalizedQuestion(
        question_id="qst_pipeline_1",
        event_id=event.event_id,
        event=event,
        normalized_text="how much is this pair",
        canonical_key="how much is this pair",
        canonical_scope=EPOCH,
        canonical_question_id=None,
        bound_listing=_bound(),
    )


def _routing() -> RoutingDecision:
    return RoutingDecision(
        question_id="qst_pipeline_1",
        event_id="evt_pipeline_1",
        route=ReplyRoute.ELIGIBLE,
        state=QuestionState.QUEUED,
        reason_code="eligible_candidate",
        normalized_text="how much is this pair",
        canonical_key="how much is this pair",
        canonical_question_id=None,
        bound_listing=_bound(),
        should_process=True,
    )


def _analysis() -> AnalysisResult:
    return AnalysisResult(
        analysis_id="ana_pipeline_1",
        question_id="qst_pipeline_1",
        trace_id=TRACE,
        model_id="scripted-analysis",
        status=AnalysisStatus.SUCCEEDED,
        request=EvidenceRequest(
            intent=AnalysisIntent.ANSWERABLE,
            answer_category=AnswerCategory.PRICE,
            product_mentions=("Aero Dash",),
            required_fact_types=(FactType.CURRENT_PRICE,),
        ),
        duration_ms=10.0,
    )


def _snapshot() -> EvidenceSnapshot:
    return EvidenceSnapshot(
        snapshot_id="snp_pipeline_1",
        seller_id=SELLER,
        show_id=SHOW,
        listing_id=LISTING,
        epoch_id=EPOCH,
        created_at=NOW,
        records=(
            EvidenceRecord(
                evidence_id="evd_pipeline_price",
                seller_id=SELLER,
                listing_id=LISTING,
                fact_type=FactType.CURRENT_PRICE,
                value="USD 160.00",
                source=EvidenceSource.MARKETPLACE_STATE,
                source_ref=f"sqlite:listings/{LISTING}/price_cents",
                source_version=1,
                observed_at=NOW,
                provenance="synthetic_seller_data",
            ),
        ),
    )


def _agent_result() -> AgentRunResult:
    return AgentRunResult(
        task_id="qst_pipeline_1",
        adapter_id="sidestage.reply",
        profile_version="1.0.0",
        profile_digest="sha256:" + "a" * 64,
        run_id="run_pipeline_1",
        trace_id=TRACE,
        model_id="scripted-reply",
        status=RunStatus.SUCCEEDED,
        terminal_intent=TerminalIntent(
            tool_name="request_reply_send",
            arguments={
                "reply_text": "It is $160.",
                "answer_category": "price",
                "claims": [
                    {
                        "reply_span": "It is $160.",
                        "evidence_ids": ["evd_pipeline_price"],
                    }
                ],
            },
        ),
        latency=LatencyBreakdown(
            queue_ms=1.0,
            provider_ms=10.0,
            parse_ms=1.0,
            total_ms=12.0,
        ),
        completed_monotonic_s=100.5,
    )


def _raw() -> RawCustomerReplyEvent:
    return RawCustomerReplyEvent(
        authority=SellerAuthority(
            seller_id=SELLER,
            show_id=SHOW,
            actor_id="demo_velocity_kicks",
        ),
        customer_display_name="tester",
        raw_text="How much is this pair?",
        input_origin="custom",
    )


class _Ingestor:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def ingest(self, _authority, **kwargs):
        self.calls.append("ingest")
        assert kwargs["trace_id"] == TRACE
        return _accepted()


class _Router:
    def __init__(self, calls: list[str], decision: RoutingDecision | None = None) -> None:
        self.calls = calls
        self.decision = decision or _routing()

    def normalize_and_deduplicate(self, event):
        self.calls.append("normalize")
        return _normalized(event)

    def route(self, _normalized_question):
        self.calls.append("route")
        return self.decision


class _Analyzer:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def analyze(self, value: AnalysisInput):
        self.calls.append("analysis")
        assert value.question_id == "qst_pipeline_1"
        return _analysis()


class _Retriever:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def retrieve(self, _context, _request):
        self.calls.append("retrieval")
        return RetrievalResult(status=RetrievalStatus.SUCCEEDED, snapshot=_snapshot())


class _Agent:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def run(self, task: ReplyTask):
        self.calls.append("agent")
        assert task.evidence_snapshot.snapshot_id == "snp_pipeline_1"
        return _agent_result()


class _Broker:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def evaluate(self, _agent_result, _routing, _snapshot):
        self.calls.append("broker")
        return BrokerDecision(
            outcome=BrokerOutcome.REVIEW,
            reason_code="supported_for_review",
            reply_text="It is $160.",
            evidence_ids=("evd_pipeline_price",),
        )


class _ResultHandler:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def handle(self, _event, _routing, _snapshot, _broker):
        self.calls.append("result")
        return {"question_id": "qst_pipeline_1", "state": "awaiting_review"}


def _services(calls: list[str], recorder: TraceRecorder, *, router=None) -> PipelineServices:
    return PipelineServices(
        catalog=load_seller_fixture(),
        ingestor=_Ingestor(calls),
        router=router or _Router(calls),
        analyzer=_Analyzer(calls),
        retriever=_Retriever(calls),
        reply_agent=_Agent(calls),
        broker=_Broker(calls),
        result_handler=_ResultHandler(calls),
        trace_recorder=recorder,
        wall_clock=lambda: NOW,
        monotonic=lambda: 100.0,
        trace_id_factory=lambda: TRACE,
    )


def test_pipeline_trace_order_is_produced_by_the_eight_real_component_calls() -> None:
    calls: list[str] = []
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink=sink, wall_clock=lambda: NOW, monotonic=lambda: 100.0)

    result = asyncio.run(process_customer_reply(_raw(), _services(calls, recorder)))

    assert result.status is PipelineStatus.COMPLETED
    assert calls == [
        "ingest",
        "normalize",
        "route",
        "analysis",
        "retrieval",
        "agent",
        "broker",
        "result",
    ]
    observations = sink.observations
    assert len(observations) == 16
    for stage in TraceStage:
        stage_events = [event for event in observations if event.stage is stage]
        assert [event.status for event in stage_events] == [
            TraceObservationStatus.STARTED,
            TraceObservationStatus.COMPLETED,
        ]
    stage_six = [event for event in observations if event.stage is TraceStage.REPLY_AGENT][-1]
    assert stage_six.agent_run_id == "run_pipeline_1"
    assert stage_six.profile_digest == "sha256:" + "a" * 64
    serialized = json.dumps([event.model_dump(mode="json") for event in observations])
    assert "How much is this pair?" not in serialized
    assert "api_key" not in serialized


def test_early_route_exit_records_all_downstream_stages_as_skipped() -> None:
    calls: list[str] = []
    sink = InMemoryTraceSink()
    recorder = TraceRecorder(sink=sink, wall_clock=lambda: NOW, monotonic=lambda: 100.0)
    noise = _routing().model_copy(
        update={
            "route": ReplyRoute.NOISE,
            "state": None,
            "reason_code": "deterministic_noise",
            "should_process": False,
        }
    )

    result = asyncio.run(
        process_customer_reply(
            _raw(),
            _services(calls, recorder, router=_Router(calls, noise)),
        )
    )

    assert result.status is PipelineStatus.EXITED
    assert result.reason_code == "deterministic_noise"
    assert calls == ["ingest", "normalize", "route"]
    route_terminal = [
        event
        for event in sink.observations
        if event.stage is TraceStage.DETERMINISTIC_ROUTE
    ][-1]
    assert route_terminal.status is TraceObservationStatus.EXITED
    skipped = [
        event for event in sink.observations if event.status is TraceObservationStatus.SKIPPED
    ]
    assert [event.stage for event in skipped] == list(TraceStage)[3:]
    assert all(event.reason_code == "deterministic_noise" for event in skipped)


def test_trace_sink_failure_cannot_change_a_successful_pipeline_result() -> None:
    class FailingSink:
        def emit(self, _observation):
            raise RuntimeError("trace storage unavailable")

    calls: list[str] = []
    recorder = TraceRecorder(sink=FailingSink(), wall_clock=lambda: NOW, monotonic=lambda: 100.0)

    result = asyncio.run(process_customer_reply(_raw(), _services(calls, recorder)))

    assert result.status is PipelineStatus.COMPLETED
    assert calls[-1] == "result"


def test_sqlite_trace_sink_persists_backend_observation_identity(tmp_path: Path) -> None:
    database = MarketplaceDatabase(tmp_path / "sidestage.sqlite3")
    database.initialize(load_seller_fixture(), evidence_imported_at="2026-08-17T11:00:00.000Z")
    sink = SqliteTraceSink(database)
    observation_ids = iter(("obs_persisted_1", "obs_persisted_2"))
    recorder = TraceRecorder(
        sink=sink,
        wall_clock=lambda: NOW,
        monotonic=lambda: 100.0,
        id_factory=lambda: next(observation_ids),
    )

    span = recorder.start(
        TraceStage.INGEST,
        trace_id=TRACE,
        seller_id=SELLER,
        show_id=SHOW,
        input_ref="raw:custom",
    )
    span.completed(event_id="evt_pipeline_1", output_ref="evt_pipeline_1")

    observations = sink.for_trace(TRACE)
    assert len(observations) == 2
    assert observations[0].component_id.endswith("EventIngestor.ingest")
    assert observations[1].event_id == "evt_pipeline_1"
    assert observations[1].duration_ms == 0.0
