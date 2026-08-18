from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from sidestage.fixtures.generator import generate_pressure, write_artifacts
from sidestage.fixtures.replay import LivesellReplay, ReplayArtifactError


ROOT = Path(__file__).parents[2]
SCENARIO = ROOT / "fixtures" / "scenarios" / "pressure_v1.json"


def _run(tmp_path: Path) -> Path:
    output = tmp_path / "run"
    write_artifacts(generate_pressure(SCENARIO, seed=20260817), output)
    return output


def _rehash(output: Path, filename: str, manifest_key: str) -> None:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    manifest[manifest_key] = f"sha256:{sha256((output / filename).read_bytes()).hexdigest()}"
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def test_replay_preserves_generated_source_order_and_oracle_is_separate(tmp_path: Path) -> None:
    output = _run(tmp_path)
    replay = LivesellReplay(output)

    assert len(tuple(replay)) == 360
    assert [event.event_id for event in replay.events] == [
        item["event_id"] for item in replay.oracle["events"]
    ]
    first = replay.events[0].model_dump(mode="json")
    assert "expected_route" not in json.dumps(first)
    assert replay.oracle["events"][0]["expected_route"]


def test_replay_rejects_digest_mismatch_with_seed(tmp_path: Path) -> None:
    output = _run(tmp_path)
    with (output / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{}\n")

    with pytest.raises(ReplayArtifactError, match=r"seed=20260817"):
        LivesellReplay(output)


def test_replay_rejects_oracle_metadata_in_runtime_even_with_updated_digest(
    tmp_path: Path,
) -> None:
    output = _run(tmp_path)
    lines = (output / "events.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["expected_route"] = "eligible"
    lines[0] = json.dumps(first, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    (output / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _rehash(output, "events.jsonl", "events_digest")

    with pytest.raises(ReplayArtifactError, match=r"seed=20260817.*event_id=.*malformed"):
        LivesellReplay(output)


def test_replay_rejects_reordered_events_even_with_updated_digest(tmp_path: Path) -> None:
    output = _run(tmp_path)
    lines = (output / "events.jsonl").read_text(encoding="utf-8").splitlines()
    lines[0], lines[1] = lines[1], lines[0]
    (output / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _rehash(output, "events.jsonl", "events_digest")

    with pytest.raises(ReplayArtifactError, match=r"seed=20260817"):
        LivesellReplay(output)


def test_replay_does_not_reuse_previous_event_identity_for_malformed_line(
    tmp_path: Path,
) -> None:
    output = _run(tmp_path)
    lines = (output / "events.jsonl").read_text(encoding="utf-8").splitlines()
    lines[1] = "{"
    (output / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(
        ReplayArtifactError,
        match=r"event_id=unknown line=2",
    ):
        LivesellReplay(output)


def test_replay_rejects_oracle_quota_or_route_tampering_after_rehash(
    tmp_path: Path,
) -> None:
    output = _run(tmp_path)
    oracle = json.loads((output / "oracle.json").read_text(encoding="utf-8"))
    paired_parent_ids = {
        item["canonical_event_id"]
        for item in oracle["events"]
        if item["expected_bucket"] == "duplicate_child"
    }
    parent = next(
        item
        for item in oracle["events"]
        if item["expected_bucket"] == "answerable_parent"
        and item["event_id"] not in paired_parent_ids
    )
    parent["expected_bucket"] = "prompt_injection"
    parent["expected_route"] = "adversarial"
    (output / "oracle.json").write_text(
        json.dumps(oracle, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    _rehash(output, "oracle.json", "oracle_digest")

    with pytest.raises(ReplayArtifactError, match=r"seed=20260817.*quota mismatch"):
        LivesellReplay(output)


def test_replay_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    output = _run(tmp_path)
    manifest = (output / "manifest.json").read_text(encoding="utf-8")
    manifest = manifest.replace(
        '"schema_version":"sidestage.livesell_manifest.v1",',
        '"schema_version":"sidestage.livesell_manifest.v1","schema_version":"sidestage.livesell_manifest.v1",',
    )
    (output / "manifest.json").write_text(manifest, encoding="utf-8")

    with pytest.raises(ReplayArtifactError, match="malformed manifest.json"):
        LivesellReplay(output)
