"""The single hardcoded SideStage customer-reply function."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Callable, Dict, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from sidestage.agent_core import RunStatus
from sidestage.copilot.analysis import AnalysisInput, AnalysisStatus
from sidestage.copilot.contracts import (
    AnalysisIntent,
    ReplyTask,
    ReplyTone,
    TemplateSelectionTask,
)
from sidestage.copilot.profile import decode_template_selection
from sidestage.copilot.retrieval import (
    RetrievalContext,
    RetrievalStatus,
    TemplateRetrievalContext,
)
from sidestage.copilot.runtime import RuntimeCatalog, RuntimeSelection, RuntimeSelector
from sidestage.copilot.scheduling import (
    WorkQueueDeadlineError,
    WorkQueueFullError,
)
from sidestage.copilot.templates import TemplateRenderError, render_approved_template
from sidestage.copilot.workflows import TemplateWorkflow, TwoCallWorkflow
from sidestage.domain.replies import BrokerDecision, ReplyTemplateId
from sidestage.fixtures.loader import SellerCatalog
from sidestage.marketplace.authority import SellerAuthority
from sidestage.trace.recorder import TraceRecorder, TraceStage


class PipelineStatus(str, Enum):
    COMPLETED = "completed"
    EXITED = "exited"
    FAILED = "failed"


class RawCustomerReplyEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    authority: SellerAuthority
    customer_display_name: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=48)
    ]
    raw_text: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=240)]
    input_origin: Literal["prepared", "custom"]


class PipelineLatency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    boundary: Literal[
        "early_exit",
        "r2_inbox_sse",
        "r3_reply_commit_sse",
    ]
    queue_ms: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    total_ms: Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
    slo_target_ms: Literal[2000] = 2000
    hard_timeout_ms: Literal[5000] = 5000
    slo_missed: bool
    hard_timeout_outcome: bool


class PipelineResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    trace_id: str
    status: PipelineStatus
    event_id: Optional[str] = None
    question_id: Optional[str] = None
    reason_code: str
    broker_decision: Optional[BrokerDecision] = None
    publication: Optional[Dict[str, Any]] = None
    latency: Optional[PipelineLatency] = None
    runtime_selection: Optional[RuntimeSelection] = None
    sample_phase: Optional[Literal["cold", "steady"]] = None


@dataclass(frozen=True)
class PipelineServices:
    catalog: SellerCatalog
    ingestor: Any
    router: Any
    analyzer: Any
    retriever: Any
    reply_agent: Any
    broker: Any
    result_handler: Any
    trace_recorder: TraceRecorder
    wall_clock: Callable[[], datetime]
    monotonic: Callable[[], float]
    work_scheduler: Any = None
    trace_id_factory: Callable[[], str] = lambda: f"trc_{uuid4().hex}"
    hard_timeout_s: float = 5.0
    workflow: Optional[TemplateWorkflow | TwoCallWorkflow] = None
    runtime_catalog: Optional[RuntimeCatalog] = None
    runtime_selector: Optional[RuntimeSelector] = None


async def process_customer_reply(
    raw_event: RawCustomerReplyEvent,
    services: PipelineServices,
) -> PipelineResult:
    """Run the approved eight stages directly, without a workflow abstraction."""

    trace_id = services.trace_id_factory()
    pipeline_started = services.monotonic()
    deadline = pipeline_started + services.hard_timeout_s
    accepted_monotonic_s: Optional[float] = None
    work_ticket = None
    queue_ms = 0.0
    runtime_selection: Optional[RuntimeSelection] = None
    context: dict[str, Any] = {
        "trace_id": trace_id,
        "seller_id": raw_event.authority.seller_id,
        "show_id": raw_event.authority.show_id,
    }
    selected_workflow = services.workflow
    template_workflow = (
        selected_workflow if isinstance(selected_workflow, TemplateWorkflow) else None
    )
    two_call_workflow = (
        selected_workflow if isinstance(selected_workflow, TwoCallWorkflow) else None
    )

    def configure_runtime(selection: RuntimeSelection) -> None:
        nonlocal runtime_selection, selected_workflow, template_workflow, two_call_workflow
        runtime_selection = selection
        selected_workflow = services.runtime_catalog.resolve(
            runtime_selection.workflow_id,
            runtime_selection.model_profile_id,
        ).workflow
        context.update(
            {
                "workflow_id": runtime_selection.workflow_id,
                "model_profile_id": runtime_selection.model_profile_id,
                "selection_version": runtime_selection.selection_version,
            }
        )
        template_workflow = (
            selected_workflow if isinstance(selected_workflow, TemplateWorkflow) else None
        )
        two_call_workflow = (
            selected_workflow if isinstance(selected_workflow, TwoCallWorkflow) else None
        )
        context["workflow_strategy"] = (
            "one_call_template" if template_workflow is not None else "two_call_draft"
        )

    context["workflow_strategy"] = (
        "one_call_template" if template_workflow is not None else "two_call_draft"
    )

    def claim_model_sample(question_id: str) -> Optional[str]:
        if runtime_selection is None or services.runtime_selector is None:
            return None
        sample_phase = services.runtime_selector.claim_model_sample(runtime_selection)
        context["sample_phase"] = sample_phase
        services.router.record_runtime_execution(
            question_id,
            sample_phase=sample_phase,
        )
        return sample_phase

    def record_resolved_model(question_id: str, result) -> None:
        if runtime_selection is None or context.get("sample_phase") is None:
            return
        metadata_value = result.provider_metadata
        metadata = (
            metadata_value.to_dict()
            if hasattr(metadata_value, "to_dict")
            else dict(metadata_value)
        )
        services.router.record_runtime_execution(
            question_id,
            sample_phase=context["sample_phase"],
            resolved_model_id=metadata.get("resolved_model_id") or result.model_id,
            resolved_provider=metadata.get("resolved_provider"),
        )

    def skip_after(stage: TraceStage, reason_code: str) -> None:
        stages = list(TraceStage)
        for downstream in stages[stages.index(stage) + 1 :]:
            services.trace_recorder.skip(
                downstream,
                **context,
                reason_code=reason_code,
                verdict="skipped",
            )

    def skip_work_after(stage: TraceStage, reason_code: str) -> None:
        """Skip dependent work stages while reserving RESULT for a safe card outcome."""

        stages = list(TraceStage)
        for downstream in stages[stages.index(stage) + 1 :]:
            if downstream is TraceStage.RESULT:
                continue
            services.trace_recorder.skip(
                downstream,
                **context,
                reason_code=reason_code,
                verdict="skipped",
            )

    async def publish_terminal(routing, reason_code: str, *, no_response: bool = False):
        result_span = services.trace_recorder.start(
            TraceStage.RESULT,
            **context,
            input_ref=f"terminal:{reason_code}",
        )
        try:
            if no_response:
                publication = await services.result_handler.handle_no_response(
                    event,
                    routing,
                    reason_code,
                )
            else:
                publication = await services.result_handler.handle_failure(
                    event,
                    routing,
                    reason_code,
                )
        except Exception:
            result_span.failed(
                reason_code="result_persistence_failed",
                verdict="failed",
            )
            return None, True
        services.trace_recorder.artifact(
            TraceStage.RESULT,
            trace_id=trace_id,
            artifact_kind="publication",
            payload=publication,
        )
        result_span.completed(
            output_ref=routing.question_id,
            verdict="published",
            reason_code=reason_code,
        )
        return publication, False

    def finalize(result: PipelineResult) -> PipelineResult:
        nonlocal work_ticket
        if work_ticket is not None and services.work_scheduler is not None:
            services.work_scheduler.release(work_ticket)
            work_ticket = None
        result = result.model_copy(
            update={
                "runtime_selection": runtime_selection,
                "sample_phase": context.get("sample_phase"),
            }
        )
        if accepted_monotonic_s is None:
            return result
        total_ms = max(0.0, (services.monotonic() - accepted_monotonic_s) * 1_000)
        state = (result.publication or {}).get("state")
        boundary = (
            "r3_reply_commit_sse"
            if state == "auto_answered"
            else "r2_inbox_sse"
            if state in {"awaiting_review", "needs_seller"}
            else "early_exit"
        )
        latency = PipelineLatency(
            boundary=boundary,
            queue_ms=queue_ms,
            total_ms=total_ms,
            slo_missed=total_ms > 2_000,
            hard_timeout_outcome=result.reason_code == "hard_timeout",
        )
        services.trace_recorder.artifact(
            TraceStage.RESULT,
            trace_id=trace_id,
            artifact_kind="end_to_end_latency",
            payload={
                **latency.model_dump(mode="json"),
                "workflow_id": context.get("workflow_id"),
                "model_profile_id": context.get("model_profile_id"),
                "selection_version": context.get("selection_version"),
                "sample_phase": context.get("sample_phase"),
            },
        )
        return result.model_copy(update={"latency": latency})

    # 1. Authoritative ingestion.
    span = None
    try:
        if services.runtime_catalog is not None and services.runtime_selector is not None:
            with services.runtime_selector.acceptance(raw_event.authority) as selection:
                configure_runtime(selection)
                span = services.trace_recorder.start(
                    TraceStage.INGEST,
                    **context,
                    input_ref=f"raw:{raw_event.input_origin}",
                )
                event = services.ingestor.ingest(
                    raw_event.authority,
                    customer_display_name=raw_event.customer_display_name,
                    raw_text=raw_event.raw_text,
                    input_origin=raw_event.input_origin,
                    trace_id=trace_id,
                    runtime_selection=runtime_selection,
                )
        else:
            span = services.trace_recorder.start(
                TraceStage.INGEST,
                **context,
                input_ref=f"raw:{raw_event.input_origin}",
            )
            event = services.ingestor.ingest(
                raw_event.authority,
                customer_display_name=raw_event.customer_display_name,
                raw_text=raw_event.raw_text,
                input_origin=raw_event.input_origin,
                trace_id=trace_id,
                runtime_selection=runtime_selection,
            )
    except Exception:
        if span is not None:
            span.failed(reason_code="ingest_failed", verdict="failed")
        skip_after(TraceStage.INGEST, "ingest_failed")
        return finalize(PipelineResult(
            trace_id=trace_id,
            status=PipelineStatus.FAILED,
            reason_code="ingest_failed",
        ))
    context["event_id"] = event.event_id
    accepted_monotonic_s = services.monotonic()
    deadline = accepted_monotonic_s + services.hard_timeout_s
    span.completed(
        event_id=event.event_id,
        output_ref=event.event_id,
        verdict="accepted",
    )
    if runtime_selection is not None:
        services.trace_recorder.artifact(
            TraceStage.INGEST,
            trace_id=trace_id,
            artifact_kind="runtime_selection",
            payload=runtime_selection.model_dump(mode="json"),
        )

    # 2. Normalization and exact/normalization-equivalent deduplication.
    span = services.trace_recorder.start(
        TraceStage.NORMALIZE_DEDUPLICATE,
        **context,
        input_ref=event.event_id,
    )
    try:
        normalized = services.router.normalize_and_deduplicate(event)
    except Exception:
        span.failed(reason_code="normalization_failed", verdict="failed")
        skip_after(TraceStage.NORMALIZE_DEDUPLICATE, "normalization_failed")
        return finalize(PipelineResult(
            trace_id=trace_id,
            status=PipelineStatus.FAILED,
            event_id=event.event_id,
            reason_code="normalization_failed",
        ))
    context["question_id"] = normalized.question_id
    span.completed(
        question_id=normalized.question_id,
        output_ref=normalized.question_id,
        verdict="normalized",
    )

    # 3. Deterministic route and immutable temporal binding.
    span = services.trace_recorder.start(
        TraceStage.DETERMINISTIC_ROUTE,
        **context,
        input_ref=normalized.question_id,
    )
    try:
        routing = services.router.route(normalized)
    except Exception:
        span.failed(reason_code="routing_failed", verdict="failed")
        skip_after(TraceStage.DETERMINISTIC_ROUTE, "routing_failed")
        return finalize(PipelineResult(
            trace_id=trace_id,
            status=PipelineStatus.FAILED,
            event_id=event.event_id,
            question_id=normalized.question_id,
            reason_code="routing_failed",
        ))
    services.trace_recorder.artifact(
        TraceStage.DETERMINISTIC_ROUTE,
        trace_id=trace_id,
        artifact_kind="routing_decision",
        payload=routing.model_dump(mode="json"),
    )
    if not routing.should_process:
        span.exited(
            output_ref=f"route:{routing.route.value}",
            verdict="exited",
            reason_code=routing.reason_code,
        )
        skip_after(TraceStage.DETERMINISTIC_ROUTE, routing.reason_code)
        return finalize(PipelineResult(
            trace_id=trace_id,
            status=PipelineStatus.EXITED,
            event_id=event.event_id,
            question_id=routing.question_id,
            reason_code=routing.reason_code,
        ))
    span.completed(
        output_ref=f"route:{routing.route.value}",
        verdict=routing.route.value,
        reason_code=routing.reason_code,
    )

    if services.work_scheduler is not None:
        try:
            work_ticket = await services.work_scheduler.acquire(
                event.show_id,
                deadline=deadline,
            )
        except WorkQueueFullError:
            reason = "capacity_exceeded"
            skip_work_after(TraceStage.DETERMINISTIC_ROUTE, reason)
            publication, persistence_failed = await publish_terminal(routing, reason)
            return finalize(PipelineResult(
                trace_id=trace_id,
                status=PipelineStatus.FAILED,
                event_id=event.event_id,
                question_id=routing.question_id,
                reason_code="result_persistence_failed" if persistence_failed else reason,
                publication=publication,
            ))
        except WorkQueueDeadlineError:
            reason = "hard_timeout"
            skip_work_after(TraceStage.DETERMINISTIC_ROUTE, reason)
            publication, persistence_failed = await publish_terminal(routing, reason)
            return finalize(PipelineResult(
                trace_id=trace_id,
                status=PipelineStatus.FAILED,
                event_id=event.event_id,
                question_id=routing.question_id,
                reason_code="result_persistence_failed" if persistence_failed else reason,
                publication=publication,
            ))
        queue_ms = work_ticket.queue_ms
        current_task = asyncio.current_task()
        if current_task is not None:
            current_task.add_done_callback(
                lambda _task, ticket=work_ticket: services.work_scheduler.release(ticket)
            )
        scheduler_state = services.work_scheduler.snapshot()
        services.trace_recorder.artifact(
            TraceStage.LLM_ANALYSIS,
            trace_id=trace_id,
            artifact_kind="queue_admission",
            payload={
                "queue_ms": queue_ms,
                "depth_at_enqueue": work_ticket.depth_at_enqueue,
                "per_show_capacity": scheduler_state["per_show_capacity"],
                "per_show_concurrency": scheduler_state["per_show_concurrency"],
                "global_concurrency": scheduler_state["global_concurrency"],
            },
        )

    # 4. Workflow 1 prepares a deterministic evidence plan; Workflow 2 invokes
    # its registered evidence-planner agent exactly once.
    if template_workflow is None:
        claim_model_sample(routing.question_id)
    span = services.trace_recorder.start(
        TraceStage.LLM_ANALYSIS,
        **context,
        input_ref=routing.question_id,
    )
    try:
        if template_workflow is not None:
            analysis = None
            planning_id = f"bundle_{routing.question_id}"
        else:
            analysis_input = AnalysisInput(
                question_id=routing.question_id,
                trace_id=trace_id,
                question=event.raw_text,
                bound_listing=routing.bound_listing,
                deadline_monotonic_s=deadline,
            )
            analyzer = (
                two_call_workflow.evidence_planner
                if two_call_workflow is not None
                else services.analyzer
            )
            analysis = await analyzer.analyze(analysis_input)
            planning_id = analysis.analysis_id
    except Exception:
        span.failed(reason_code="analysis_failed", verdict="failed")
        skip_work_after(TraceStage.LLM_ANALYSIS, "analysis_failed")
        publication, persistence_failed = await publish_terminal(
            routing,
            "analysis_failed",
        )
        return finalize(PipelineResult(
            trace_id=trace_id,
            status=PipelineStatus.FAILED,
            event_id=event.event_id,
            question_id=routing.question_id,
            reason_code=(
                "result_persistence_failed" if persistence_failed else "analysis_failed"
            ),
            publication=publication,
        ))
    context["analysis_call_id"] = planning_id
    if template_workflow is not None:
        services.trace_recorder.artifact(
            TraceStage.LLM_ANALYSIS,
            trace_id=trace_id,
            artifact_kind="deterministic_evidence_plan",
            payload={
                "planning_id": planning_id,
                "workflow_strategy": "one_call_template",
                "provider_call_count": 0,
            },
        )
        span.completed(
            analysis_call_id=planning_id,
            output_ref=planning_id,
            verdict="deterministic_bundle_planned",
        )
    else:
        record_resolved_model(routing.question_id, analysis)
        services.trace_recorder.artifact(
            TraceStage.LLM_ANALYSIS,
            trace_id=trace_id,
            artifact_kind="analysis_result",
            payload=analysis.model_dump(mode="json"),
        )
        if analysis.status is AnalysisStatus.FAILED:
            reason = analysis.failure.code.value
            span.failed(
                analysis_call_id=analysis.analysis_id,
                output_ref=analysis.analysis_id,
                verdict="failed",
                reason_code=reason,
            )
            skip_work_after(TraceStage.LLM_ANALYSIS, reason)
            publication, persistence_failed = await publish_terminal(routing, reason)
            return finalize(PipelineResult(
                trace_id=trace_id,
                status=PipelineStatus.FAILED,
                event_id=event.event_id,
                question_id=routing.question_id,
                reason_code="result_persistence_failed" if persistence_failed else reason,
                publication=publication,
            ))
        if analysis.request.intent is not AnalysisIntent.ANSWERABLE:
            reason = analysis.request.intent.value
            try:
                services.router.refine_route_after_analysis(
                    event,
                    routing.question_id,
                    analysis.request.intent,
                )
            except AttributeError:
                pass
            span.exited(
                analysis_call_id=analysis.analysis_id,
                output_ref=analysis.analysis_id,
                verdict="exited",
                reason_code=reason,
            )
            skip_work_after(TraceStage.LLM_ANALYSIS, reason)
            publication, persistence_failed = await publish_terminal(
                routing,
                reason,
                no_response=analysis.request.intent in {
                    AnalysisIntent.NO_RESPONSE_NEEDED,
                    AnalysisIntent.ADVERSARIAL,
                },
            )
            return finalize(PipelineResult(
                trace_id=trace_id,
                status=(PipelineStatus.FAILED if persistence_failed else PipelineStatus.EXITED),
                event_id=event.event_id,
                question_id=routing.question_id,
                reason_code="result_persistence_failed" if persistence_failed else reason,
                publication=publication,
            ))
        span.completed(
            analysis_call_id=analysis.analysis_id,
            output_ref=analysis.analysis_id,
            verdict="answerable",
        )

    # 5. Deterministic tenant-scoped retrieval and immutable snapshot.
    span = services.trace_recorder.start(
        TraceStage.EVIDENCE_RETRIEVAL,
        **context,
        input_ref=planning_id,
    )
    try:
        if template_workflow is not None:
            retrieval = services.retriever.retrieve_template_bundle(
                TemplateRetrievalContext(
                    question_id=routing.question_id,
                    trace_id=trace_id,
                    seller_id=event.seller_id,
                    show_id=event.show_id,
                    bound_listing=routing.bound_listing,
                    observed_at=services.wall_clock(),
                    question=event.raw_text,
                )
            )
        else:
            retrieval = services.retriever.retrieve(
                RetrievalContext(
                    question_id=routing.question_id,
                    trace_id=trace_id,
                    analysis_id=analysis.analysis_id,
                    seller_id=event.seller_id,
                    show_id=event.show_id,
                    bound_listing=routing.bound_listing,
                    observed_at=services.wall_clock(),
                    question=event.raw_text,
                ),
                analysis.request,
            )
    except Exception:
        span.failed(reason_code="retrieval_failed", verdict="failed")
        skip_work_after(TraceStage.EVIDENCE_RETRIEVAL, "retrieval_failed")
        publication, persistence_failed = await publish_terminal(
            routing,
            "retrieval_failed",
        )
        return finalize(PipelineResult(
            trace_id=trace_id,
            status=PipelineStatus.FAILED,
            event_id=event.event_id,
            question_id=routing.question_id,
            reason_code=(
                "result_persistence_failed" if persistence_failed else "retrieval_failed"
            ),
            publication=publication,
        ))
    services.trace_recorder.artifact(
        TraceStage.EVIDENCE_RETRIEVAL,
        trace_id=trace_id,
        artifact_kind="retrieval_result",
        payload=retrieval.model_dump(mode="json"),
    )
    if retrieval.status is RetrievalStatus.FAILED:
        reason = retrieval.failure.code.value
        span.failed(reason_code=reason, verdict="failed")
        skip_work_after(TraceStage.EVIDENCE_RETRIEVAL, reason)
        publication, persistence_failed = await publish_terminal(routing, reason)
        return finalize(PipelineResult(
            trace_id=trace_id,
            status=PipelineStatus.FAILED,
            event_id=event.event_id,
            question_id=routing.question_id,
            reason_code="result_persistence_failed" if persistence_failed else reason,
            publication=publication,
        ))
    snapshot = retrieval.snapshot
    services.trace_recorder.artifact(
        TraceStage.EVIDENCE_RETRIEVAL,
        trace_id=trace_id,
        artifact_kind="evidence_snapshot",
        payload=snapshot.model_dump(mode="json"),
    )
    context["snapshot_id"] = snapshot.snapshot_id
    span.completed(
        snapshot_id=snapshot.snapshot_id,
        output_ref=snapshot.snapshot_id,
        verdict="grounded",
    )

    # 6. Startup-registered M3A reply-agent handle.
    seller = services.catalog.seller(event.seller_id)
    tone = ReplyTone(
        voice=seller.tone.voice,
        max_reply_chars=seller.tone.max_reply_chars,
        emoji_mode=seller.tone.emoji_mode,
        prohibited_phrases=seller.tone.prohibited_phrases,
    )
    if template_workflow is not None:
        agent_task = TemplateSelectionTask(
            question_id=routing.question_id,
            trace_id=trace_id,
            seller_id=event.seller_id,
            show_id=event.show_id,
            asked_at=_parse_utc(event.accepted_at),
            deadline_monotonic_s=deadline,
            question=event.raw_text,
            bound_listing=routing.bound_listing,
            evidence_snapshot=snapshot,
            tone=tone,
        )
        reply_agent = template_workflow.evidence_template_agent
    else:
        agent_task = ReplyTask(
            question_id=routing.question_id,
            trace_id=trace_id,
            analysis_id=analysis.analysis_id,
            seller_id=event.seller_id,
            show_id=event.show_id,
            asked_at=_parse_utc(event.accepted_at),
            deadline_monotonic_s=deadline,
            question=event.raw_text,
            bound_listing=routing.bound_listing,
            evidence_snapshot=snapshot,
            answer_category=analysis.request.answer_category,
            tone=tone,
        )
        reply_agent = (
            two_call_workflow.reply_drafter_agent
            if two_call_workflow is not None
            else services.reply_agent
        )
    if template_workflow is not None:
        claim_model_sample(routing.question_id)
    span = services.trace_recorder.start(
        TraceStage.REPLY_AGENT,
        **context,
        input_ref=snapshot.snapshot_id,
    )
    try:
        agent_result = await reply_agent.run(agent_task)
    except Exception:
        span.failed(reason_code="agent_not_registered", verdict="failed")
        skip_work_after(TraceStage.REPLY_AGENT, "agent_not_registered")
        publication, persistence_failed = await publish_terminal(
            routing,
            "agent_not_registered",
        )
        return finalize(PipelineResult(
            trace_id=trace_id,
            status=PipelineStatus.FAILED,
            event_id=event.event_id,
            question_id=routing.question_id,
            reason_code=(
                "result_persistence_failed"
                if persistence_failed
                else "agent_not_registered"
            ),
            publication=publication,
        ))
    context["agent_run_id"] = agent_result.run_id
    context["profile_digest"] = agent_result.profile_digest
    record_resolved_model(routing.question_id, agent_result)
    services.trace_recorder.artifact(
        TraceStage.REPLY_AGENT,
        trace_id=trace_id,
        artifact_kind="agent_run_result",
        payload=agent_result.model_dump(mode="json"),
    )
    if agent_result.status is not RunStatus.SUCCEEDED:
        reason = agent_result.failure.code.value
        span.failed(
            agent_run_id=agent_result.run_id,
            profile_digest=agent_result.profile_digest,
            output_ref=agent_result.run_id,
            verdict="failed",
            reason_code=reason,
        )
        skip_work_after(TraceStage.REPLY_AGENT, reason)
        publication, persistence_failed = await publish_terminal(routing, reason)
        return finalize(PipelineResult(
            trace_id=trace_id,
            status=PipelineStatus.FAILED,
            event_id=event.event_id,
            question_id=routing.question_id,
            reason_code="result_persistence_failed" if persistence_failed else reason,
            publication=publication,
        ))
    template_selection = None
    rendered_template = None
    if template_workflow is not None:
        try:
            template_selection = decode_template_selection(agent_result)
            if template_selection.template_id in {
                ReplyTemplateId.NEEDS_SELLER,
                ReplyTemplateId.NO_RESPONSE,
            }:
                intent_by_reason = {
                    "ambiguous_question": AnalysisIntent.AMBIGUOUS,
                    "unsupported_request": AnalysisIntent.UNSUPPORTED,
                    "prompt_injection": AnalysisIntent.ADVERSARIAL,
                    "no_response_needed": AnalysisIntent.NO_RESPONSE_NEEDED,
                }
                refined_intent = intent_by_reason.get(
                    template_selection.reason_code.value
                )
                if refined_intent is not None:
                    try:
                        services.router.refine_route_after_analysis(
                            event,
                            routing.question_id,
                            refined_intent,
                        )
                    except AttributeError:
                        pass
            if template_selection.template_id not in {
                ReplyTemplateId.NEEDS_SELLER,
                ReplyTemplateId.NO_RESPONSE,
            }:
                rendered_template = render_approved_template(
                    template_selection,
                    agent_task,
                )
        except (ValueError, TemplateRenderError):
            reason = "template_render_failed"
            span.failed(
                agent_run_id=agent_result.run_id,
                profile_digest=agent_result.profile_digest,
                output_ref=agent_result.run_id,
                verdict="failed",
                reason_code=reason,
            )
            skip_work_after(TraceStage.REPLY_AGENT, reason)
            publication, persistence_failed = await publish_terminal(routing, reason)
            return finalize(PipelineResult(
                trace_id=trace_id,
                status=PipelineStatus.FAILED,
                event_id=event.event_id,
                question_id=routing.question_id,
                reason_code="result_persistence_failed" if persistence_failed else reason,
                publication=publication,
            ))
    span.completed(
        agent_run_id=agent_result.run_id,
        profile_digest=agent_result.profile_digest,
        output_ref=agent_result.run_id,
        verdict="terminal_validated",
    )

    # 7. Application-owned authorization and guardrails.
    span = services.trace_recorder.start(
        TraceStage.BROKER_GUARDRAILS,
        **context,
        input_ref=agent_result.run_id,
    )
    try:
        if template_workflow is not None:
            broker_decision = services.broker.evaluate_template(
                template_selection,
                rendered_template,
                routing,
                snapshot,
            )
        else:
            broker_decision = services.broker.evaluate(agent_result, routing, snapshot)
    except Exception:
        span.failed(reason_code="broker_failed", verdict="failed")
        skip_work_after(TraceStage.BROKER_GUARDRAILS, "broker_failed")
        publication, persistence_failed = await publish_terminal(
            routing,
            "broker_failed",
        )
        return finalize(PipelineResult(
            trace_id=trace_id,
            status=PipelineStatus.FAILED,
            event_id=event.event_id,
            question_id=routing.question_id,
            reason_code=(
                "result_persistence_failed" if persistence_failed else "broker_failed"
            ),
            publication=publication,
        ))
    span.completed(
        output_ref=f"broker:{broker_decision.outcome.value}",
        verdict=broker_decision.outcome.value,
        reason_code=broker_decision.reason_code,
    )
    services.trace_recorder.artifact(
        TraceStage.BROKER_GUARDRAILS,
        trace_id=trace_id,
        artifact_kind="broker_decision",
        payload=broker_decision.model_dump(mode="json"),
    )

    # 8. Persist/publish the broker-selected outcome.
    span = services.trace_recorder.start(
        TraceStage.RESULT,
        **context,
        input_ref=f"broker:{broker_decision.outcome.value}",
    )
    try:
        publication = await services.result_handler.handle(
            event,
            routing,
            snapshot,
            broker_decision,
        )
    except Exception:
        span.failed(reason_code="result_persistence_failed", verdict="failed")
        return finalize(PipelineResult(
            trace_id=trace_id,
            status=PipelineStatus.FAILED,
            event_id=event.event_id,
            question_id=routing.question_id,
            reason_code="result_persistence_failed",
            broker_decision=broker_decision,
        ))
    span.completed(
        output_ref=routing.question_id,
        verdict="published",
        reason_code=broker_decision.reason_code,
    )
    services.trace_recorder.artifact(
        TraceStage.RESULT,
        trace_id=trace_id,
        artifact_kind="publication",
        payload=publication,
    )
    return finalize(PipelineResult(
        trace_id=trace_id,
        status=PipelineStatus.COMPLETED,
        event_id=event.event_id,
        question_id=routing.question_id,
        reason_code=broker_decision.reason_code,
        broker_decision=broker_decision,
        publication=publication,
    ))


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("accepted_at must be timezone-aware")
    return parsed
