from __future__ import annotations

import json
from pathlib import Path

import pytest

from sidestage.agent_core.evaluation import EvaluationArtifactError
from sidestage.agent_core.profile import register_profile
from sidestage.agent_core.evaluation import generate_workload


ROOT = Path(__file__).resolve().parents[3]
SCENARIO = ROOT / "fixtures" / "agent_core" / "pressure_v1.json"
BANNED_DOMAIN_TERMS = (
    "seller_id",
    "listing_id",
    "catalog",
    "marketplace",
    "livesell",
    "inventory",
    "reply_send",
)


def test_fixed_seed_generates_bounded_domain_neutral_tasks() -> None:
    workload = generate_workload(SCENARIO, seed=20260817, model_mode="scripted")

    assert workload.manifest["evaluation_scope"] == "agent_core"
    assert workload.manifest["generator_version"] == "agent-core-generator-v1"
    assert workload.manifest["seed"] == 20260817
    assert workload.manifest["task_count"] == 20
    assert len(workload.tasks) == 20
    assert workload.manifest["profile_digest"] == register_profile(workload.profile).digest
    assert workload.manifest["scenario_digest"].startswith("sha256:")
    assert workload.manifest["clock"] == {
        "mode": "fixed",
        "wall_time": "2026-08-17T00:00:00.000Z",
        "monotonic_base_s": 1000.0,
    }

    fixture_text = (
        SCENARIO.read_text(encoding="utf-8")
        + (SCENARIO.parent / "contract_v1.json").read_text(encoding="utf-8")
    ).casefold()
    generated_metadata = json.dumps(
        {"manifest": workload.manifest, "oracle": workload.oracle},
        sort_keys=True,
    ).casefold()
    for term in BANNED_DOMAIN_TERMS:
        assert term not in fixture_text
        assert term not in generated_metadata

    runtime_payloads = []
    for planned in workload.tasks:
        task = planned.task
        registered = register_profile(workload.profile)
        projection = registered.project_model_request(
            task,
            now_monotonic_s=workload.monotonic_base_s + planned.at_ms / 1_000,
        )
        runtime_payloads.append(task.model_dump(mode="json"))
        provider_json = json.dumps(projection.to_provider_dict(), sort_keys=True)
        assert "expected" not in provider_json
        assert "provider_condition" not in provider_json
        assert "oracle" not in provider_json
        assert "case_id" not in provider_json
        assert set(task.correlation_metadata.to_dict()) == {"scenario_id", "trace_id"}

    serialized = json.dumps(runtime_payloads, sort_keys=True).casefold()
    assert not any(term in serialized for term in BANNED_DOMAIN_TERMS)


def test_same_seed_is_identical_and_different_seed_changes_only_generated_content() -> None:
    first = generate_workload(SCENARIO, seed=20260817, model_mode="scripted")
    second = generate_workload(SCENARIO, seed=20260817, model_mode="scripted")
    different = generate_workload(SCENARIO, seed=20260818, model_mode="scripted")

    assert first.manifest == second.manifest
    assert [task.task for task in first.tasks] == [task.task for task in second.tasks]
    assert first.oracle == second.oracle
    assert [task.at_ms for task in first.tasks] == [task.at_ms for task in different.tasks]
    assert [task.expected for task in first.tasks] == [task.expected for task in different.tasks]
    assert [task.task.model_input for task in first.tasks] != [
        task.task.model_input for task in different.tasks
    ]
    assert first.manifest["scenario_digest"] == different.manifest["scenario_digest"]
    assert first.manifest["run_id"] != different.manifest["run_id"]


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("tasks", 0, "provider_condition", "kind"), "invented", "provider kind"),
        (("tasks", 0, "deadline_ms"), 25_000, "registered agent profile"),
        (("core_budget_p95_ms",), float("nan"), "cannot load"),
    ],
)
def test_generator_rejects_malformed_or_unbounded_scenarios(
    tmp_path: Path,
    path: tuple[object, ...],
    value: object,
    message: str,
) -> None:
    scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
    target = scenario
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value

    scenario_path = tmp_path / "pressure_v1.json"
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
    (tmp_path / "contract_v1.json").write_bytes(
        (SCENARIO.parent / "contract_v1.json").read_bytes()
    )

    with pytest.raises(EvaluationArtifactError, match=message):
        generate_workload(scenario_path, seed=20260817, model_mode="scripted")


def test_generator_rejects_duplicate_fixture_object_keys(tmp_path: Path) -> None:
    source = SCENARIO.read_text(encoding="utf-8")
    duplicate = source.replace(
        '"scenario_id": "generic-pressure-v1",',
        '"scenario_id": "generic-pressure-v1",\n  "scenario_id": "ambiguous",',
        1,
    )
    scenario_path = tmp_path / "pressure_v1.json"
    scenario_path.write_text(duplicate, encoding="utf-8")
    (tmp_path / "contract_v1.json").write_bytes(
        (SCENARIO.parent / "contract_v1.json").read_bytes()
    )

    with pytest.raises(EvaluationArtifactError, match="cannot load"):
        generate_workload(scenario_path, seed=20260817, model_mode="scripted")


def test_live_manifest_records_endpoint_and_model_without_credentials(monkeypatch) -> None:
    monkeypatch.setenv("SIDESTAGE_MODEL_BASE_URL", "https://provider.invalid/v1/")
    monkeypatch.setenv("SIDESTAGE_MODEL_ID", "provider-model-pinned")
    monkeypatch.setenv("SIDESTAGE_MODEL_API_KEY", "credential-must-not-be-recorded")
    monkeypatch.setenv("SIDESTAGE_MODEL_REASONING_EFFORT", "none")

    workload = generate_workload(SCENARIO, seed=20260817, model_mode="live")

    assert workload.manifest["model"] == {
        "mode": "live",
        "identifier": "provider-model-pinned",
        "config_ref": "agent-core-evaluation-v1",
        "base_url": "https://provider.invalid/v1",
        "reasoning_effort": "none",
    }
    assert "credential-must-not-be-recorded" not in json.dumps(workload.manifest)
