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
from sidestage.agent_core.core import StaticAgentCore
from sidestage.agent_core.model import (
    ModelInvocation,
    ModelResponse,
    ModelRunner,
    ModelRunnerError,
    ModelTerminalCall,
    OpenAICompatibleModelConfig,
    OpenAICompatibleModelRunner,
    ScriptedModelRunner,
)
from sidestage.agent_core.terminal import (
    TerminalResponseError,
    decode_terminal_response,
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
    "ModelInvocation",
    "ModelRequestProjection",
    "ModelResponse",
    "ModelRunner",
    "ModelRunnerError",
    "ModelTerminalCall",
    "OpenAICompatibleModelConfig",
    "OpenAICompatibleModelRunner",
    "QueuePolicy",
    "RegisteredAgentProfile",
    "RunStatus",
    "ScriptedModelRunner",
    "StaticAgentCore",
    "TerminalIntent",
    "TerminalResponseError",
    "TerminalToolSchema",
    "UnknownAgentProfileError",
    "decode_terminal_response",
    "register_profile",
]
