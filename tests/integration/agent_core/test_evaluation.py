from __future__ import annotations

import json
from pathlib import Path

from sidestage.agent_core.evaluation import evaluate_scenario


ROOT = Path(__file__).resolve().parents[3]
SCENARIO = ROOT / "fixtures" / "agent_core" / "pressure_v1.json"


def test_scripted_evaluation_covers_terminal_and_typed_failure_matrix(tmp_path: Path) -> None:
    output = tmp_path / "evaluation"
    evaluation = evaluate_scenario(
        SCENARIO,
        seed=20260817,
        model_mode="scripted",
        output_dir=output,
    )

    assert evaluation["evaluation_scope"] == "agent_core"
    assert evaluation["evaluation_mode"] == "scripted"
    assert evaluation["task_count"] == 20
    assert evaluation["outcome_matches"] == 20
    assert evaluation["terminal_contract_compliance"] == {"count": 20, "rate": 1.0}
    assert evaluation["provider_calls"] == {"actual": 16, "expected": 16}
    assert evaluation["effect_calls"] == 0
    assert evaluation["complete_traces"] == {"count": 20, "rate": 1.0}
    assert evaluation["terminal_counts"] == {"abstain": 2, "finish": 6}
    assert evaluation["failure_counts"] == {
        "cancelled": 1,
        "hard_timeout": 3,
        "malformed_arguments": 1,
        "missing_terminal_call": 2,
        "multiple_terminal_calls": 1,
        "provider_error": 1,
        "queue_full": 2,
        "unknown_tool": 1,
    }

    records = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
    assert len(records) == 40
    assert {record["record_type"] for record in records} == {
        "task_accepted",
        "task_completed",
    }
    event_text = json.dumps(records, sort_keys=True)
    for forbidden in ("expected", "provider_condition", "oracle", "case_id"):
        assert forbidden not in event_text

    oracle = json.loads((output / "oracle.json").read_text())
    assert len(oracle["tasks"]) == 20
    assert all("provider_condition" in item for item in oracle["tasks"].values())

    completed_by_task = {
        record["task_id"]: record
        for record in records
        if record["record_type"] == "task_completed"
    }
    trace_by_case = {
        item["case_id"]: completed_by_task[task_id]["trace_event_types"]
        for task_id, item in oracle["tasks"].items()
    }
    assert trace_by_case["burst-01"] == [
        "task_accepted",
        "task_queued",
        "provider_started",
        "provider_completed",
        "terminal_validated",
        "run_completed",
    ]
    assert trace_by_case["burst-04"] == [
        "task_accepted",
        "task_queued",
        "provider_started",
        "provider_completed",
        "terminal_validated",
        "run_failed",
    ]
    assert trace_by_case["burst-05"] == [
        "task_accepted",
        "task_queued",
        "run_failed",
    ]
    assert trace_by_case["burst-07"] == ["task_accepted", "run_failed"]
    for case_id in ("steady-13", "late-15", "cancel-17"):
        assert trace_by_case[case_id] == [
            "task_accepted",
            "task_queued",
            "provider_started",
            "provider_completed",
            "run_failed",
        ]
    assert (output / "evaluation.json").is_file()


def test_manifest_records_reproducibility_and_scope_without_product_claims(tmp_path: Path) -> None:
    output = tmp_path / "manifest"
    evaluate_scenario(SCENARIO, seed=20260817, model_mode="scripted", output_dir=output)
    manifest = json.loads((output / "manifest.json").read_text())

    assert manifest["evaluation_scope"] == "agent_core"
    assert manifest["model"] == {
        "config_ref": "agent-core-evaluation-v1",
        "identifier": "scripted-agent-core-v1",
        "mode": "scripted",
    }
    assert manifest["clock"] == {
        "mode": "fixed",
        "wall_time": "2026-08-17T00:00:00.000Z",
        "monotonic_base_s": 1000.0,
    }
    assert manifest["seed"] == 20260817
    assert manifest["queue_policy"] == {"capacity": 6, "max_concurrency": 2}
    assert manifest["deadline_policy"] == {
        "default_timeout_ms": 1000,
        "max_timeout_ms": 20000,
    }
    assert manifest["implementation_commit"]
    assert isinstance(manifest["worktree_dirty"], bool)
    assert "gmv" not in json.dumps(manifest).casefold()
    assert "sidestage_e2e" not in json.dumps(manifest)
