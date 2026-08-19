"""Closed startup workflow/model catalog and per-show debug selection."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
import time
from types import MappingProxyType
from typing import Callable, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from typing_extensions import Annotated

from sidestage.agent_core import ModelRunner, TraceSink
from sidestage.copilot.workflows import (
    TemplateWorkflow,
    TwoCallWorkflow,
    register_template_workflow,
    register_two_call_workflow,
)
from sidestage.marketplace.authority import SellerAuthority


WorkflowId = Literal["one_call_template", "two_call_draft"]
SamplePhase = Literal["cold", "steady"]
SafeId = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]


class RuntimeSelectionConflict(ValueError):
    """A closed-catalog selection was unknown, stale, or incompatible."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RuntimeModelProfile(BaseModel):
    """Public, credential-free identity for one startup model configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    profile_id: SafeId
    display_name: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=80)]
    provider: Literal["openai", "openrouter", "scripted"]
    requested_model_id: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=240)
    ]
    model_config_ref: SafeId
    reasoning_effort: Optional[
        Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
    ] = None
    service_tier: Optional[Literal["default", "priority"]] = None
    request_timeout_s: Annotated[float, Field(strict=True, gt=0, le=30)] = 5.0
    supported_workflows: tuple[WorkflowId, ...]
    enabled: bool = True
    disabled_reason: Optional[SafeId] = None

    @model_validator(mode="after")
    def status_is_consistent(self) -> "RuntimeModelProfile":
        if len(set(self.supported_workflows)) != len(self.supported_workflows):
            raise ValueError("supported workflows must be unique")
        if self.enabled and not self.supported_workflows:
            raise ValueError("enabled model profile requires a supported workflow")
        if self.enabled and self.disabled_reason is not None:
            raise ValueError("enabled model profile cannot have a disabled reason")
        if not self.enabled and self.disabled_reason is None:
            raise ValueError("disabled model profile requires a disabled reason")
        if self.provider != "openai" and self.service_tier is not None:
            raise ValueError("service_tier is only valid for direct OpenAI profiles")
        return self


@dataclass(frozen=True)
class RuntimeModelRegistration:
    profile: RuntimeModelProfile
    runner: Optional[ModelRunner]


@dataclass(frozen=True)
class RuntimeCatalogEntry:
    profile: RuntimeModelProfile
    workflow_id: WorkflowId
    workflow: TemplateWorkflow | TwoCallWorkflow


class RuntimeSelection(BaseModel):
    """Immutable selection captured for one accepted chat event."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    seller_id: SafeId
    show_id: SafeId
    workflow_id: WorkflowId
    model_profile_id: SafeId
    requested_model_id: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=240)
    ]
    model_config_ref: SafeId
    provider: Literal["openai", "openrouter", "scripted"]
    selection_version: Annotated[int, Field(strict=True, gt=0)]
    selected_at: datetime

    @model_validator(mode="after")
    def timestamp_is_utc(self) -> "RuntimeSelection":
        if self.selected_at.tzinfo is None or self.selected_at.utcoffset() is None:
            raise ValueError("selection timestamp must be timezone-aware")
        if self.selected_at.utcoffset().total_seconds() != 0:
            raise ValueError("selection timestamp must use UTC")
        return self


_WORKFLOW_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "workflow_id": "one_call_template",
        "display_name": "One-call template",
        "provider_call_count": 1,
        "description": "Select trusted evidence and one approved reply template in one call.",
    },
    {
        "workflow_id": "two_call_draft",
        "display_name": "Two-call draft",
        "provider_call_count": 2,
        "description": "Plan evidence, retrieve it deterministically, then draft a grounded reply.",
    },
)


class RuntimeCatalog:
    """Immutable two-workflow catalog built before the app accepts chat."""

    def __init__(
        self,
        *,
        registrations: Sequence[RuntimeModelRegistration],
        default_workflow_id: WorkflowId,
        default_model_profile_id: str,
        monotonic: Callable[[], float] = time.monotonic,
        trace_sink: Optional[TraceSink] = None,
    ) -> None:
        validate_runtime_registrations(
            registrations,
            default_workflow_id=default_workflow_id,
            default_model_profile_id=default_model_profile_id,
        )
        profiles: dict[str, RuntimeModelProfile] = {}
        config_refs: set[str] = set()
        entries: dict[tuple[str, str], RuntimeCatalogEntry] = {}
        runners: dict[str, ModelRunner] = {}
        ordered_profiles: list[RuntimeModelProfile] = []
        for registration in registrations:
            profile = registration.profile
            if profile.profile_id in profiles:
                raise ValueError("runtime model profile IDs must be unique")
            if profile.model_config_ref in config_refs:
                raise ValueError("runtime model configuration references must be unique")
            profiles[profile.profile_id] = profile
            config_refs.add(profile.model_config_ref)
            ordered_profiles.append(profile)
            if not profile.enabled:
                if registration.runner is not None:
                    raise ValueError("disabled model profile cannot register a runner")
                continue
            if registration.runner is None:
                raise ValueError("enabled model profile requires a runner")
            runners[profile.profile_id] = registration.runner
            for workflow_id in profile.supported_workflows:
                if workflow_id == "one_call_template":
                    workflow = register_template_workflow(
                        registration.runner,
                        model_config_ref=profile.model_config_ref,
                        monotonic=monotonic,
                        trace_sink=trace_sink,
                    )
                else:
                    workflow = register_two_call_workflow(
                        registration.runner,
                        model_config_ref=profile.model_config_ref,
                        monotonic=monotonic,
                        trace_sink=trace_sink,
                    )
                entries[(workflow_id, profile.profile_id)] = RuntimeCatalogEntry(
                    profile=profile,
                    workflow_id=workflow_id,
                    workflow=workflow,
                )
        if (default_workflow_id, default_model_profile_id) not in entries:
            raise ValueError("runtime default selection must be enabled and compatible")
        self.default_workflow_id = default_workflow_id
        self.default_model_profile_id = default_model_profile_id
        self._profiles: Mapping[str, RuntimeModelProfile] = MappingProxyType(profiles)
        self._entries: Mapping[tuple[str, str], RuntimeCatalogEntry] = MappingProxyType(entries)
        self._runners: Mapping[str, ModelRunner] = MappingProxyType(runners)
        self._ordered_profiles = tuple(ordered_profiles)

    @property
    def runners(self) -> tuple[ModelRunner, ...]:
        return tuple(self._runners.values())

    def resolve(self, workflow_id: str, model_profile_id: str) -> RuntimeCatalogEntry:
        if workflow_id not in {"one_call_template", "two_call_draft"}:
            raise RuntimeSelectionConflict("unknown_workflow", "unknown workflow selection")
        profile = self._profiles.get(model_profile_id)
        if profile is None:
            raise RuntimeSelectionConflict("unknown_model", "unknown model profile selection")
        if not profile.enabled:
            raise RuntimeSelectionConflict(
                "model_disabled", "model profile is disabled for runtime selection"
            )
        entry = self._entries.get((workflow_id, model_profile_id))
        if entry is None:
            raise RuntimeSelectionConflict(
                "incompatible_selection", "workflow and model profile are incompatible"
            )
        return entry

    def profile(self, model_profile_id: str) -> RuntimeModelProfile:
        profile = self._profiles.get(model_profile_id)
        if profile is None:
            raise RuntimeSelectionConflict("unknown_model", "unknown model profile selection")
        return profile

    def public_projection(self) -> dict:
        return {
            "schema_version": "sidestage.runtime_catalog.v1",
            "workflows": [dict(item) for item in _WORKFLOW_DEFINITIONS],
            "models": [
                {
                    "profile_id": profile.profile_id,
                    "display_name": profile.display_name,
                    "provider": profile.provider,
                    "requested_model_id": profile.requested_model_id,
                    "model_config_ref": profile.model_config_ref,
                    "reasoning_effort": profile.reasoning_effort,
                    "service_tier": profile.service_tier,
                    "request_timeout_s": profile.request_timeout_s,
                    "supported_workflows": list(profile.supported_workflows),
                    "enabled": profile.enabled,
                    "disabled_reason": profile.disabled_reason,
                }
                for profile in self._ordered_profiles
            ],
            "default": {
                "workflow_id": self.default_workflow_id,
                "model_profile_id": self.default_model_profile_id,
            },
        }


class RuntimeSelector:
    """Atomic in-memory selection and cold-marker state scoped by seller/show."""

    def __init__(
        self,
        catalog: RuntimeCatalog,
        *,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.catalog = catalog
        self.wall_clock = wall_clock
        self._active: dict[tuple[str, str], RuntimeSelection] = {}
        self._cold_consumed: set[tuple[str, str, int]] = set()
        self._lock = Lock()

    def capture(self, authority: SellerAuthority) -> RuntimeSelection:
        key = (authority.seller_id, authority.show_id)
        with self._lock:
            return self._capture_locked(authority, key)

    @contextmanager
    def acceptance(self, authority: SellerAuthority):
        """Prevent a switch from interleaving selection capture and durable ingest."""

        key = (authority.seller_id, authority.show_id)
        with self._lock:
            yield self._capture_locked(authority, key)

    def switch(
        self,
        authority: SellerAuthority,
        *,
        workflow_id: str,
        model_profile_id: str,
        expected_selection_version: int,
    ) -> RuntimeSelection:
        self.catalog.resolve(workflow_id, model_profile_id)
        key = (authority.seller_id, authority.show_id)
        with self._lock:
            active = self._active.get(key)
            if active is None:
                active = self._selection(
                    authority,
                    workflow_id=self.catalog.default_workflow_id,
                    model_profile_id=self.catalog.default_model_profile_id,
                    version=1,
                )
                self._active[key] = active
            if expected_selection_version != active.selection_version:
                raise RuntimeSelectionConflict(
                    "stale_selection_version",
                    "runtime selection version is stale",
                )
            if (
                active.workflow_id == workflow_id
                and active.model_profile_id == model_profile_id
            ):
                return active
            changed = self._selection(
                authority,
                workflow_id=workflow_id,
                model_profile_id=model_profile_id,
                version=active.selection_version + 1,
            )
            self._active[key] = changed
            return changed

    def claim_model_sample(self, selection: RuntimeSelection) -> SamplePhase:
        key = (selection.seller_id, selection.show_id, selection.selection_version)
        with self._lock:
            if key in self._cold_consumed:
                return "steady"
            self._cold_consumed.add(key)
            return "cold"

    def next_sample_phase(self, selection: RuntimeSelection) -> SamplePhase:
        key = (selection.seller_id, selection.show_id, selection.selection_version)
        with self._lock:
            return "steady" if key in self._cold_consumed else "cold"

    def reset(self, authority: SellerAuthority) -> RuntimeSelection:
        """Restore the startup default while preserving monotonic selection identity."""

        key = (authority.seller_id, authority.show_id)
        with self._lock:
            active = self._active.get(key)
            next_version = 1 if active is None else active.selection_version + 1
            reset = self._selection(
                authority,
                workflow_id=self.catalog.default_workflow_id,
                model_profile_id=self.catalog.default_model_profile_id,
                version=next_version,
            )
            self._active[key] = reset
            self._cold_consumed = {
                marker
                for marker in self._cold_consumed
                if marker[:2] != key
            }
            return reset

    def _selection(
        self,
        authority: SellerAuthority,
        *,
        workflow_id: str,
        model_profile_id: str,
        version: int,
    ) -> RuntimeSelection:
        entry = self.catalog.resolve(workflow_id, model_profile_id)
        selected_at = self.wall_clock()
        if selected_at.tzinfo is None or selected_at.utcoffset() is None:
            raise ValueError("runtime selection wall clock must be timezone-aware")
        return RuntimeSelection(
            seller_id=authority.seller_id,
            show_id=authority.show_id,
            workflow_id=entry.workflow_id,
            model_profile_id=entry.profile.profile_id,
            requested_model_id=entry.profile.requested_model_id,
            model_config_ref=entry.profile.model_config_ref,
            provider=entry.profile.provider,
            selection_version=version,
            selected_at=selected_at.astimezone(timezone.utc),
        )

    def _capture_locked(
        self,
        authority: SellerAuthority,
        key: tuple[str, str],
    ) -> RuntimeSelection:
        selection = self._active.get(key)
        if selection is None:
            selection = self._selection(
                authority,
                workflow_id=self.catalog.default_workflow_id,
                model_profile_id=self.catalog.default_model_profile_id,
                version=1,
            )
            self._active[key] = selection
        return selection


def validate_runtime_registrations(
    registrations: Sequence[RuntimeModelRegistration],
    *,
    default_workflow_id: WorkflowId,
    default_model_profile_id: str,
) -> None:
    """Validate the closed catalog before any runtime database is initialized."""

    if not registrations:
        raise ValueError("runtime catalog requires at least one model profile")
    profile_ids: set[str] = set()
    config_refs: set[str] = set()
    compatible_default = False
    for registration in registrations:
        profile = registration.profile
        if profile.profile_id in profile_ids:
            raise ValueError("runtime model profile IDs must be unique")
        if profile.model_config_ref in config_refs:
            raise ValueError("runtime model configuration references must be unique")
        profile_ids.add(profile.profile_id)
        config_refs.add(profile.model_config_ref)
        if profile.enabled and registration.runner is None:
            raise ValueError("enabled model profile requires a runner")
        if not profile.enabled and registration.runner is not None:
            raise ValueError("disabled model profile cannot register a runner")
        if (
            profile.profile_id == default_model_profile_id
            and profile.enabled
            and default_workflow_id in profile.supported_workflows
        ):
            compatible_default = True
    if not compatible_default:
        raise ValueError("runtime default selection must be enabled and compatible")
