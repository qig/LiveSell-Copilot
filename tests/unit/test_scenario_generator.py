from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from sidestage.fixtures.generator import (
    GenerationError,
    _weighted_sample_without_replacement,
    generate_pressure,
    write_artifacts,
)


ROOT = Path(__file__).parents[2]
SCENARIO = ROOT / "fixtures" / "scenarios" / "pressure_v1.json"


def test_pressure_generator_is_quota_first_and_has_exact_burst_semantics() -> None:
    artifacts = generate_pressure(SCENARIO, seed=20260817)
    oracle_by_id = {item["event_id"]: item for item in artifacts.oracle["events"]}
    events_by_seller = defaultdict(list)
    for event in artifacts.events:
        events_by_seller[event.seller_id].append(event)

    assert len(artifacts.events) == 360
    for seller_id, events in events_by_seller.items():
        assert len(events) == 120
        assert [event.show_seq for event in events] == list(range(1, 121))
        counts = Counter(oracle_by_id[event.event_id]["expected_bucket"] for event in events)
        assert counts == {
            "noise": 60,
            "answerable_parent": 24,
            "duplicate_child": 20,
            "ambiguous_or_unsupported": 8,
            "prompt_injection": 8,
        }
        assert sum(10_000 <= event.at_ms < 12_000 for event in events) == 20
        assert all(0 <= event.at_ms < 30_000 for event in events)

        by_id = {event.event_id: event for event in events}
        duplicate_children = [
            event
            for event in events
            if oracle_by_id[event.event_id]["expected_bucket"] == "duplicate_child"
        ]
        assert len(duplicate_children) == 20
        for child in duplicate_children:
            parent = by_id[oracle_by_id[child.event_id]["canonical_event_id"]]
            assert child.show_seq == parent.show_seq + 1
            assert child.at_ms == parent.at_ms + 1


def test_same_seed_and_inputs_are_byte_identical_and_runtime_stream_has_no_oracle(
    tmp_path: Path,
) -> None:
    first = generate_pressure(SCENARIO, seed=20260817)
    second = generate_pressure(SCENARIO, seed=20260817)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    write_artifacts(first, first_dir)
    write_artifacts(second, second_dir)

    for filename in ("manifest.json", "events.jsonl", "oracle.json"):
        assert (first_dir / filename).read_bytes() == (second_dir / filename).read_bytes()
    runtime_text = (first_dir / "events.jsonl").read_text(encoding="utf-8")
    for forbidden in (
        "fixture_class",
        "seller_scope",
        "weight",
        "emission_mode",
        "scenario_capabilities",
        "expected_route",
        "expected_bucket",
        "canonical_event_id",
    ):
        assert forbidden not in runtime_text
    assert "expected_route" in (first_dir / "oracle.json").read_text(encoding="utf-8")


def test_authored_normalized_surfaces_and_exact_duplicates_are_emitted_as_events() -> None:
    artifacts = generate_pressure(SCENARIO, seed=20260817)
    text_by_id = {event.event_id: event.payload.raw_text for event in artifacts.events}
    oracle = artifacts.oracle["events"]
    pairs = [
        (
            text_by_id[item["canonical_event_id"]],
            text_by_id[item["event_id"]],
        )
        for item in oracle
        if item["expected_bucket"] == "duplicate_child"
    ]
    assert ("When did the Aero Dash release? 👟", "when did the aero dash release") in pairs
    assert (
        "When did the Heritage High 88 release? 👟",
        "when did the heritage high 88 release",
    ) in pairs
    assert ("Is Flash Arc available in size 9?!", "is flash arc available in size 9") in pairs
    assert any(parent == child for parent, child in pairs)


def test_different_seed_preserves_denominators_but_changes_allowlisted_fields() -> None:
    first = generate_pressure(SCENARIO, seed=20260817)
    second = generate_pressure(SCENARIO, seed=20260818)

    assert first.manifest["per_seller_counts"] == second.manifest["per_seller_counts"]
    assert [event.at_ms for event in first.events] != [event.at_ms for event in second.events]
    assert [event.actor.display_name for event in first.events] != [
        event.actor.display_name for event in second.events
    ]


def test_generator_fails_instead_of_padding_missing_quota_capacity(tmp_path: Path) -> None:
    chat = json.loads((ROOT / "fixtures" / "chat_messages.json").read_text(encoding="utf-8"))
    chat["pools"] = [
        pool for pool in chat["pools"] if pool["fixture_class"] != "prompt_injection"
    ]
    malformed = tmp_path / "chat.json"
    malformed.write_text(json.dumps(chat), encoding="utf-8")

    with pytest.raises(GenerationError, match=r"seed=20260817.*injection quota"):
        generate_pressure(SCENARIO, seed=20260817, chat_path=malformed)


def test_weighted_selection_is_without_replacement_and_does_not_change_quota() -> None:
    items = [
        {"id": "heavy", "weight": 1_000},
        {"id": "light-a", "weight": 1},
        {"id": "light-b", "weight": 1},
    ]
    selected = _weighted_sample_without_replacement(items, 2, random.Random(20260817))

    assert len(selected) == 2
    assert len({item["id"] for item in selected}) == 2
    assert "heavy" in {item["id"] for item in selected}


@pytest.mark.parametrize("malformation", ["non_finite", "duplicate_key"])
def test_generator_rejects_nonstandard_or_ambiguous_json(
    tmp_path: Path,
    malformation: str,
) -> None:
    source = SCENARIO.read_text(encoding="utf-8")
    if malformation == "non_finite":
        source = source.replace('"seed": 20260817', '"seed": NaN')
    else:
        source = source.replace(
            '"scenario_id": "pressure_v1",',
            '"scenario_id": "pressure_v1",\n  "scenario_id": "pressure_v1",',
        )
    scenario = tmp_path / "malformed.json"
    scenario.write_text(source, encoding="utf-8")

    with pytest.raises(GenerationError, match="cannot load generation input"):
        generate_pressure(scenario, seed=20260817)


def test_seed_falls_back_from_cli_to_scenario_to_chat_default(tmp_path: Path) -> None:
    scenario_payload = json.loads(SCENARIO.read_text(encoding="utf-8"))
    scenario_payload.pop("seed")
    scenario = tmp_path / "scenario-without-seed.json"
    scenario.write_text(json.dumps(scenario_payload), encoding="utf-8")

    artifacts = generate_pressure(scenario)

    assert artifacts.manifest["seed"] == 20260817
