"""Quota-first deterministic livesell scenario generator for M3B evaluation."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import random
import subprocess
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sidestage.agent_core import register_profile
from sidestage.config import REPOSITORY_ROOT
from sidestage.copilot.profile import build_livesell_reply_profile
from sidestage.copilot.routing import canonicalize_question


GENERATOR_VERSION = "1.0.0"
EVENT_SCHEMA_VERSION = "sidestage.livesell_event.v1"
MANIFEST_SCHEMA_VERSION = "sidestage.livesell_manifest.v1"
ORACLE_SCHEMA_VERSION = "sidestage.livesell_oracle.v1"


class GenerationError(ValueError):
    """The approved scenario cannot be generated without violating its contract."""


class FrozenGenerationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BurstWindow(FrozenGenerationModel):
    start_ms: int = Field(strict=True, ge=0)
    end_ms: int = Field(strict=True, gt=0)
    event_count: int = Field(strict=True, gt=0)

    @model_validator(mode="after")
    def ordered(self) -> "BurstWindow":
        if self.end_ms <= self.start_ms:
            raise ValueError("burst window must be ordered")
        return self


class PressureQuotas(FrozenGenerationModel):
    noise: int = Field(strict=True, ge=0)
    answerable_parent: int = Field(strict=True, ge=0)
    duplicate_child: int = Field(strict=True, ge=0)
    ambiguous_or_unsupported: int = Field(strict=True, ge=0)
    prompt_injection: int = Field(strict=True, ge=0)

    @property
    def total(self) -> int:
        return sum(self.model_dump().values())


class PressureScenario(FrozenGenerationModel):
    schema_version: Literal["sidestage.livesell_scenario.v1"]
    scenario_id: Literal["pressure_v1"]
    generator_version: Literal[GENERATOR_VERSION]
    seed: Optional[int] = Field(default=None, strict=True, ge=0)
    run_started_at: datetime
    duration_ms: int = Field(strict=True, gt=0)
    burst_window: BurstWindow
    per_seller_quotas: PressureQuotas
    scenario_capabilities: Tuple[str, ...] = ()
    model_config_ref: str

    @model_validator(mode="after")
    def approved_shape(self) -> "PressureScenario":
        if self.run_started_at.tzinfo is None or self.run_started_at.utcoffset() != timedelta(0):
            raise ValueError("run_started_at must use UTC")
        if self.per_seller_quotas.model_dump() != {
            "noise": 60,
            "answerable_parent": 24,
            "duplicate_child": 20,
            "ambiguous_or_unsupported": 8,
            "prompt_injection": 8,
        }:
            raise ValueError("pressure_v1 requires the approved fixed event quotas")
        if self.duration_ms != 30_000:
            raise ValueError("pressure_v1 requires the approved 30-second duration")
        if self.burst_window.model_dump() != {
            "start_ms": 10_000,
            "end_ms": 12_000,
            "event_count": 20,
        }:
            raise ValueError("pressure_v1 requires the approved burst window")
        if self.scenario_capabilities:
            raise ValueError("pressure_v1 accepts only non-temporal answerable pools")
        if self.burst_window.end_ms > self.duration_ms:
            raise ValueError("burst window must be inside scenario duration")
        return self


class RuntimeActor(FrozenGenerationModel):
    actor_type: Literal["synthetic_customer"] = "synthetic_customer"
    actor_id: str
    display_name: str


class RuntimeChatPayload(FrozenGenerationModel):
    raw_text: str = Field(min_length=1, max_length=240)


class RuntimeChatEvent(FrozenGenerationModel):
    schema_version: Literal[EVENT_SCHEMA_VERSION] = EVENT_SCHEMA_VERSION
    event_id: str
    run_id: str
    seller_id: str
    show_id: str
    show_seq: int = Field(strict=True, gt=0)
    at_ms: int = Field(strict=True, ge=0)
    source_occurred_at: datetime
    actor: RuntimeActor
    event_type: Literal["customer_chat"] = "customer_chat"
    payload: RuntimeChatPayload


class OracleEvent(FrozenGenerationModel):
    event_id: str
    seller_id: str
    expected_bucket: Literal[
        "noise",
        "answerable_parent",
        "duplicate_child",
        "ambiguous_or_unsupported",
        "prompt_injection",
    ]
    expected_route: Literal[
        "noise",
        "eligible",
        "duplicate",
        "ambiguous_or_unsupported",
        "adversarial",
    ]
    canonical_event_id: Optional[str] = None


class GeneratedArtifacts(FrozenGenerationModel):
    manifest: Dict[str, Any]
    events: Tuple[RuntimeChatEvent, ...]
    oracle: Dict[str, Any]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, json.JSONDecodeError, GenerationError) as error:
        raise GenerationError(f"cannot load generation input {path.name}") from error


def _reject_json_constant(value: str):
    raise GenerationError(f"non-finite JSON constant is forbidden: {value}")


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GenerationError(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def _digest(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def _seller_seed(seed: int, seller_id: str) -> int:
    digest = sha256(f"{seed}:{seller_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _utc_millis(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _event_id(run_id: str, seller_id: str, ordinal: int, text: str) -> str:
    digest = sha256(f"{run_id}:{seller_id}:{ordinal}:{text}".encode("utf-8")).hexdigest()
    return f"evt_{seller_id.removeprefix('sel_')}_{ordinal:03d}_{digest[:8]}"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _git_metadata() -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        return commit, dirty
    except (OSError, subprocess.SubprocessError):
        return "unavailable", True


def generate_pressure(
    scenario_path: Path,
    *,
    seed: Optional[int] = None,
    sellers_path: Path = REPOSITORY_ROOT / "fixtures" / "sellers.json",
    chat_path: Path = REPOSITORY_ROOT / "fixtures" / "chat_messages.json",
) -> GeneratedArtifacts:
    scenario = PressureScenario.model_validate(_load_json(scenario_path), strict=False)
    seller_document = _load_json(sellers_path)
    chat_document = _load_json(chat_path)
    resolved_seed = (
        seed
        if seed is not None
        else scenario.seed
        if scenario.seed is not None
        else chat_document.get("default_seed")
    )
    if (
        isinstance(resolved_seed, bool)
        or not isinstance(resolved_seed, int)
        or resolved_seed < 0
    ):
        raise GenerationError("seed must be nonnegative")
    sellers = sorted(seller["seller_id"] for seller in seller_document["sellers"])
    if len(sellers) != 3:
        raise GenerationError("pressure_v1 requires exactly three sellers")
    run_id = f"run_{scenario.scenario_id}_{resolved_seed}"

    all_events: list[RuntimeChatEvent] = []
    all_oracle: list[OracleEvent] = []
    per_seller_counts: dict[str, dict[str, int]] = {}
    for seller_id in sellers:
        events, oracle = _generate_seller(
            seller_id,
            run_id,
            resolved_seed,
            scenario,
            chat_document,
        )
        all_events.extend(events)
        all_oracle.extend(oracle)
        per_seller_counts[seller_id] = dict(Counter(item.expected_bucket for item in oracle))

    all_events.sort(key=lambda item: (item.at_ms, item.seller_id, item.show_seq))
    all_oracle.sort(key=lambda item: next(
        index for index, event in enumerate(all_events) if event.event_id == item.event_id
    ))
    event_lines = "".join(
        _canonical_json(event.model_dump(mode="json")) + "\n" for event in all_events
    )
    oracle_payload = {
        "schema_version": ORACLE_SCHEMA_VERSION,
        "run_id": run_id,
        "seed": resolved_seed,
        "events": [item.model_dump(mode="json") for item in all_oracle],
    }
    oracle_bytes = (_canonical_json(oracle_payload) + "\n").encode("utf-8")
    commit, dirty = _git_metadata()
    profile = register_profile(
        build_livesell_reply_profile(model_config_ref=scenario.model_config_ref)
    )
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluation_scope": "sidestage_e2e",
        "scenario_id": scenario.scenario_id,
        "generator_version": GENERATOR_VERSION,
        "run_id": run_id,
        "seed": resolved_seed,
        "run_started_at": _utc_millis(scenario.run_started_at),
        "duration_ms": scenario.duration_ms,
        "burst_window": scenario.burst_window.model_dump(mode="json"),
        "per_seller_quotas": scenario.per_seller_quotas.model_dump(mode="json"),
        "per_seller_counts": per_seller_counts,
        "seller_ids": sellers,
        "event_count": len(all_events),
        "input_digests": {
            "sellers": _digest(sellers_path),
            "chat_messages": _digest(chat_path),
            "scenario": _digest(scenario_path),
        },
        "events_digest": f"sha256:{sha256(event_lines.encode('utf-8')).hexdigest()}",
        "oracle_digest": f"sha256:{sha256(oracle_bytes).hexdigest()}",
        "profile_digest": profile.digest,
        "model_config_ref": scenario.model_config_ref,
        "implementation_commit": commit,
        "worktree_dirty": dirty,
    }
    return GeneratedArtifacts(
        manifest=manifest,
        events=tuple(all_events),
        oracle=oracle_payload,
    )


def _generate_seller(
    seller_id: str,
    run_id: str,
    seed: int,
    scenario: PressureScenario,
    chat_document: dict,
) -> tuple[list[RuntimeChatEvent], list[OracleEvent]]:
    rng = random.Random(_seller_seed(seed, seller_id))
    pools = sorted(chat_document["pools"], key=lambda item: item["pool_id"])
    applicable = [
        pool
        for pool in pools
        if pool["seller_scope"] in {"all", seller_id}
        and not pool.get("required_scenario_capabilities")
    ]
    answerable_classes = {
        "answerable_listing",
        "answerable_policy",
        "answerable_research",
        "mixed_greeting_question",
    }
    candidates: list[dict] = []
    for pool in applicable:
        if (
            pool["fixture_class"] not in answerable_classes
            or pool.get("pressure_answerable") is not True
        ):
            continue
        mode = pool.get("emission_mode", chat_document.get("default_emission_mode", "single_event"))
        if mode == "adjacent_normalized_pair":
            surfaces = pool.get("message_pairs", [])
        else:
            surfaces = [(message, None) for message in pool.get("messages", [])]
        for position, pair in enumerate(surfaces):
            parent = pair[0]
            child = pair[1] if len(pair) > 1 else None
            candidates.append(
                {
                    "parent": parent,
                    "authored_child": child,
                    "mode": mode,
                    "pool_id": pool["pool_id"],
                    "position": position,
                    "canonical": canonicalize_question(parent),
                    "weight": pool.get("weight", 1),
                }
            )
    candidates.sort(key=lambda item: (item["pool_id"], item["position"]))
    canonical_keys = [item["canonical"] for item in candidates]
    if len(candidates) != scenario.per_seller_quotas.answerable_parent:
        raise GenerationError(
            f"seed={seed} seller={seller_id}: pressure-answerable candidates must equal 24"
        )
    if len(set(canonical_keys)) != len(canonical_keys):
        raise GenerationError(f"seed={seed} seller={seller_id}: answerable candidates collide")
    authored_candidates = [item for item in candidates if item["mode"] != "single_event"]
    if len(authored_candidates) > scenario.per_seller_quotas.answerable_parent:
        raise GenerationError(f"seed={seed} seller={seller_id}: authored pair quota overflow")
    selectable = [item for item in candidates if item not in authored_candidates]
    selected = authored_candidates + _weighted_sample_without_replacement(
        selectable,
        scenario.per_seller_quotas.answerable_parent - len(authored_candidates),
        rng,
    )
    authored = [item for item in selected if item["mode"] != "single_event"]
    remaining = [item for item in selected if item not in authored]
    rng.shuffle(remaining)
    duplicate_parents = authored + remaining[
        : scenario.per_seller_quotas.duplicate_child - len(authored)
    ]
    if len(duplicate_parents) != scenario.per_seller_quotas.duplicate_child:
        raise GenerationError(f"seed={seed} seller={seller_id}: duplicate capacity mismatch")
    burst_parents = list(authored)
    non_authored_duplicates = [item for item in duplicate_parents if item not in authored]
    rng.shuffle(non_authored_duplicates)
    burst_parents.extend(non_authored_duplicates[: 10 - len(authored)])
    if len(burst_parents) != 10:
        raise GenerationError(f"seed={seed} seller={seller_id}: burst duplicate capacity mismatch")

    blocks: list[dict] = []
    for candidate in selected:
        entries = [
            {
                "text": candidate["parent"],
                "bucket": "answerable_parent",
                "route": "eligible",
                "canonical_parent": None,
            }
        ]
        if candidate in duplicate_parents:
            entries.append(
                {
                    "text": candidate["authored_child"] or candidate["parent"],
                    "bucket": "duplicate_child",
                    "route": "duplicate",
                    "canonical_parent": 0,
                }
            )
        blocks.append(
            {
                "entries": entries,
                "burst": candidate in burst_parents,
                "stable_key": f"answer:{candidate['pool_id']}:{candidate['position']}",
            }
        )

    by_class: dict[str, list[str]] = {}
    for pool in applicable:
        by_class.setdefault(pool["fixture_class"], []).extend(pool.get("messages", []))
    noise: list[str] = []
    for fixture_class in ("reaction", "off_topic", "greeting", "emoji"):
        noise.extend(sorted(set(by_class.get(fixture_class, []))))
    filler = sorted(set(by_class.get("greeting", []) + by_class.get("emoji", [])))
    if not filler:
        raise GenerationError(f"seed={seed} seller={seller_id}: noise filler is missing")
    while len(noise) < scenario.per_seller_quotas.noise:
        noise.append(rng.choice(filler))
    if len(noise) != scenario.per_seller_quotas.noise:
        raise GenerationError(f"seed={seed} seller={seller_id}: noise quota overflow")
    for index, text in enumerate(noise):
        blocks.append(
            {
                "entries": [{"text": text, "bucket": "noise", "route": "noise", "canonical_parent": None}],
                "burst": False,
                "stable_key": f"noise:{index:03d}",
            }
        )
    ambiguous = sorted(set(by_class.get("ambiguous", []) + by_class.get("unsupported", [])))
    injections = sorted(set(by_class.get("prompt_injection", [])))
    if len(ambiguous) < scenario.per_seller_quotas.ambiguous_or_unsupported:
        raise GenerationError(f"seed={seed} seller={seller_id}: ambiguity quota capacity mismatch")
    if len(injections) < scenario.per_seller_quotas.prompt_injection:
        raise GenerationError(f"seed={seed} seller={seller_id}: injection quota capacity mismatch")
    rng.shuffle(ambiguous)
    rng.shuffle(injections)
    for index, text in enumerate(
        ambiguous[: scenario.per_seller_quotas.ambiguous_or_unsupported]
    ):
        blocks.append(
            {
                "entries": [{"text": text, "bucket": "ambiguous_or_unsupported", "route": "ambiguous_or_unsupported", "canonical_parent": None}],
                "burst": False,
                "stable_key": f"ambiguous:{index:02d}",
            }
        )
    for index, text in enumerate(injections[: scenario.per_seller_quotas.prompt_injection]):
        blocks.append(
            {
                "entries": [{"text": text, "bucket": "prompt_injection", "route": "adversarial", "canonical_parent": None}],
                "burst": False,
                "stable_key": f"injection:{index:02d}",
            }
        )
    if len(blocks) != 100:
        raise GenerationError(f"seed={seed} seller={seller_id}: expected 100 schedulable blocks")

    burst_blocks = sorted((item for item in blocks if item["burst"]), key=lambda item: item["stable_key"])
    other_blocks = [item for item in blocks if not item["burst"]]
    rng.shuffle(other_blocks)
    burst_anchors = list(
        range(scenario.burst_window.start_ms, scenario.burst_window.start_ms + 1000, 100)
    )
    allowed_anchors = list(range(0, scenario.burst_window.start_ms, 100)) + list(
        range(scenario.burst_window.end_ms, scenario.duration_ms, 100)
    )
    if len(allowed_anchors) < len(other_blocks):
        raise GenerationError(f"seed={seed} seller={seller_id}: timing capacity mismatch")
    rng.shuffle(allowed_anchors)
    for block, anchor in zip(burst_blocks, burst_anchors):
        block["at_ms"] = anchor
    for block, anchor in zip(other_blocks, allowed_anchors):
        block["at_ms"] = anchor

    generated: list[dict] = []
    ordinal = 0
    for block in blocks:
        parent_id = None
        for entry_index, entry in enumerate(block["entries"]):
            ordinal += 1
            event_id = _event_id(run_id, seller_id, ordinal, entry["text"])
            if entry_index == 0:
                parent_id = event_id
            generated.append(
                {
                    **entry,
                    "event_id": event_id,
                    "canonical_event_id": parent_id if entry["bucket"] == "duplicate_child" else None,
                    "at_ms": block["at_ms"] + entry_index,
                    "ordinal": ordinal,
                }
            )
    generated.sort(key=lambda item: (item["at_ms"], item["ordinal"]))
    names = tuple(chat_document["customer_names"])
    events: list[RuntimeChatEvent] = []
    oracle: list[OracleEvent] = []
    for show_seq, item in enumerate(generated, start=1):
        display_name = rng.choice(names)
        occurred_at = scenario.run_started_at + timedelta(milliseconds=item["at_ms"])
        events.append(
            RuntimeChatEvent(
                event_id=item["event_id"],
                run_id=run_id,
                seller_id=seller_id,
                show_id=f"show_{seller_id.removeprefix('sel_')}",
                show_seq=show_seq,
                at_ms=item["at_ms"],
                source_occurred_at=occurred_at,
                actor=RuntimeActor(
                    actor_id=f"cus_{sha256((item['event_id'] + display_name).encode()).hexdigest()[:12]}",
                    display_name=display_name,
                ),
                payload=RuntimeChatPayload(raw_text=item["text"]),
            )
        )
        oracle.append(
            OracleEvent(
                event_id=item["event_id"],
                seller_id=seller_id,
                expected_bucket=item["bucket"],
                expected_route=item["route"],
                canonical_event_id=item["canonical_event_id"],
            )
        )
    counts = Counter(item.expected_bucket for item in oracle)
    if counts != Counter(scenario.per_seller_quotas.model_dump()):
        raise GenerationError(f"seed={seed} seller={seller_id}: quota verification failed")
    burst_count = sum(
        scenario.burst_window.start_ms <= item.at_ms < scenario.burst_window.end_ms
        for item in events
    )
    if burst_count != scenario.burst_window.event_count:
        raise GenerationError(f"seed={seed} seller={seller_id}: burst count verification failed")
    return events, oracle


def _weighted_sample_without_replacement(
    items: list[dict],
    count: int,
    rng: random.Random,
) -> list[dict]:
    """Use integer pool weights only after the answerable quota is fixed."""

    if count < 0 or count > len(items):
        raise GenerationError("weighted selection capacity mismatch")
    remaining = list(items)
    selected: list[dict] = []
    for _ in range(count):
        weights = []
        for item in remaining:
            weight = item.get("weight", 1)
            if isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0:
                raise GenerationError("pool weight must be a positive integer")
            weights.append(weight)
        target = rng.randrange(sum(weights))
        cumulative = 0
        selected_index = 0
        for index, weight in enumerate(weights):
            cumulative += weight
            if target < cumulative:
                selected_index = index
                break
        selected.append(remaining.pop(selected_index))
    return selected


def write_artifacts(artifacts: GeneratedArtifacts, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(
        _canonical_json(artifacts.manifest) + "\n",
        encoding="utf-8",
    )
    (output / "events.jsonl").write_text(
        "".join(
            _canonical_json(event.model_dump(mode="json")) + "\n"
            for event in artifacts.events
        ),
        encoding="utf-8",
    )
    (output / "oracle.json").write_text(
        _canonical_json(artifacts.oracle) + "\n",
        encoding="utf-8",
    )


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    artifacts = generate_pressure(args.scenario, seed=args.seed)
    write_artifacts(artifacts, args.output)
    print(
        _canonical_json(
            {
                "status": "generated",
                "run_id": artifacts.manifest["run_id"],
                "seed": artifacts.manifest["seed"],
                "event_count": artifacts.manifest["event_count"],
                "output": str(args.output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
