"""Public contracts for SideStage's domain-neutral static agent core."""

from sidestage.agent_core.contracts import (
    AgentProfile,
    AgentRunResult,
    AgentTask,
    CoreFailure,
    CoreFailureCode,
    DeadlinePolicy,
    LatencyBreakdown,
    ModelRequestProjection,
    QueuePolicy,
    RunStatus,
    TerminalIntent,
    TerminalToolSchema,
)
from sidestage.agent_core.profile import (
    AgentProfileRegistry,
    AgentProfileValidationError,
    AgentTaskValidationError,
    RegisteredAgentProfile,
    UnknownAgentProfileError,
    register_profile,
)

__all__ = [
    "AgentProfile",
    "AgentProfileRegistry",
    "AgentProfileValidationError",
    "AgentRunResult",
    "AgentTask",
    "AgentTaskValidationError",
    "CoreFailure",
    "CoreFailureCode",
    "DeadlinePolicy",
    "LatencyBreakdown",
    "ModelRequestProjection",
    "QueuePolicy",
    "RegisteredAgentProfile",
    "RunStatus",
    "TerminalIntent",
    "TerminalToolSchema",
    "UnknownAgentProfileError",
    "register_profile",
]
