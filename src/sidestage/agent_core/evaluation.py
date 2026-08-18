"""Deterministic, domain-neutral generation and evaluation for the static agent core."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import heapq
import json
import math
import os
from pathlib import Path
import random
import subprocess
import time
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from pydantic import SecretStr, ValidationError

from sidestage.agent_core.contracts import (
    AgentProfile,
    AgentRunResult,
    AgentTask,
    CoreFailureCode,
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
)
from sidestage.agent_core.profile import (
    AgentProfileRegistry,
    AgentTaskValidationError,
    register_profile,
)
from sidestage.agent_core.trace import (
    CoreTraceEvent,
    CoreTraceEventType,
    InMemoryTraceSink,
    SafeTraceEmitter,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GENERATOR_VERSION = "agent-core-generator-v1"
SCRIPTED_MODEL_ID = "scripted-agent-core-v1"
MANIFEST_SCHEMA = "sidestage.agent_core.manifest.v1"
EVENT_SCHEMA = "sidestage.agent_core.event.v1"
ORACLE_SCHEMA = "sidestage.agent_core.oracle.v1"
EVALUATION_SCHEMA = "sidestage.agent_core.evaluation.v1"
REPLAY_SCHEMA = "sidestage.agent_core.replay.v1"
_TERMINAL_FAILURES = {
    CoreFailureCode.UNKNOWN_TOOL,
    CoreFailureCode.MISSING_TERMINAL_CALL,
    CoreFailureCode.MULTIPLE_TERMINAL_CALLS,
    CoreFailureCode.MALFORMED_ARGUMENTS,
}
_SCRIPTED_PROVIDER_CONDITIONS = {
    "abstain",
    "finish",
    "malformed_arguments",
    "missing_terminal_call",
    "multiple_terminal_calls",
    "provider_error",
    "unknown_tool",
}


class EvaluationArtifactError(ValueError):
    """A retained workload or replay artifact cannot be trusted."""


@dataclass(frozen=True)
class ProviderCondition:
    kind: str
    latency_ms: int

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "latency_ms": self.latency_ms}


@dataclass(frozen=True)
class ExpectedOutcome:
    provider_called: bool
    terminal_tool: Optional[str] = None
    failure_code: Optional[str] = None
    timeout_phase: Optional[str] = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"provider_called": self.provider_called}
        if self.terminal_tool is not None:
            result["terminal_tool"] = self.terminal_tool
        if self.failure_code is not None:
            result["failure_code"] = self.failure_code
        if self.timeout_phase is not None:
            result["timeout_phase"] = self.timeout_phase
        return result


@dataclass(frozen=True)
class PlannedTask:
    case_id: str
    at_ms: int
    cancel_at_ms: Optional[int]
    task: AgentTask
    input_digest: str
    provider_condition: ProviderCondition
    expected: ExpectedOutcome


@dataclass(frozen=True)
class GeneratedWorkload:
    scenario_path: Path
    profile: AgentProfile
    monotonic_base_s: float
    tasks: tuple[PlannedTask, ...]
    manifest: dict[str, object]
    oracle: dict[str, object]
    expected_dispatch_case_order: tuple[str, ...]
    core_budget_p95_ms: float
    trace_overhead_budget_ms_per_event: float


@dataclass
class _ProviderStart:
    order: int
    task_id: str
    case_id: str
    due_ms: int
    condition: ProviderCondition
    future: asyncio.Future[ModelResponse]


@dataclass(frozen=True)
class _Execution:
    results: tuple[AgentRunResult, ...]
    trace_events: tuple[CoreTraceEvent, ...]
    provider_called_task_ids: frozenset[str]
    dispatch_case_order: tuple[str, ...]
    effect_calls: int


class _FakeClock:
    def __init__(self, base_s: float) -> None:
        self.base_s = base_s
        self.value = base_s

    def __call__(self) -> float:
        return self.value

    def set_ms(self, at_ms: int) -> None:
        next_value = self.base_s + at_ms / 1_000
        if next_value + 1e-12 < self.value:
            raise RuntimeError("deterministic evaluation clock cannot move backwards")
        self.value = next_value

    def relative_ms(self) -> int:
        return int(round((self.value - self.base_s) * 1_000))


class _ScriptedEvaluationRunner:
    """Evaluator-owned conditions keyed by input digest, never by model-visible labels."""

    def __init__(
        self,
        plans_by_input_digest: Mapping[str, PlannedTask],
        *,
        clock: _FakeClock,
    ) -> None:
        self._plans = plans_by_input_digest
        self._clock = clock
        self._starts: list[_ProviderStart] = []
        self._next_order = 0
        self.provider_called_task_ids: set[str] = set()
        self.dispatch_case_order: list[str] = []
        self.effect_calls: list[object] = []

    async def run(self, invocation: ModelInvocation) -> ModelResponse:
        digest = _json_digest(invocation.request.model_input.to_dict())
        try:
            planned = self._plans[digest]
        except KeyError as exc:
            raise ModelRunnerError("scripted invocation has no evaluator condition") from exc
        self._next_order += 1
        future: asyncio.Future[ModelResponse] = asyncio.get_running_loop().create_future()
        self.provider_called_task_ids.add(planned.task.task_id)
        self.dispatch_case_order.append(planned.case_id)
        self._starts.append(
            _ProviderStart(
                order=self._next_order,
                task_id=planned.task.task_id,
                case_id=planned.case_id,
                due_ms=self._clock.relative_ms() + planned.provider_condition.latency_ms,
                condition=planned.provider_condition,
                future=future,
            )
        )
        return await future

    def drain_starts(self) -> tuple[_ProviderStart, ...]:
        starts = tuple(self._starts)
        self._starts.clear()
        return starts

    def complete(self, start: _ProviderStart) -> None:
        if start.future.done():
            return
        condition = start.condition.kind
        if condition == "provider_error":
            start.future.set_exception(ModelRunnerError("injected provider failure"))
            return
        start.future.set_result(_scripted_response(condition, start.task_id))

    def execute_effect(self, payload: object) -> None:
        self.effect_calls.append(payload)


class _CountingRunner:
    def __init__(
        self,
        runner: ModelRunner,
        plans_by_input_digest: Mapping[str, PlannedTask],
    ) -> None:
        self.runner = runner
        self._plans = plans_by_input_digest
        self.provider_called_task_ids: set[str] = set()
        self.dispatch_case_order: list[str] = []
        self.effect_calls: list[object] = []

    async def run(self, invocation: ModelInvocation) -> ModelResponse:
        digest = _json_digest(invocation.request.model_input.to_dict())
        planned = self._plans[digest]
        self.provider_called_task_ids.add(planned.task.task_id)
        self.dispatch_case_order.append(planned.case_id)
        return await self.runner.run(invocation)

    def execute_effect(self, payload: object) -> None:
        self.effect_calls.append(payload)


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _canonical_json_line(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_digest(value: object) -> str:
    canonical = _canonical_json_line(value).encode("utf-8")
    return f"sha256:{sha256(canonical).hexdigest()}"


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _reject_duplicate_object_keys(
    pairs: Iterable[Tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key is forbidden: {key}")
        result[key] = value
    return result


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_object_keys,
        )
    except (OSError, ValueError) as exc:
        raise EvaluationArtifactError(f"cannot load evaluation JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise EvaluationArtifactError(f"evaluation JSON must be an object: {path.name}")
    return value


def _require_int(value: object, *, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise EvaluationArtifactError(f"{label} must be an integer >= {minimum}")
    return value


def _require_finite_number(
    value: object,
    *,
    label: str,
    minimum: float = 0.0,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationArtifactError(f"{label} must be a finite number >= {minimum}")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise EvaluationArtifactError(f"{label} must be a finite number >= {minimum}")
    return result


def _sanitized_provider_base_url(value: Optional[str]) -> str:
    if value is None or not value:
        return "live-provider-not-configured"
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EvaluationArtifactError("live provider base URL must be absolute HTTP(S)")
    if parsed.username is not None or parsed.password is not None:
        raise EvaluationArtifactError("live provider base URL cannot contain credentials")
    if parsed.query or parsed.fragment:
        raise EvaluationArtifactError("live provider base URL cannot contain query or fragment")
    return value.rstrip("/")


def _expected_outcome(value: object, *, case_id: str) -> ExpectedOutcome:
    if not isinstance(value, dict):
        raise EvaluationArtifactError(f"case {case_id} expected outcome must be an object")
    terminal_tool = value.get("terminal_tool")
    failure_code = value.get("failure_code")
    if (terminal_tool is None) == (failure_code is None):
        raise EvaluationArtifactError(
            f"case {case_id} must expect exactly one terminal tool or failure code"
        )
    provider_called = value.get("provider_called")
    if not isinstance(provider_called, bool):
        raise EvaluationArtifactError(f"case {case_id} provider_called must be boolean")
    timeout_phase = value.get("timeout_phase")
    for label, candidate in (
        ("terminal_tool", terminal_tool),
        ("failure_code", failure_code),
        ("timeout_phase", timeout_phase),
    ):
        if candidate is not None and (not isinstance(candidate, str) or not candidate):
            raise EvaluationArtifactError(f"case {case_id} {label} must be nonempty text")
    return ExpectedOutcome(
        provider_called=provider_called,
        terminal_tool=terminal_tool,
        failure_code=failure_code,
        timeout_phase=timeout_phase,
    )


def _profile_from_contract(contract: Mapping[str, object]) -> AgentProfile:
    profile_data = contract.get("profile")
    if not isinstance(profile_data, dict):
        raise EvaluationArtifactError("agent-core contract must contain a profile object")
    try:
        profile = AgentProfile.model_validate_json(json.dumps(profile_data))
        register_profile(profile)
    except (ValidationError, ValueError) as exc:
        raise EvaluationArtifactError("agent-core profile is invalid") from exc
    return profile


def _git_metadata() -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return commit or "unknown", bool(status.strip())
    except (OSError, subprocess.SubprocessError):
        return "unknown", True


def generate_workload(
    scenario_path: Path,
    *,
    seed: int,
    model_mode: str,
    implementation_commit: Optional[str] = None,
    worktree_dirty: Optional[bool] = None,
) -> GeneratedWorkload:
    """Generate a bounded runtime workload and separate evaluator oracle."""

    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise EvaluationArtifactError("seed must be a nonnegative integer")
    if model_mode not in {"scripted", "live"}:
        raise EvaluationArtifactError("model mode must be scripted or live")
    scenario_path = scenario_path.resolve()
    scenario = _load_json_object(scenario_path)
    if scenario.get("schema_version") != "sidestage.agent_core.scenario.v1":
        raise EvaluationArtifactError("unsupported agent-core scenario schema")
    if scenario.get("generator_version") != GENERATOR_VERSION:
        raise EvaluationArtifactError("scenario generator version is not supported")
    scenario_id = scenario.get("scenario_id")
    if not isinstance(scenario_id, str) or not scenario_id:
        raise EvaluationArtifactError("scenario_id must be nonempty text")

    contract_name = scenario.get("contract_file")
    if not isinstance(contract_name, str) or not contract_name:
        raise EvaluationArtifactError("scenario contract_file must be nonempty text")
    contract_path = (scenario_path.parent / contract_name).resolve()
    if contract_path.parent != scenario_path.parent:
        raise EvaluationArtifactError("scenario contract_file must stay in its fixture directory")
    contract = _load_json_object(contract_path)
    if contract.get("schema_version") != "sidestage.agent_core.contract.v1":
        raise EvaluationArtifactError("unsupported agent-core contract schema")
    if contract.get("generator_version") != GENERATOR_VERSION:
        raise EvaluationArtifactError("contract generator version does not match scenario")
    profile = _profile_from_contract(contract)
    registered = register_profile(profile)

    fixed_clock = scenario.get("fixed_clock")
    if not isinstance(fixed_clock, dict):
        raise EvaluationArtifactError("scenario fixed_clock must be an object")
    fixed_wall_time = fixed_clock.get("wall_time")
    fixed_base = fixed_clock.get("monotonic_base_s")
    if not isinstance(fixed_wall_time, str) or not fixed_wall_time:
        raise EvaluationArtifactError("fixed wall time must be nonempty text")
    try:
        parsed_wall_time = datetime.fromisoformat(fixed_wall_time.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvaluationArtifactError("fixed wall time must be valid ISO 8601") from exc
    if (
        parsed_wall_time.tzinfo is None
        or parsed_wall_time.utcoffset() != timezone.utc.utcoffset(parsed_wall_time)
    ):
        raise EvaluationArtifactError("fixed wall time must be UTC")
    fixed_monotonic_base_s = _require_finite_number(
        fixed_base,
        label="fixed monotonic base",
    )
    monotonic_base_s = (
        fixed_monotonic_base_s if model_mode == "scripted" else time.monotonic()
    )

    raw_specs = scenario.get("tasks" if model_mode == "scripted" else "live_matrix")
    if not isinstance(raw_specs, list) or not raw_specs:
        raise EvaluationArtifactError(f"scenario has no {model_mode} task specifications")
    prompt_templates = contract.get("prompt_templates")
    topics = contract.get("topics")
    evidence_templates = contract.get("evidence_templates")
    values = contract.get("values")
    for label, pool in (
        ("prompt_templates", prompt_templates),
        ("topics", topics),
        ("evidence_templates", evidence_templates),
        ("values", values),
    ):
        if not isinstance(pool, list) or not pool or not all(isinstance(item, str) for item in pool):
            raise EvaluationArtifactError(f"contract {label} must be a nonempty text array")

    rng = random.Random(seed)
    tasks: list[PlannedTask] = []
    seen_cases: set[str] = set()
    seen_inputs: set[str] = set()
    for ordinal, raw_spec in enumerate(raw_specs, start=1):
        if not isinstance(raw_spec, dict):
            raise EvaluationArtifactError(f"task specification {ordinal} must be an object")
        case_id = raw_spec.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in seen_cases:
            raise EvaluationArtifactError(f"task specification {ordinal} has invalid case_id")
        seen_cases.add(case_id)
        at_ms = _require_int(raw_spec.get("at_ms"), label=f"case {case_id} at_ms")
        deadline_ms = _require_int(
            raw_spec.get("deadline_ms"),
            label=f"case {case_id} deadline_ms",
            minimum=1,
        )
        cancel_value = raw_spec.get("cancel_at_ms")
        cancel_at_ms = None
        if cancel_value is not None:
            cancel_at_ms = _require_int(cancel_value, label=f"case {case_id} cancel_at_ms")
            if cancel_at_ms < at_ms:
                raise EvaluationArtifactError(f"case {case_id} cancellation precedes arrival")
        expected = _expected_outcome(raw_spec.get("expected"), case_id=case_id)

        if model_mode == "scripted":
            raw_condition = raw_spec.get("provider_condition")
            if not isinstance(raw_condition, dict):
                raise EvaluationArtifactError(f"case {case_id} provider condition is missing")
            kind = raw_condition.get("kind")
            if not isinstance(kind, str) or kind not in _SCRIPTED_PROVIDER_CONDITIONS:
                raise EvaluationArtifactError(f"case {case_id} provider kind is invalid")
            latency_ms = _require_int(
                raw_condition.get("latency_ms"),
                label=f"case {case_id} provider latency",
            )
            condition = ProviderCondition(kind=kind, latency_ms=latency_ms)
            topic = rng.choice(topics)
            value = rng.choice(values)
            prompt = rng.choice(prompt_templates).format(ordinal=ordinal, topic=topic)
            if kind == "abstain":
                evidence: list[str] = []
            else:
                evidence = [
                    rng.choice(evidence_templates).format(
                        record=f"{ordinal:03d}-{index}",
                        topic=topic,
                        value=value,
                    )
                    for index in (1, 2)
                ]
            model_input = {"prompt": prompt, "evidence": evidence}
        else:
            raw_model_input = raw_spec.get("model_input")
            if not isinstance(raw_model_input, dict):
                raise EvaluationArtifactError(f"case {case_id} live model_input is missing")
            model_input = raw_model_input
            condition = ProviderCondition(kind="live", latency_ms=0)

        input_digest = _json_digest(model_input)
        if input_digest in seen_inputs:
            raise EvaluationArtifactError("generated model inputs must be unique")
        seen_inputs.add(input_digest)
        task_id = f"task-{seed}-{ordinal:03d}"
        task = AgentTask(
            task_id=task_id,
            adapter_id=profile.adapter_id,
            profile_version=profile.profile_version,
            profile_digest=registered.digest,
            deadline_monotonic_s=monotonic_base_s + (at_ms + deadline_ms) / 1_000,
            model_input=model_input,
            correlation_metadata={
                "scenario_id": scenario_id,
                "trace_id": f"trace-{seed}-{ordinal:03d}",
            },
        )
        try:
            registered.validate_task(
                task,
                now_monotonic_s=monotonic_base_s + at_ms / 1_000,
            )
        except AgentTaskValidationError as exc:
            raise EvaluationArtifactError(
                f"case {case_id} violates the registered agent profile"
            ) from exc
        tasks.append(
            PlannedTask(
                case_id=case_id,
                at_ms=at_ms,
                cancel_at_ms=cancel_at_ms,
                task=task,
                input_digest=input_digest,
                provider_condition=condition,
                expected=expected,
            )
        )

    scenario_digest = _json_digest(scenario)
    contract_digest = _json_digest(contract)
    if implementation_commit is None or worktree_dirty is None:
        detected_commit, detected_dirty = _git_metadata()
        if implementation_commit is None:
            implementation_commit = detected_commit
        if worktree_dirty is None:
            worktree_dirty = detected_dirty
    model_identifier = (
        SCRIPTED_MODEL_ID
        if model_mode == "scripted"
        else os.environ.get("SIDESTAGE_MODEL_ID", "live-model-not-configured")
    )
    model_metadata: dict[str, object] = {
        "mode": model_mode,
        "identifier": model_identifier,
        "config_ref": profile.model_config_ref,
    }
    if model_mode == "live":
        model_metadata["base_url"] = _sanitized_provider_base_url(
            os.environ.get("SIDESTAGE_MODEL_BASE_URL")
        )
        reasoning_effort = os.environ.get("SIDESTAGE_MODEL_REASONING_EFFORT")
        if reasoning_effort is not None:
            model_metadata["reasoning_effort"] = reasoning_effort
    run_material = f"{scenario_digest}:{registered.digest}:{seed}:{model_mode}"
    run_id = f"core-{sha256(run_material.encode('utf-8')).hexdigest()[:20]}"
    generated_at = (
        fixed_wall_time
        if model_mode == "scripted"
        else datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    )
    manifest: dict[str, object] = {
        "schema_version": MANIFEST_SCHEMA,
        "evaluation_scope": "agent_core",
        "generator_version": GENERATOR_VERSION,
        "scenario_id": scenario_id,
        "scenario_digest": scenario_digest,
        "contract_digest": contract_digest,
        "profile_version": profile.profile_version,
        "profile_digest": registered.digest,
        "seed": seed,
        "run_id": run_id,
        "generated_at": generated_at,
        "model": model_metadata,
        "clock": {
            "mode": "fixed" if model_mode == "scripted" else "live",
            "wall_time": generated_at,
            "monotonic_base_s": monotonic_base_s,
        },
        "queue_policy": profile.queue_policy.model_dump(mode="json"),
        "deadline_policy": profile.deadline_policy.model_dump(mode="json"),
        "task_count": len(tasks),
        "implementation_commit": implementation_commit,
        "worktree_dirty": bool(worktree_dirty),
    }
    oracle_tasks = {
        planned.task.task_id: {
            "case_id": planned.case_id,
            "at_ms": planned.at_ms,
            "cancel_at_ms": planned.cancel_at_ms,
            "input_digest": planned.input_digest,
            "provider_condition": planned.provider_condition.to_dict(),
            "expected": planned.expected.to_dict(),
        }
        for planned in tasks
    }
    expected_dispatch = scenario.get("expected_dispatch_case_order", [])
    if not isinstance(expected_dispatch, list) or not all(
        isinstance(item, str) for item in expected_dispatch
    ):
        raise EvaluationArtifactError("expected dispatch order must be a text array")
    oracle: dict[str, object] = {
        "schema_version": ORACLE_SCHEMA,
        "scenario_digest": scenario_digest,
        "seed": seed,
        "tasks": oracle_tasks,
        "expected_dispatch_case_order": expected_dispatch if model_mode == "scripted" else [],
    }
    core_budget = _require_finite_number(
        scenario.get("core_budget_p95_ms"),
        label="scenario core latency budget",
    )
    trace_budget = _require_finite_number(
        scenario.get("trace_overhead_budget_ms_per_event"),
        label="scenario trace overhead budget",
    )
    return GeneratedWorkload(
        scenario_path=scenario_path,
        profile=profile,
        monotonic_base_s=monotonic_base_s,
        tasks=tuple(tasks),
        manifest=manifest,
        oracle=oracle,
        expected_dispatch_case_order=tuple(expected_dispatch) if model_mode == "scripted" else (),
        core_budget_p95_ms=core_budget,
        trace_overhead_budget_ms_per_event=trace_budget,
    )


def _scripted_response(kind: str, task_id: str) -> ModelResponse:
    if kind == "finish":
        calls = (
            ModelTerminalCall(
                tool_name="finish",
                arguments_json=json.dumps(
                    {"answer": f"Supported generic conclusion for {task_id}."},
                    separators=(",", ":"),
                ),
            ),
        )
        return ModelResponse(model_id=SCRIPTED_MODEL_ID, terminal_calls=calls)
    if kind == "abstain":
        return ModelResponse(
            model_id=SCRIPTED_MODEL_ID,
            terminal_calls=(
                ModelTerminalCall(
                    tool_name="abstain",
                    arguments_json='{"reason":"insufficient_evidence"}',
                ),
            ),
        )
    if kind == "missing_terminal_call":
        return ModelResponse(model_id=SCRIPTED_MODEL_ID, text="no terminal result")
    if kind == "unknown_tool":
        return ModelResponse(
            model_id=SCRIPTED_MODEL_ID,
            terminal_calls=(ModelTerminalCall(tool_name="unregistered_tool", arguments_json="{}"),),
        )
    if kind == "multiple_terminal_calls":
        return ModelResponse(
            model_id=SCRIPTED_MODEL_ID,
            terminal_calls=(
                ModelTerminalCall(
                    tool_name="finish",
                    arguments_json='{"answer":"first"}',
                ),
                ModelTerminalCall(
                    tool_name="abstain",
                    arguments_json='{"reason":"insufficient_evidence"}',
                ),
            ),
        )
    if kind == "malformed_arguments":
        return ModelResponse(
            model_id=SCRIPTED_MODEL_ID,
            terminal_calls=(
                ModelTerminalCall(tool_name="finish", arguments_json='{"answer":7}'),
            ),
        )
    raise ModelRunnerError("scripted provider condition is not supported")


async def _settle_loop(turns: int = 12) -> None:
    for _ in range(turns):
        await asyncio.sleep(0)


async def _execute_scripted(workload: GeneratedWorkload) -> _Execution:
    clock = _FakeClock(workload.monotonic_base_s)
    sink = InMemoryTraceSink()
    by_digest = {planned.input_digest: planned for planned in workload.tasks}
    runner = _ScriptedEvaluationRunner(by_digest, clock=clock)
    ids = (f"run-{workload.manifest['seed']}-{index:03d}" for index in range(1, 1000))
    core = StaticAgentCore(
        registry=AgentProfileRegistry((workload.profile,)),
        model_runner=runner,
        monotonic=clock,
        id_factory=lambda: next(ids),
        trace_sink=sink,
    )
    tasks_by_case: dict[str, asyncio.Task[AgentRunResult]] = {}
    event_heap: list[tuple[int, int, int, str, object]] = []
    next_order = 0
    for planned in workload.tasks:
        next_order += 1
        heapq.heappush(event_heap, (planned.at_ms, 2, next_order, "arrival", planned))
        if planned.cancel_at_ms is not None:
            next_order += 1
            heapq.heappush(
                event_heap,
                (planned.cancel_at_ms, 1, next_order, "cancel", planned.case_id),
            )

    while event_heap:
        at_ms = event_heap[0][0]
        clock.set_ms(at_ms)
        batch: list[tuple[int, int, int, str, object]] = []
        while event_heap and event_heap[0][0] == at_ms:
            batch.append(heapq.heappop(event_heap))
        for _, _, _, event_kind, payload in batch:
            if event_kind == "provider_complete":
                runner.complete(payload)  # type: ignore[arg-type]
            elif event_kind == "cancel":
                task = tasks_by_case.get(str(payload))
                if task is not None and not task.done():
                    task.cancel()
            elif event_kind == "arrival":
                planned = payload
                if not isinstance(planned, PlannedTask):
                    raise RuntimeError("invalid deterministic arrival payload")
                tasks_by_case[planned.case_id] = asyncio.create_task(core.run(planned.task))
            else:
                raise RuntimeError(f"unknown deterministic event kind: {event_kind}")
        await _settle_loop()
        for start in runner.drain_starts():
            next_order += 1
            heapq.heappush(
                event_heap,
                (start.due_ms, 0, next_order, "provider_complete", start),
            )

    await _settle_loop()
    missing = [planned.case_id for planned in workload.tasks if planned.case_id not in tasks_by_case]
    if missing:
        raise RuntimeError(f"deterministic evaluator did not submit: {missing}")
    unfinished = [case_id for case_id, task in tasks_by_case.items() if not task.done()]
    if unfinished:
        raise RuntimeError(f"deterministic evaluator left unfinished tasks: {unfinished}")
    results = tuple(tasks_by_case[planned.case_id].result() for planned in workload.tasks)
    return _Execution(
        results=results,
        trace_events=sink.events,
        provider_called_task_ids=frozenset(runner.provider_called_task_ids),
        dispatch_case_order=tuple(runner.dispatch_case_order),
        effect_calls=len(runner.effect_calls),
    )


async def _execute_live(
    workload: GeneratedWorkload,
    runner: OpenAICompatibleModelRunner,
) -> _Execution:
    sink = InMemoryTraceSink()
    by_digest = {planned.input_digest: planned for planned in workload.tasks}
    counting = _CountingRunner(runner, by_digest)
    ids = (f"live-run-{index:03d}" for index in range(1, 1000))
    core = StaticAgentCore(
        registry=AgentProfileRegistry((workload.profile,)),
        model_runner=counting,
        id_factory=lambda: next(ids),
        trace_sink=sink,
    )
    started = time.monotonic()

    async def submit(planned: PlannedTask) -> AgentRunResult:
        delay_s = max(0.0, started + planned.at_ms / 1_000 - time.monotonic())
        if delay_s:
            await asyncio.sleep(delay_s)
        return await core.run(planned.task)

    try:
        results = tuple(await asyncio.gather(*(submit(planned) for planned in workload.tasks)))
    finally:
        await runner.aclose()
    return _Execution(
        results=results,
        trace_events=sink.events,
        provider_called_task_ids=frozenset(counting.provider_called_task_ids),
        dispatch_case_order=tuple(counting.dispatch_case_order),
        effect_calls=len(counting.effect_calls),
    )


def _run_execution(workload: GeneratedWorkload, model_mode: str) -> _Execution:
    if model_mode == "scripted":
        return asyncio.run(_execute_scripted(workload))
    required = {
        "base_url": os.environ.get("SIDESTAGE_MODEL_BASE_URL"),
        "api_key": os.environ.get("SIDESTAGE_MODEL_API_KEY"),
        "model_id": os.environ.get("SIDESTAGE_MODEL_ID"),
        "reasoning_effort": os.environ.get("SIDESTAGE_MODEL_REASONING_EFFORT"),
    }
    if not all(required.values()):
        raise EvaluationArtifactError(
            "live mode requires SIDESTAGE_MODEL_BASE_URL, SIDESTAGE_MODEL_API_KEY, "
            "and SIDESTAGE_MODEL_ID"
        )
    runner = OpenAICompatibleModelRunner(
        OpenAICompatibleModelConfig(
            config_ref=workload.profile.model_config_ref,
            base_url=str(required["base_url"]),
            api_key=SecretStr(str(required["api_key"])),
            model_id=str(required["model_id"]),
            request_timeout_s=15.0,
            reasoning_effort=required["reasoning_effort"],
        )
    )
    return asyncio.run(_execute_live(workload, runner))


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return float(ordered[rank - 1])


def _latency_metric(values: Iterable[float]) -> dict[str, object]:
    materialized = [float(value) for value in values]
    return {
        "count": len(materialized),
        "p50": _nearest_rank(materialized, 0.50),
        "p95": _nearest_rank(materialized, 0.95),
        "max": max(materialized, default=0.0),
    }


def _trace_overhead(
    trace_events: Sequence[CoreTraceEvent],
    *,
    budget_ms: float,
) -> dict[str, object]:
    if not trace_events:
        return {
            "sample_count": 0,
            "p50_ms_per_event": 0.0,
            "p95_ms_per_event": 0.0,
            "max_ms_per_event": 0.0,
            "budget_ms_per_event": budget_ms,
            "status": "not_measured",
        }
    sample = trace_events[0].model_dump(mode="python")
    sink = InMemoryTraceSink()
    emitter = SafeTraceEmitter(sink)
    durations: list[float] = []
    for _ in range(2_000):
        started = time.perf_counter_ns()
        emitter.emit(CoreTraceEvent.model_validate(sample))
        durations.append((time.perf_counter_ns() - started) / 1_000_000)
    p95 = _nearest_rank(durations, 0.95)
    return {
        "sample_count": len(durations),
        "p50_ms_per_event": _nearest_rank(durations, 0.50),
        "p95_ms_per_event": p95,
        "max_ms_per_event": max(durations),
        "budget_ms_per_event": budget_ms,
        "status": "pass" if p95 <= budget_ms else "miss",
    }


def _trace_types_by_task(
    events: Sequence[CoreTraceEvent],
) -> dict[str, list[CoreTraceEventType]]:
    grouped: dict[str, list[CoreTraceEventType]] = {}
    for event in events:
        grouped.setdefault(event.task_id, []).append(event.event_type)
    return grouped


def _trace_is_complete(
    result: AgentRunResult,
    event_types: Sequence[CoreTraceEventType],
    *,
    provider_called: bool,
) -> bool:
    if not event_types or event_types[0] is not CoreTraceEventType.TASK_ACCEPTED:
        return False
    if len(set(event_types)) != len(event_types):
        return False
    canonical_order = {
        event_type: index
        for index, event_type in enumerate(
            (
                CoreTraceEventType.TASK_ACCEPTED,
                CoreTraceEventType.TASK_QUEUED,
                CoreTraceEventType.PROVIDER_STARTED,
                CoreTraceEventType.PROVIDER_COMPLETED,
                CoreTraceEventType.TERMINAL_VALIDATED,
                CoreTraceEventType.RUN_COMPLETED,
                CoreTraceEventType.RUN_FAILED,
            )
        )
    }
    if any(
        canonical_order[current] >= canonical_order[following]
        for current, following in zip(event_types, event_types[1:])
    ):
        return False
    terminal_event = (
        CoreTraceEventType.RUN_COMPLETED
        if result.terminal_intent is not None
        else CoreTraceEventType.RUN_FAILED
    )
    if event_types[-1] is not terminal_event:
        return False
    failure_code = result.failure.code if result.failure is not None else None
    queued_expected = failure_code is not CoreFailureCode.QUEUE_FULL
    if (CoreTraceEventType.TASK_QUEUED in event_types) is not queued_expected:
        return False
    if provider_called:
        if CoreTraceEventType.PROVIDER_STARTED not in event_types:
            return False
        if CoreTraceEventType.PROVIDER_COMPLETED not in event_types:
            return False
    else:
        if CoreTraceEventType.PROVIDER_STARTED in event_types:
            return False
    if result.terminal_intent is not None:
        return CoreTraceEventType.TERMINAL_VALIDATED in event_types
    if failure_code in _TERMINAL_FAILURES:
        return CoreTraceEventType.TERMINAL_VALIDATED in event_types
    return CoreTraceEventType.TERMINAL_VALIDATED not in event_types


def _actual_outcome(result: AgentRunResult, *, provider_called: bool) -> dict[str, object]:
    actual: dict[str, object] = {"provider_called": provider_called}
    if result.terminal_intent is not None:
        actual["terminal_tool"] = result.terminal_intent.tool_name
    if result.failure is not None:
        actual["failure_code"] = result.failure.code.value
    return actual


def _expected_matches(expected: ExpectedOutcome, actual: Mapping[str, object]) -> bool:
    return (
        actual.get("provider_called") is expected.provider_called
        and actual.get("terminal_tool") == expected.terminal_tool
        and actual.get("failure_code") == expected.failure_code
    )


def _event_records(
    workload: GeneratedWorkload,
    execution: _Execution,
) -> list[dict[str, object]]:
    trace_types = _trace_types_by_task(execution.trace_events)
    accepted = [
        {
            "schema_version": EVENT_SCHEMA,
            "record_type": "task_accepted",
            "at_ms": planned.at_ms,
            "task": planned.task.model_dump(mode="json"),
        }
        for planned in workload.tasks
    ]
    ordinal = {planned.task.task_id: index for index, planned in enumerate(workload.tasks)}
    completed_results = sorted(
        execution.results,
        key=lambda result: (result.completed_monotonic_s, ordinal[result.task_id]),
    )
    completed = []
    for result in completed_results:
        completed.append(
            {
                "schema_version": EVENT_SCHEMA,
                "record_type": "task_completed",
                "task_id": result.task_id,
                "trace_id": result.trace_id,
                "status": result.status.value,
                "terminal_tool": (
                    result.terminal_intent.tool_name
                    if result.terminal_intent is not None
                    else None
                ),
                "failure_code": (
                    result.failure.code.value if result.failure is not None else None
                ),
                "model_id": result.model_id,
                "latency": result.latency.model_dump(mode="json"),
                "trace_event_types": [event.value for event in trace_types[result.task_id]],
            }
        )
    return accepted + completed


def _build_evaluation(
    workload: GeneratedWorkload,
    execution: _Execution,
    *,
    model_mode: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    planned_by_task = {planned.task.task_id: planned for planned in workload.tasks}
    trace_types = _trace_types_by_task(execution.trace_events)
    outcome_matches = 0
    complete_traces = 0
    terminal_counts: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()
    results: list[dict[str, object]] = []
    for result in execution.results:
        planned = planned_by_task[result.task_id]
        provider_called = result.task_id in execution.provider_called_task_ids
        actual = _actual_outcome(result, provider_called=provider_called)
        matches = _expected_matches(planned.expected, actual)
        outcome_matches += int(matches)
        trace_complete = _trace_is_complete(
            result,
            trace_types.get(result.task_id, []),
            provider_called=provider_called,
        )
        complete_traces += int(trace_complete)
        terminal_tool = actual.get("terminal_tool")
        failure_code = actual.get("failure_code")
        if isinstance(terminal_tool, str):
            terminal_counts[terminal_tool] += 1
        if isinstance(failure_code, str):
            failure_counts[failure_code] += 1
        results.append(
            {
                "task_id": result.task_id,
                "case_id": planned.case_id,
                "status": result.status.value,
                "terminal_tool": terminal_tool,
                "failure_code": failure_code,
                "provider_called": provider_called,
                "outcome_match": matches,
                "trace_complete": trace_complete,
                "latency": result.latency.model_dump(mode="json"),
            }
        )

    task_count = len(workload.tasks)
    compliant_outcomes = sum(
        int(result.terminal_intent is not None or result.failure is not None)
        for result in execution.results
    )
    latency = {
        field: _latency_metric(getattr(result.latency, field) for result in execution.results)
        for field in ("queue_ms", "provider_ms", "parse_ms", "total_ms")
    }
    total_p95 = float(latency["total_ms"]["p95"])
    budget = {
        "target_p95_ms": workload.core_budget_p95_ms,
        "measured_p95_ms": total_p95,
        "status": "pass" if total_p95 <= workload.core_budget_p95_ms else "miss",
    }
    expected_calls = sum(int(planned.expected.provider_called) for planned in workload.tasks)
    dispatch_expected = list(workload.expected_dispatch_case_order)
    evaluation: dict[str, object] = {
        "schema_version": EVALUATION_SCHEMA,
        "evaluation_scope": "agent_core",
        "evaluation_mode": model_mode,
        "run_id": workload.manifest["run_id"],
        "scenario_id": workload.manifest["scenario_id"],
        "scenario_digest": workload.manifest["scenario_digest"],
        "profile_digest": workload.manifest["profile_digest"],
        "seed": workload.manifest["seed"],
        "model_identifier": workload.manifest["model"]["identifier"],  # type: ignore[index]
        "task_count": task_count,
        "outcome_matches": outcome_matches,
        "terminal_contract_compliance": {
            "count": compliant_outcomes,
            "rate": (
                0.0
                if task_count == 0
                else round(compliant_outcomes / task_count, 6)
            ),
        },
        "provider_calls": {
            "actual": len(execution.provider_called_task_ids),
            "expected": expected_calls,
        },
        "effect_calls": execution.effect_calls,
        "complete_traces": {
            "count": complete_traces,
            "rate": 0.0 if task_count == 0 else round(complete_traces / task_count, 6),
        },
        "terminal_counts": dict(sorted(terminal_counts.items())),
        "failure_counts": dict(sorted(failure_counts.items())),
        "fifo": {
            "valid": (
                True
                if model_mode == "live"
                else list(execution.dispatch_case_order) == dispatch_expected
            ),
            "dispatch_case_order": list(execution.dispatch_case_order),
            "expected_case_order": dispatch_expected,
        },
        "backpressure": {
            "queue_full": failure_counts[CoreFailureCode.QUEUE_FULL.value],
            "queued_hard_timeout": sum(
                1
                for planned, result in zip(workload.tasks, execution.results)
                if planned.expected.timeout_phase == "queued"
                and result.failure is not None
                and result.failure.code is CoreFailureCode.HARD_TIMEOUT
            ),
        },
        "latency_ms": latency,
        "core_budget": budget,
        "trace_overhead": _trace_overhead(
            execution.trace_events,
            budget_ms=workload.trace_overhead_budget_ms_per_event,
        ),
        "results": results,
    }
    return evaluation, _event_records(workload, execution)


def _artifact_bytes(
    workload: GeneratedWorkload,
    events: Sequence[Mapping[str, object]],
    evaluation: Mapping[str, object],
) -> dict[str, bytes]:
    event_bytes = "".join(_canonical_json_line(record) + "\n" for record in events).encode(
        "utf-8"
    )
    return {
        "manifest.json": _canonical_json_bytes(workload.manifest),
        "events.jsonl": event_bytes,
        "oracle.json": _canonical_json_bytes(workload.oracle),
        "evaluation.json": _canonical_json_bytes(evaluation),
    }


def _write_artifacts(output_dir: Path, files: Mapping[str, bytes]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, contents in files.items():
        (output_dir / filename).write_bytes(contents)


def evaluate_scenario(
    scenario_path: Path,
    *,
    seed: int,
    model_mode: str,
    output_dir: Optional[Path] = None,
    implementation_commit: Optional[str] = None,
    worktree_dirty: Optional[bool] = None,
) -> dict[str, object]:
    """Run one generic workload and optionally retain its four evidence artifacts."""

    workload = generate_workload(
        scenario_path,
        seed=seed,
        model_mode=model_mode,
        implementation_commit=implementation_commit,
        worktree_dirty=worktree_dirty,
    )
    execution = _run_execution(workload, model_mode)
    evaluation, events = _build_evaluation(workload, execution, model_mode=model_mode)
    if output_dir is not None:
        _write_artifacts(output_dir, _artifact_bytes(workload, events, evaluation))
    return evaluation


def _read_event_records(path: Path, *, seed: int) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EvaluationArtifactError(f"events unavailable for seed {seed}") from exc
    for line_number, line in enumerate(lines, start=1):
        try:
            record = json.loads(
                line,
                parse_constant=_reject_json_constant,
                object_pairs_hook=_reject_duplicate_object_keys,
            )
        except ValueError as exc:
            raise EvaluationArtifactError(
                f"malformed event line {line_number} for seed {seed}"
            ) from exc
        if not isinstance(record, dict):
            raise EvaluationArtifactError(f"event line {line_number} is not an object for seed {seed}")
        records.append(record)
    return records


def replay_artifacts(
    output_dir: Path,
    *,
    scenario_path: Path,
) -> dict[str, object]:
    """Regenerate scripted evidence and reject any manifest, task, or oracle drift."""

    manifest = _load_json_object(output_dir / "manifest.json")
    seed = manifest.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise EvaluationArtifactError("replay manifest seed is invalid")
    retained_model = manifest.get("model")
    if not isinstance(retained_model, dict) or retained_model.get("mode") != "scripted":
        raise EvaluationArtifactError(f"replay supports scripted artifacts only for seed {seed}")
    current_scenario = _load_json_object(scenario_path.resolve())
    current_digest = _json_digest(current_scenario)
    if manifest.get("scenario_digest") != current_digest:
        raise EvaluationArtifactError(f"scenario digest mismatch for seed {seed}")

    workload = generate_workload(
        scenario_path,
        seed=seed,
        model_mode="scripted",
        implementation_commit=str(manifest.get("implementation_commit", "unknown")),
        worktree_dirty=bool(manifest.get("worktree_dirty", True)),
    )
    records = _read_event_records(output_dir / "events.jsonl", seed=seed)
    accepted = [record for record in records if record.get("record_type") == "task_accepted"]
    expected_tasks = {planned.task.task_id: planned.task for planned in workload.tasks}
    if len(accepted) != len(expected_tasks):
        raise EvaluationArtifactError(f"accepted task count mismatch for seed {seed}")
    for record in accepted:
        raw_task = record.get("task")
        task_id = raw_task.get("task_id", "unknown-task") if isinstance(raw_task, dict) else "unknown-task"
        try:
            task = AgentTask.model_validate(raw_task)
        except (ValidationError, TypeError) as exc:
            raise EvaluationArtifactError(
                f"malformed task for seed {seed}, task {task_id}"
            ) from exc
        expected = expected_tasks.get(task.task_id)
        if expected is None or task != expected:
            raise EvaluationArtifactError(
                f"task digest or payload mismatch for seed {seed}, task {task.task_id}"
            )

    execution = _run_execution(workload, "scripted")
    evaluation, regenerated_events = _build_evaluation(workload, execution, model_mode="scripted")
    regenerated = _artifact_bytes(workload, regenerated_events, evaluation)
    for filename in ("manifest.json", "events.jsonl", "oracle.json"):
        try:
            retained = (output_dir / filename).read_bytes()
        except OSError as exc:
            raise EvaluationArtifactError(f"missing {filename} for seed {seed}") from exc
        if retained != regenerated[filename]:
            raise EvaluationArtifactError(f"{filename} mismatch for seed {seed}")
    return {
        "schema_version": REPLAY_SCHEMA,
        "status": "matched",
        "seed": seed,
        "task_count": len(workload.tasks),
        "scenario_digest": current_digest,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the domain-neutral static agent core")
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--model", required=True, choices=("scripted", "live"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        evaluation = evaluate_scenario(
            args.scenario,
            seed=args.seed,
            model_mode=args.model,
            output_dir=args.output,
        )
    except EvaluationArtifactError as exc:
        parser.error(str(exc))
    summary = {
        "evaluation_scope": evaluation["evaluation_scope"],
        "evaluation_mode": evaluation["evaluation_mode"],
        "model_identifier": evaluation["model_identifier"],
        "task_count": evaluation["task_count"],
        "outcome_matches": evaluation["outcome_matches"],
        "provider_calls": evaluation["provider_calls"],
        "complete_traces": evaluation["complete_traces"],
        "core_budget": evaluation["core_budget"],
        "output": str(args.output),
    }
    print(_canonical_json_line(summary))
    return 0 if (
        evaluation["outcome_matches"] == evaluation["task_count"]
        and evaluation["complete_traces"]["count"] == evaluation["task_count"]  # type: ignore[index]
        and evaluation["effect_calls"] == 0
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
