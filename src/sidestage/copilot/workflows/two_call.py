"""Startup registration for the two-call planner/retrieval/drafter workflow."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Optional

from sidestage.agent_core import ModelRunner, TraceSink
from sidestage.copilot.analysis import (
    EvidencePlannerAgent,
    MessageAnalyzer,
    register_evidence_planner_agent,
)
from sidestage.copilot.profile import LivesellReplyAgent, register_livesell_reply_agent


@dataclass(frozen=True)
class TwoCallWorkflow:
    """The two distinct registered model handles available to Workflow 2."""

    evidence_planner_agent: EvidencePlannerAgent
    evidence_planner: MessageAnalyzer
    reply_drafter_agent: LivesellReplyAgent


def register_two_call_workflow(
    model_runner: ModelRunner,
    *,
    model_config_ref: str,
    monotonic: Callable[[], float] = time.monotonic,
    trace_sink: Optional[TraceSink] = None,
) -> TwoCallWorkflow:
    """Register only the planner and drafter agents before chat acceptance."""

    planner_agent = register_evidence_planner_agent(
        model_runner,
        model_config_ref=model_config_ref,
        monotonic=monotonic,
        trace_sink=trace_sink,
    )
    return TwoCallWorkflow(
        evidence_planner_agent=planner_agent,
        evidence_planner=MessageAnalyzer(planner_agent),
        reply_drafter_agent=register_livesell_reply_agent(
            model_runner,
            model_config_ref=model_config_ref,
            monotonic=monotonic,
            trace_sink=trace_sink,
        ),
    )
