from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi.testclient import TestClient

from sidestage.agent_core import ModelResponse, ModelTerminalCall
from sidestage.app import create_app


SELLER = "sel_velocity_kicks"
LISTING = "lst_velocity_aero_dash"
FIXED_TIME = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


class TwoCallAvailabilityRunner:
    def __init__(self, *, wrong_reply_variant: bool = False) -> None:
        self.wrong_reply_variant = wrong_reply_variant
        self.calls = []

    async def run(self, invocation):
        self.calls.append(invocation)
        tools = [tool.name for tool in invocation.request.terminal_tools]
        model_input = invocation.request.model_input.to_dict()
        if tools == ["request_evidence"]:
            return ModelResponse(
                model_id="scripted-availability-planner",
                terminal_calls=(
                    ModelTerminalCall(
                        tool_name="request_evidence",
                        arguments_json=json.dumps(
                            {
                                "intent": "answerable",
                                "answer_category": "availability",
                                "product_mentions": ["Aero Dash"],
                                "required_fact_types": ["variant_availability"],
                                "query_terms": [],
                            }
                        ),
                    ),
                ),
            )

        evidence = [
            item
            for item in model_input["evidence"]
            if item["fact_type"] != "listing_identity"
        ]
        assert len(evidence) == 1
        record = evidence[0]
        reply_text = (
            "US M 10: 1 available"
            if self.wrong_reply_variant
            else record["value"]
        )
        return ModelResponse(
            model_id="scripted-availability-drafter",
            terminal_calls=(
                ModelTerminalCall(
                    tool_name="request_reply_send",
                    arguments_json=json.dumps(
                        {
                            "reply_text": reply_text,
                            "answer_category": "availability",
                            "claims": [
                                {
                                    "reply_span": reply_text,
                                    "evidence_ids": [record["evidence_id"]],
                                }
                            ],
                        }
                    ),
                ),
            ),
        )


def _run_two_call(
    tmp_path: Path,
    runner: TwoCallAvailabilityRunner,
    question: str,
) -> dict:
    app = create_app(
        database_path=tmp_path / "two-call-variant.sqlite3",
        wall_clock=lambda: FIXED_TIME,
        model_runner=runner,
        workflow_strategy="two_call_draft",
    )
    with TestClient(app) as client:
        session = client.post("/api/demo/sessions", json={"seller_id": SELLER}).json()
        token = session["session_token"]
        pushed = client.post(
            f"/api/sessions/{token}/actions/push",
            json={"target_listing_id": LISTING, "expected_show_version": 1},
            headers={"Idempotency-Key": "two-call-variant-push"},
        )
        assert pushed.status_code == 200
        response = client.post(
            f"/api/sessions/{token}/chat/custom",
            json={"raw_text": question},
        )
        assert response.status_code == 201
        return response.json()


def test_two_call_uses_python_resolved_variant_without_a_model_variant_field(
    tmp_path: Path,
) -> None:
    runner = TwoCallAvailabilityRunner()

    response = _run_two_call(tmp_path, runner, "Do you have 9 for man?")

    result = response["pipeline_results"][0]
    reply_input = runner.calls[1].request.model_input.to_dict()
    variant_records = [
        item for item in reply_input["evidence"] if item["fact_type"] == "variant_availability"
    ]
    assert len(runner.calls) == 2
    assert len(variant_records) == 1
    assert variant_records[0]["value"] == "US M 9: 2 available"
    assert variant_records[0]["source_ref"].endswith("/var_velocity_aero_dash_9")
    assert result["broker_decision"]["outcome"] == "review"
    assert result["broker_decision"]["reply_text"] == "US M 9: 2 available"


def test_two_call_general_availability_uses_one_aggregate_record(tmp_path: Path) -> None:
    runner = TwoCallAvailabilityRunner()

    response = _run_two_call(
        tmp_path,
        runner,
        "How many pairs are left across all sizes?",
    )

    result = response["pipeline_results"][0]
    reply_input = runner.calls[1].request.model_input.to_dict()
    summaries = [
        item for item in reply_input["evidence"] if item["fact_type"] == "availability_summary"
    ]
    assert len(summaries) == 1
    assert not any(
        item["fact_type"] == "variant_availability" for item in reply_input["evidence"]
    )
    assert "Total available: 7 pairs" in summaries[0]["value"]
    assert result["broker_decision"]["outcome"] == "review"


def test_two_call_unknown_size_stops_before_reply_model(tmp_path: Path) -> None:
    runner = TwoCallAvailabilityRunner()

    response = _run_two_call(tmp_path, runner, "Do you have men's US size 11?")

    result = response["pipeline_results"][0]
    assert len(runner.calls) == 1
    assert result["status"] == "failed"
    assert result["reason_code"] == "missing_evidence"
    assert result["publication"]["state"] == "needs_seller"
    assert response["snapshot"]["outbound_replies"] == []


def test_two_call_wrong_but_real_variant_claim_fails_semantic_validation(
    tmp_path: Path,
) -> None:
    runner = TwoCallAvailabilityRunner(wrong_reply_variant=True)

    response = _run_two_call(tmp_path, runner, "Do you have men's US size 9?")

    result = response["pipeline_results"][0]
    assert len(runner.calls) == 2
    assert result["broker_decision"]["outcome"] == "needs_seller"
    assert result["broker_decision"]["reason_code"] == "unsupported_claim"
    assert result["publication"]["state"] == "needs_seller"
    assert response["snapshot"]["outbound_replies"] == []
