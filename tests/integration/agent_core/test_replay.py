from __future__ import annotations

import json
from pathlib import Path

import pytest

from sidestage.agent_core.evaluation import (
    EvaluationArtifactError,
    evaluate_scenario,
    replay_artifacts,
)


ROOT = Path(__file__).resolve().parents[3]
SCENARIO = ROOT / "fixtures" / "agent_core" / "pressure_v1.json"
DETERMINISTIC_FILES = ("manifest.json", "events.jsonl", "oracle.json")


def test_scripted_generation_and_execution_artifacts_are_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    evaluate_scenario(SCENARIO, seed=20260817, model_mode="scripted", output_dir=first)
    evaluate_scenario(SCENARIO, seed=20260817, model_mode="scripted", output_dir=second)

    for filename in DETERMINISTIC_FILES:
        assert (first / filename).read_bytes() == (second / filename).read_bytes()

    replay = replay_artifacts(first, scenario_path=SCENARIO)
    assert replay["status"] == "matched"
    assert replay["task_count"] == 20


def test_replay_rejects_task_digest_tampering_with_seed_and_task_id(tmp_path: Path) -> None:
    output = tmp_path / "tampered-task"
    evaluate_scenario(SCENARIO, seed=20260817, model_mode="scripted", output_dir=output)
    event_path = output / "events.jsonl"
    records = [json.loads(line) for line in event_path.read_text().splitlines()]
    accepted = next(record for record in records if record["record_type"] == "task_accepted")
    task_id = accepted["task"]["task_id"]
    accepted["task"]["profile_digest"] = "sha256:" + "0" * 64
    event_path.write_text(
        "".join(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" for record in records)
    )

    with pytest.raises(EvaluationArtifactError) as captured:
        replay_artifacts(output, scenario_path=SCENARIO)

    assert "20260817" in str(captured.value)
    assert task_id in str(captured.value)


def test_replay_rejects_scenario_digest_mismatch(tmp_path: Path) -> None:
    output = tmp_path / "tampered-manifest"
    evaluate_scenario(SCENARIO, seed=20260817, model_mode="scripted", output_dir=output)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["scenario_digest"] = "sha256:" + "f" * 64
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")

    with pytest.raises(EvaluationArtifactError, match="scenario digest.*20260817"):
        replay_artifacts(output, scenario_path=SCENARIO)


def test_replay_rejects_malformed_manifest_model_with_seed(tmp_path: Path) -> None:
    output = tmp_path / "malformed-manifest"
    evaluate_scenario(SCENARIO, seed=20260817, model_mode="scripted", output_dir=output)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["model"] = []
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")

    with pytest.raises(EvaluationArtifactError, match="scripted artifacts.*20260817"):
        replay_artifacts(output, scenario_path=SCENARIO)
