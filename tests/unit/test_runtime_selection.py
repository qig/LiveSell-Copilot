from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, Thread

import pytest

from sidestage.agent_core import ScriptedModelRunner
from sidestage.copilot.runtime import (
    RuntimeCatalog,
    RuntimeModelProfile,
    RuntimeModelRegistration,
    RuntimeSelectionConflict,
    RuntimeSelector,
)
from sidestage.marketplace.authority import SellerAuthority


NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
AUTHORITY = SellerAuthority(
    seller_id="sel_velocity_kicks",
    show_id="show_velocity_kicks",
    actor_id="debugger",
)


def _profile(
    profile_id: str,
    *,
    workflows: tuple[str, ...] = ("one_call_template", "two_call_draft"),
) -> RuntimeModelProfile:
    return RuntimeModelProfile(
        profile_id=profile_id,
        display_name=profile_id.replace("-", " ").title(),
        provider="scripted",
        requested_model_id=f"model-{profile_id}",
        model_config_ref=f"config-{profile_id}",
        reasoning_effort="none",
        request_timeout_s=5.0,
        supported_workflows=workflows,
    )


def _catalog() -> RuntimeCatalog:
    return RuntimeCatalog(
        registrations=(
            RuntimeModelRegistration(_profile("fast"), ScriptedModelRunner(())),
            RuntimeModelRegistration(
                _profile("template-only", workflows=("one_call_template",)),
                ScriptedModelRunner(()),
            ),
        ),
        default_workflow_id="two_call_draft",
        default_model_profile_id="fast",
    )


def test_selector_is_per_show_versioned_and_validates_compatibility() -> None:
    catalog = _catalog()
    selector = RuntimeSelector(catalog, wall_clock=lambda: NOW)

    original = selector.capture(AUTHORITY)
    assert original.selection_version == 1
    assert original.workflow_id == "two_call_draft"
    assert original.model_profile_id == "fast"

    changed = selector.switch(
        AUTHORITY,
        workflow_id="one_call_template",
        model_profile_id="template-only",
        expected_selection_version=1,
    )
    assert changed.selection_version == 2
    assert selector.capture(AUTHORITY) == changed
    assert original.workflow_id == "two_call_draft"

    with pytest.raises(RuntimeSelectionConflict, match="incompatible"):
        selector.switch(
            AUTHORITY,
            workflow_id="two_call_draft",
            model_profile_id="template-only",
            expected_selection_version=2,
        )

    assert selector.capture(AUTHORITY) == changed
    restarted = RuntimeSelector(catalog, wall_clock=lambda: NOW)
    assert restarted.capture(AUTHORITY).selection_version == 1
    assert restarted.capture(AUTHORITY).model_profile_id == "fast"


def test_cold_marker_is_consumed_only_by_first_model_backed_claim() -> None:
    selector = RuntimeSelector(_catalog(), wall_clock=lambda: NOW)
    selection = selector.capture(AUTHORITY)

    assert selector.next_sample_phase(selection) == "cold"
    assert selector.claim_model_sample(selection) == "cold"
    assert selector.claim_model_sample(selection) == "steady"
    assert selector.next_sample_phase(selection) == "steady"


def test_catalog_projection_is_sanitized_and_closed() -> None:
    catalog = _catalog()

    projection = catalog.public_projection()

    assert {item["workflow_id"] for item in projection["workflows"]} == {
        "one_call_template",
        "two_call_draft",
    }
    assert projection["models"][1]["supported_workflows"] == ["one_call_template"]
    assert "runner" not in repr(projection)
    assert catalog.resolve("one_call_template", "template-only").workflow is not None
    with pytest.raises(RuntimeSelectionConflict, match="unknown"):
        catalog.resolve("one_call_template", "not-registered")


def test_switch_cannot_interleave_acceptance_capture_and_commit_boundary() -> None:
    selector = RuntimeSelector(_catalog(), wall_clock=lambda: NOW)
    attempted = Event()
    switched = Event()

    def switch() -> None:
        attempted.set()
        selector.switch(
            AUTHORITY,
            workflow_id="one_call_template",
            model_profile_id="template-only",
            expected_selection_version=1,
        )
        switched.set()

    with selector.acceptance(AUTHORITY) as pinned:
        thread = Thread(target=switch)
        thread.start()
        assert attempted.wait(timeout=1)
        assert pinned.selection_version == 1
        assert switched.wait(timeout=0.05) is False

    thread.join(timeout=1)
    assert not thread.is_alive()
    assert switched.is_set()
    assert selector.capture(AUTHORITY).selection_version == 2
