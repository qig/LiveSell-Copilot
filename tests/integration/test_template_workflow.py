from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from sidestage.agent_core import ModelResponse, ModelTerminalCall
from sidestage.app import create_app
from sidestage.storage.repositories import _evidence_id


SELLER = "sel_velocity_kicks"
LISTING = "lst_velocity_aero_dash"
FIXED_TIME = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


class TemplateRunner:
    def __init__(self, *, needs_seller: bool = False) -> None:
        self.needs_seller = needs_seller
        self.calls = []

    async def run(self, invocation):
        self.calls.append(invocation)
        model_input = invocation.request.model_input.to_dict()
        if self.needs_seller:
            tool_name = "needs_seller"
            arguments = {"reason_code": "ambiguous_question"}
        else:
            price = next(
                record
                for record in model_input["evidence"]
                if record["fact_type"] == "current_price"
            )
            tool_name = "reply_current_price"
            arguments = {"evidence_ids": [price["evidence_id"]]}
        return ModelResponse(
            model_id="scripted-template",
            terminal_calls=(
                ModelTerminalCall(
                    tool_name=tool_name,
                    arguments_json=json.dumps(arguments),
                ),
            ),
        )


def _run_question(
    tmp_path: Path,
    runner,
    *,
    question: str = "How much is this pair?",
    manual_review: bool = True,
) -> tuple[dict, object]:
    app = create_app(
        database_path=tmp_path / "template.sqlite3",
        wall_clock=lambda: FIXED_TIME,
        model_runner=runner,
        workflow_strategy="one_call_template",
    )
    with TestClient(app) as client:
        session = client.post("/api/demo/sessions", json={"seller_id": SELLER}).json()
        token = session["session_token"]
        if manual_review:
            manual = client.post(
                f"/api/sessions/{token}/copilot/r3",
                json={
                    "enabled": False,
                    "expected_version": session["snapshot"]["r3_capability"]["version"],
                },
            )
            assert manual.status_code == 200
        push = client.post(
            f"/api/sessions/{token}/actions/push",
            json={"target_listing_id": LISTING, "expected_show_version": 1},
            headers={"Idempotency-Key": "template-push"},
        )
        assert push.status_code == 200
        response = client.post(
            f"/api/sessions/{token}/chat/custom",
            json={"raw_text": question},
        )
        assert response.status_code == 201
        return response.json(), app


def test_one_call_workflow_selects_evidence_and_template_then_renders_locally(
    tmp_path: Path,
) -> None:
    runner = TemplateRunner()

    response, app = _run_question(tmp_path, runner)

    result = response["pipeline_results"][0]
    decision = result["broker_decision"]
    assert len(runner.calls) == 1
    assert app.state.workflow_strategy == "one_call_template"
    assert app.state.analyzer is None
    assert decision["outcome"] == "review"
    assert decision["reply_text"] == "Current price: USD 160.00"
    assert decision["template_id"] == "reply_current_price"
    assert decision["template_version"] == "1.0.0"
    tools = {tool.name for tool in runner.calls[0].request.terminal_tools}
    assert "reply_current_price" in tools
    assert "request_evidence" not in tools
    assert "request_reply_send" not in tools


def test_template_miss_never_falls_back_to_the_two_call_workflow(tmp_path: Path) -> None:
    runner = TemplateRunner(needs_seller=True)

    response, _app = _run_question(tmp_path, runner)

    result = response["pipeline_results"][0]
    assert len(runner.calls) == 1
    assert result["broker_decision"]["outcome"] == "needs_seller"
    assert result["reason_code"] == "ambiguous_question"


class AvailabilityTemplateRunner:
    def __init__(self, *, selected_evidence_id: str | None = None) -> None:
        self.selected_evidence_id = selected_evidence_id
        self.calls = []

    async def run(self, invocation):
        self.calls.append(invocation)
        evidence = invocation.request.model_input.to_dict()["evidence"]
        exact = [item for item in evidence if item["fact_type"] == "variant_availability"]
        summaries = [item for item in evidence if item["fact_type"] == "availability_summary"]
        if summaries:
            assert len(summaries) == 1
            tool_name = "reply_availability_summary"
            evidence_id = summaries[0]["evidence_id"]
        else:
            assert len(exact) == 1
            tool_name = "reply_exact_variant_availability"
            evidence_id = exact[0]["evidence_id"]
        return ModelResponse(
            model_id="scripted-template-availability",
            terminal_calls=(
                ModelTerminalCall(
                    tool_name=tool_name,
                    arguments_json=json.dumps(
                        {"evidence_ids": [self.selected_evidence_id or evidence_id]}
                    ),
                ),
            ),
        )


@pytest.mark.parametrize(
    "wording",
    ("US M 9", "9 M US", "Men's US 9", "9 for men", "9 for man"),
)
def test_one_call_exact_size_wording_projects_and_renders_one_trusted_variant(
    tmp_path: Path,
    wording: str,
) -> None:
    runner = AvailabilityTemplateRunner()

    response, _app = _run_question(
        tmp_path,
        runner,
        question=f"Is {wording} available?",
    )

    result = response["pipeline_results"][0]
    model_evidence = runner.calls[0].request.model_input.to_dict()["evidence"]
    variants = [item for item in model_evidence if item["fact_type"] == "variant_availability"]
    assert len(variants) == 1
    assert variants[0]["value"] == "US M 9: 2 available"
    assert result["broker_decision"]["outcome"] == "review"
    assert result["broker_decision"]["reply_text"] == "Availability: US M 9: 2 available"
    assert response["snapshot"]["outbound_replies"] == []


def test_one_call_exact_absent_size_projects_one_negative_variant_fact(
    tmp_path: Path,
) -> None:
    runner = AvailabilityTemplateRunner()

    response, _app = _run_question(
        tmp_path,
        runner,
        question="Is US M 6.5 available?",
    )

    model_evidence = runner.calls[0].request.model_input.to_dict()["evidence"]
    variants = [item for item in model_evidence if item["fact_type"] == "variant_availability"]
    assert len(variants) == 1
    assert variants[0]["value"] == "US M 6.5: 0 available"
    assert len(variants) == 1
    assert response["pipeline_results"][0]["broker_decision"]["reply_text"] == (
        "Availability: US M 6.5: 0 available"
    )


@pytest.mark.parametrize(
    "question",
    ("What sizes are available?", "How many pairs are left across all sizes?"),
)
def test_one_call_general_availability_projects_one_aggregate_not_all_variants(
    tmp_path: Path,
    question: str,
) -> None:
    runner = AvailabilityTemplateRunner()

    response, _app = _run_question(tmp_path, runner, question=question)

    result = response["pipeline_results"][0]
    model_evidence = runner.calls[0].request.model_input.to_dict()["evidence"]
    summaries = [item for item in model_evidence if item["fact_type"] == "availability_summary"]
    assert len(summaries) == 1
    assert not any(item["fact_type"] == "variant_availability" for item in model_evidence)
    assert "Total available: 7 pairs" in summaries[0]["value"]
    assert result["broker_decision"]["outcome"] == "review"
    assert result["broker_decision"]["template_id"] == "reply_availability_summary"


def test_one_call_availability_summary_auto_messages_from_one_aggregate(
    tmp_path: Path,
) -> None:
    runner = AvailabilityTemplateRunner()

    response, _app = _run_question(
        tmp_path,
        runner,
        question="What sizes are available?",
        manual_review=False,
    )

    result = response["pipeline_results"][0]
    assert result["broker_decision"]["outcome"] == "auto_send"
    assert result["publication"]["state"] == "auto_answered"
    assert len(response["snapshot"]["outbound_replies"]) == 1
    assert response["snapshot"]["reply_receipts"][0]["validated_versions"][
        "inventory_summary_version"
    ] > 0


@pytest.mark.parametrize(
    "selected_evidence_id",
    (
        "evd_fabricated_variant",
        _evidence_id(
            SELLER,
            LISTING,
            "variant_availability:var_velocity_aero_dash_10",
        ),
    ),
)
def test_one_call_fabricated_or_wrong_real_variant_cannot_render_or_publish(
    tmp_path: Path,
    selected_evidence_id: str,
) -> None:
    runner = AvailabilityTemplateRunner(selected_evidence_id=selected_evidence_id)

    response, _app = _run_question(
        tmp_path,
        runner,
        question="Is 9 for men available?",
    )

    result = response["pipeline_results"][0]
    assert result["status"] == "failed"
    assert result["reason_code"] == "template_render_failed"
    assert result["publication"]["state"] == "needs_seller"
    assert response["snapshot"]["outbound_replies"] == []
