from __future__ import annotations

import os
from pathlib import Path

import pytest

from sidestage.agent_core.evaluation import evaluate_scenario


ROOT = Path(__file__).resolve().parents[3]
SCENARIO = ROOT / "fixtures" / "agent_core" / "pressure_v1.json"


def test_pressure_reports_fifo_backpressure_latency_and_trace_overhead(tmp_path: Path) -> None:
    evaluation = evaluate_scenario(
        SCENARIO,
        seed=20260817,
        model_mode="scripted",
        output_dir=tmp_path / "pressure",
    )

    assert evaluation["fifo"]["valid"] is True
    assert evaluation["fifo"]["dispatch_case_order"] == [
        "burst-01",
        "burst-02",
        "burst-03",
        "burst-04",
        "steady-09",
        "steady-10",
        "steady-11",
        "steady-12",
        "steady-13",
        "steady-14",
        "late-15",
        "steady-16",
        "cancel-17",
        "steady-18",
        "steady-19",
        "steady-20",
    ]
    assert evaluation["backpressure"] == {
        "queue_full": 2,
        "queued_hard_timeout": 2,
    }
    for stage in ("queue_ms", "provider_ms", "parse_ms", "total_ms"):
        metric = evaluation["latency_ms"][stage]
        assert metric["count"] == 20
        assert 0 <= metric["p50"] <= metric["p95"] <= metric["max"]

    assert evaluation["core_budget"] == {
        "target_p95_ms": 1450.0,
        "measured_p95_ms": evaluation["latency_ms"]["total_ms"]["p95"],
        "status": "pass",
    }
    assert evaluation["trace_overhead"]["sample_count"] >= 1000
    assert evaluation["trace_overhead"]["p95_ms_per_event"] >= 0
    assert evaluation["trace_overhead"]["status"] == "pass"

    queue_full = [
        result for result in evaluation["results"] if result["failure_code"] == "queue_full"
    ]
    assert len(queue_full) == 2
    assert all(result["provider_called"] is False for result in queue_full)


@pytest.mark.live_model
def test_live_matrix_reports_sanitized_core_metrics(tmp_path: Path) -> None:
    required = (
        "SIDESTAGE_MODEL_BASE_URL",
        "SIDESTAGE_MODEL_API_KEY",
        "SIDESTAGE_MODEL_ID",
    )
    if not all(os.environ.get(name) for name in required):
        pytest.skip("set the three SIDESTAGE_MODEL_* variables for the live matrix")

    evaluation = evaluate_scenario(
        SCENARIO,
        seed=20260817,
        model_mode="live",
        output_dir=tmp_path / "live",
    )

    assert evaluation["evaluation_scope"] == "agent_core"
    assert evaluation["evaluation_mode"] == "live"
    assert evaluation["task_count"] == 4
    assert evaluation["provider_calls"] == {"actual": 4, "expected": 4}
    assert evaluation["terminal_contract_compliance"]["count"] == 4
    assert evaluation["effect_calls"] == 0
    assert evaluation["model_identifier"] == os.environ["SIDESTAGE_MODEL_ID"]
    assert evaluation["core_budget"]["status"] in {"pass", "miss"}
