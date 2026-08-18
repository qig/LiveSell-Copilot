"""Startup registration for the one-call evidence-and-template workflow."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Optional

from sidestage.agent_core import ModelRunner, TraceSink
from sidestage.copilot.profile import LivesellReplyAgent, register_livesell_template_agent


@dataclass(frozen=True)
class TemplateWorkflow:
    """The only model handle available to Workflow 1."""

    evidence_template_agent: LivesellReplyAgent


def register_template_workflow(
    model_runner: ModelRunner,
    *,
    model_config_ref: str,
    monotonic: Callable[[], float] = time.monotonic,
    trace_sink: Optional[TraceSink] = None,
) -> TemplateWorkflow:
    """Register only the one-call evidence/template agent before chat acceptance."""

    return TemplateWorkflow(
        evidence_template_agent=register_livesell_template_agent(
            model_runner,
            model_config_ref=model_config_ref,
            monotonic=monotonic,
            trace_sink=trace_sink,
        )
    )
