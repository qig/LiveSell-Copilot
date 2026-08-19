from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sidestage.agent_core import ModelResponse, ModelTerminalCall
from sidestage.app import create_app
from sidestage.copilot.broker import SellerReplyDecisionRequest
from sidestage.copilot.pipeline import RawCustomerReplyEvent, process_customer_reply
from sidestage.copilot.runtime import RuntimeModelProfile, RuntimeModelRegistration
from sidestage.marketplace.authority import SellerAuthority
from sidestage.marketplace.service import PushRequest
from sidestage.trace.runtime_metrics import runtime_latency_projection


NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
SELLER = "sel_velocity_kicks"
SHOW = "show_velocity_kicks"
LISTING = "lst_velocity_aero_dash"


class TemplateRunner:
    def __init__(self, model_id: str, *, blocking: bool = False) -> None:
        self.model_id = model_id
        self.calls = []
        self.started = asyncio.Event() if blocking else None
        self.release = asyncio.Event() if blocking else None

    async def run(self, invocation):
        self.calls.append(invocation)
        if self.started is not None and self.release is not None:
            self.started.set()
            await self.release.wait()
        evidence = invocation.request.model_input.to_dict()["evidence"]
        price = next(item for item in evidence if item["fact_type"] == "current_price")
        return ModelResponse(
            model_id=self.model_id,
            terminal_calls=(
                ModelTerminalCall(
                    tool_name="reply_current_price",
                    arguments_json=json.dumps({"evidence_ids": [price["evidence_id"]]}),
                ),
            ),
            provider_metadata={
                "requested_model_id": self.model_id,
                "resolved_model_id": self.model_id,
                "resolved_provider": "test-provider",
            },
        )


def _registration(profile_id: str, runner: TemplateRunner) -> RuntimeModelRegistration:
    return RuntimeModelRegistration(
        RuntimeModelProfile(
            profile_id=profile_id,
            display_name=profile_id.title(),
            provider="scripted",
            requested_model_id=runner.model_id,
            model_config_ref=f"config-{profile_id}",
            reasoning_effort="none",
            request_timeout_s=5.0,
            supported_workflows=("one_call_template",),
        ),
        runner,
    )


def test_debugger_switch_is_versioned_compatible_and_per_show(tmp_path: Path) -> None:
    first = TemplateRunner("model-first")
    second = TemplateRunner("model-second")
    app = create_app(
        database_path=tmp_path / "switch-api.sqlite3",
        wall_clock=lambda: NOW,
        workflow_strategy="one_call_template",
        runtime_model_registrations=(
            _registration("first", first),
            _registration("second", second),
        ),
        default_model_profile_id="first",
    )
    with TestClient(app) as client:
        velocity = client.post(
            "/api/demo/sessions", json={"seller_id": SELLER}
        ).json()["session_token"]
        vault = client.post(
            "/api/demo/sessions", json={"seller_id": "sel_vault_consign"}
        ).json()["session_token"]

        active = client.get(
            "/api/debug/runtime", params={"session_token": velocity}
        ).json()
        assert active["active_selection"]["model_profile_id"] == "first"
        assert active["active_selection"]["selection_version"] == 1

        incompatible = client.put(
            "/api/debug/runtime",
            params={"session_token": velocity},
            json={
                "workflow_id": "two_call_draft",
                "model_profile_id": "second",
                "expected_selection_version": 1,
            },
        )
        assert incompatible.status_code == 409
        assert incompatible.json()["detail"]["code"] == "incompatible_selection"

        changed = client.put(
            "/api/debug/runtime",
            params={"session_token": velocity},
            json={
                "workflow_id": "one_call_template",
                "model_profile_id": "second",
                "expected_selection_version": 1,
            },
        )
        assert changed.status_code == 200
        assert changed.json()["active_selection"]["selection_version"] == 2
        assert changed.json()["snapshot"]["active_runtime_selection"][
            "model_profile_id"
        ] == "second"
        assert changed.json()["snapshot"]["active_runtime_selection"] == {
            **changed.json()["active_selection"],
            "model_display_name": "Second",
            "reasoning_effort": "none",
            "service_tier": None,
        }
        assert client.get(
            "/api/debug/runtime", params={"session_token": vault}
        ).json()["active_selection"]["selection_version"] == 1

        stale = client.put(
            "/api/debug/runtime",
            params={"session_token": velocity},
            json={
                "workflow_id": "one_call_template",
                "model_profile_id": "first",
                "expected_selection_version": 1,
            },
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "stale_selection_version"


def test_invalid_startup_default_fails_before_database_initialization(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "must-not-initialize.sqlite3"
    runner = TemplateRunner("template-only")

    with pytest.raises(ValueError, match="default selection"):
        create_app(
            database_path=database_path,
            workflow_strategy="two_call_draft",
            runtime_model_registrations=(_registration("template-only", runner),),
            default_model_profile_id="template-only",
        )

    assert not database_path.exists()


def test_in_flight_question_keeps_acceptance_time_selection(tmp_path: Path) -> None:
    async def scenario() -> None:
        first = TemplateRunner("model-first", blocking=True)
        second = TemplateRunner("model-second")
        app = create_app(
            database_path=tmp_path / "switch-pinning.sqlite3",
            wall_clock=lambda: NOW,
            workflow_strategy="one_call_template",
            runtime_model_registrations=(
                _registration("first", first),
                _registration("second", second),
            ),
            default_model_profile_id="first",
        )
        authority = SellerAuthority(
            seller_id=SELLER,
            show_id=SHOW,
            actor_id="debugger",
        )
        app.state.marketplace.push(
            authority,
            PushRequest(target_listing_id=LISTING, expected_show_version=1),
            idempotency_key="runtime-pinning-push",
        )
        with app.state.database.transaction() as connection:
            connection.execute(
                """UPDATE copilot_r3_capabilities
                   SET enabled = 0, version = version + 1
                   WHERE seller_id = ? AND show_id = ?""",
                (authority.seller_id, authority.show_id),
            )

        pending = asyncio.create_task(
            process_customer_reply(
                RawCustomerReplyEvent(
                    authority=authority,
                    customer_display_name="buyer_one",
                    raw_text="How much is this pair?",
                    input_origin="custom",
                ),
                app.state.pipeline_services,
            )
        )
        assert first.started is not None
        await first.started.wait()
        changed = app.state.runtime_selector.switch(
            authority,
            workflow_id="one_call_template",
            model_profile_id="second",
            expected_selection_version=1,
        )
        assert changed.selection_version == 2
        assert first.release is not None
        first.release.set()
        first_result = await pending

        second_result = await process_customer_reply(
            RawCustomerReplyEvent(
                authority=authority,
                customer_display_name="buyer_two",
                raw_text="What is the current price?",
                input_origin="custom",
            ),
            app.state.pipeline_services,
        )
        steady_result = await process_customer_reply(
            RawCustomerReplyEvent(
                authority=authority,
                customer_display_name="buyer_three",
                raw_text="Can you tell me the price right now?",
                input_origin="custom",
            ),
            app.state.pipeline_services,
        )

        assert first_result.runtime_selection.model_profile_id == "first"
        assert first_result.runtime_selection.selection_version == 1
        assert second_result.runtime_selection.model_profile_id == "second"
        assert second_result.runtime_selection.selection_version == 2
        assert steady_result.runtime_selection.model_profile_id == "second"
        assert steady_result.sample_phase == "steady"
        assert len(first.calls) == 1
        assert len(second.calls) == 2
        app.state.trace_sink.flush()
        with app.state.database.read() as connection:
            rows = connection.execute(
                """SELECT model_profile_id, selection_version, sample_phase,
                          resolved_model_id, resolved_provider
                   FROM copilot_questions ORDER BY question_number"""
            ).fetchall()
        assert [dict(row) for row in rows] == [
            {
                "model_profile_id": "first",
                "selection_version": 1,
                "sample_phase": "cold",
                "resolved_model_id": "model-first",
                "resolved_provider": "test-provider",
            },
            {
                "model_profile_id": "second",
                "selection_version": 2,
                "sample_phase": "cold",
                "resolved_model_id": "model-second",
                "resolved_provider": "test-provider",
            },
            {
                "model_profile_id": "second",
                "selection_version": 2,
                "sample_phase": "steady",
                "resolved_model_id": "model-second",
                "resolved_provider": "test-provider",
            },
        ]
        with app.state.database.read() as connection:
            observations = connection.execute(
                """SELECT trace_id, workflow_id, model_profile_id, selection_version
                   FROM copilot_trace_observations
                   ORDER BY observation_number"""
            ).fetchall()
        assert all(row["workflow_id"] == "one_call_template" for row in observations)
        by_trace = {}
        for row in observations:
            by_trace.setdefault(row["trace_id"], set()).add(
                (row["model_profile_id"], row["selection_version"])
            )
        assert all(len(identities) == 1 for identities in by_trace.values())

        metrics = runtime_latency_projection(
            app.state.database,
            seller_id=SELLER,
            show_id=SHOW,
        )
        groups = {item["model_profile_id"]: item for item in metrics["groups"]}
        assert groups["first"]["cold"]["count"] == 1
        assert groups["first"]["steady"]["count"] == 0
        assert groups["second"]["cold"]["count"] == 1
        assert groups["second"]["steady"]["count"] == 1
        assert groups["second"]["combined"]["count"] == 2

        sent = await app.state.reply_service.decide(
            authority,
            second_result.question_id,
            SellerReplyDecisionRequest(action="accept"),
            idempotency_key="runtime-attributed-r2",
        )
        assert sent["receipt"]["runtime_selection"] == {
            "workflow_id": "one_call_template",
            "model_profile_id": "second",
            "requested_model_id": "model-second",
            "model_config_ref": "config-second",
            "provider": "scripted",
            "selection_version": 2,
            "sample_phase": "cold",
            "resolved_model_id": "model-second",
            "resolved_provider": "test-provider",
        }

    asyncio.run(scenario())
