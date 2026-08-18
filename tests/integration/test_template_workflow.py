from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi.testclient import TestClient

from sidestage.agent_core import ModelResponse, ModelTerminalCall
from sidestage.app import create_app


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


def _run_question(tmp_path: Path, runner: TemplateRunner) -> tuple[dict, object]:
    app = create_app(
        database_path=tmp_path / "template.sqlite3",
        wall_clock=lambda: FIXED_TIME,
        model_runner=runner,
        workflow_strategy="one_call_template",
    )
    with TestClient(app) as client:
        session = client.post("/api/demo/sessions", json={"seller_id": SELLER}).json()
        token = session["session_token"]
        push = client.post(
            f"/api/sessions/{token}/actions/push",
            json={"target_listing_id": LISTING, "expected_show_version": 1},
            headers={"Idempotency-Key": "template-push"},
        )
        assert push.status_code == 200
        response = client.post(
            f"/api/sessions/{token}/chat/custom",
            json={"raw_text": "How much is this pair?"},
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
