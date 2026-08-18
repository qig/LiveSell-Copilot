"""Strict incremental replay loader for retained livesell artifacts."""

from __future__ import annotations

from hashlib import sha256
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from pydantic import ValidationError

from sidestage.config import REPOSITORY_ROOT
from sidestage.fixtures.generator import (
    EVENT_SCHEMA_VERSION,
    GENERATOR_VERSION,
    MANIFEST_SCHEMA_VERSION,
    ORACLE_SCHEMA_VERSION,
    OracleEvent,
    RuntimeChatEvent,
)


_FORBIDDEN_RUNTIME_KEYS = {
    "fixture_class",
    "seller_scope",
    "weight",
    "emission_mode",
    "required_scenario_capabilities",
    "scenario_capabilities",
    "expected_bucket",
    "expected_route",
    "expected_outcome",
    "canonical_event_id",
    "oracle",
}
_EXPECTED_ROUTES = {
    "noise": "noise",
    "answerable_parent": "eligible",
    "duplicate_child": "duplicate",
    "ambiguous_or_unsupported": "ambiguous_or_unsupported",
    "prompt_injection": "adversarial",
}


class ReplayArtifactError(ValueError):
    pass


class LivesellReplay:
    def __init__(
        self,
        run_directory: Path,
        *,
        sellers_path: Path = REPOSITORY_ROOT / "fixtures" / "sellers.json",
        chat_path: Path = REPOSITORY_ROOT / "fixtures" / "chat_messages.json",
        scenario_path: Path = REPOSITORY_ROOT / "fixtures" / "scenarios" / "pressure_v1.json",
    ) -> None:
        self.run_directory = run_directory
        self.sellers_path = sellers_path
        self.chat_path = chat_path
        self.scenario_path = scenario_path
        self.manifest = self._load_json(run_directory / "manifest.json")
        self.seed = self.manifest.get("seed", "unknown")
        self.events = self._load_events(run_directory / "events.jsonl")
        self.oracle = self._load_oracle(run_directory / "oracle.json")
        self._validate()

    def __iter__(self) -> Iterator[RuntimeChatEvent]:
        return iter(self.events)

    def _load_json(self, path: Path):
        try:
            return json.loads(
                path.read_text(encoding="utf-8"),
                parse_constant=_reject_json_constant,
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (OSError, json.JSONDecodeError, ReplayArtifactError) as error:
            raise ReplayArtifactError(f"seed=unknown: malformed {path.name}") from error

    def _load_events(self, path: Path) -> tuple[RuntimeChatEvent, ...]:
        events = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise ReplayArtifactError(f"seed={self.seed}: cannot read events.jsonl") from error
        for line_number, line in enumerate(lines, start=1):
            raw = None
            try:
                raw = json.loads(
                    line,
                    parse_constant=_reject_json_constant,
                    object_pairs_hook=_reject_duplicate_keys,
                )
                self._reject_runtime_metadata(raw)
                events.append(RuntimeChatEvent.model_validate(raw, strict=False))
            except (json.JSONDecodeError, ValidationError, ReplayArtifactError) as error:
                event_id = raw.get("event_id", "unknown") if isinstance(locals().get("raw"), dict) else "unknown"
                raise ReplayArtifactError(
                    f"seed={self.seed} event_id={event_id} line={line_number}: malformed runtime event"
                ) from error
        return tuple(events)

    def _load_oracle(self, path: Path) -> dict:
        oracle = self._load_json(path)
        if oracle.get("schema_version") != ORACLE_SCHEMA_VERSION:
            raise ReplayArtifactError(f"seed={self.seed}: invalid oracle schema")
        try:
            oracle["events"] = [
                OracleEvent.model_validate(item, strict=False).model_dump(mode="json")
                for item in oracle["events"]
            ]
        except (KeyError, ValidationError) as error:
            raise ReplayArtifactError(f"seed={self.seed}: malformed oracle") from error
        return oracle

    @classmethod
    def _reject_runtime_metadata(cls, value) -> None:
        if isinstance(value, dict):
            forbidden = _FORBIDDEN_RUNTIME_KEYS & set(value)
            if forbidden:
                raise ReplayArtifactError(
                    f"runtime event contains evaluator metadata: {sorted(forbidden)}"
                )
            for child in value.values():
                cls._reject_runtime_metadata(child)
        elif isinstance(value, list):
            for child in value:
                cls._reject_runtime_metadata(child)

    def _validate(self) -> None:
        if self.manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise ReplayArtifactError(f"seed={self.seed}: invalid manifest schema")
        if self.manifest.get("generator_version") != GENERATOR_VERSION:
            raise ReplayArtifactError(f"seed={self.seed}: generator version mismatch")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ReplayArtifactError("seed=unknown: invalid manifest seed")
        run_id = self.manifest.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ReplayArtifactError(f"seed={self.seed}: invalid run ID")
        seller_ids = self.manifest.get("seller_ids")
        if (
            not isinstance(seller_ids, list)
            or len(seller_ids) != 3
            or len(set(seller_ids)) != 3
            or not all(isinstance(item, str) and item for item in seller_ids)
        ):
            raise ReplayArtifactError(f"seed={self.seed}: invalid seller set")
        if self.oracle.get("seed") != self.seed or self.oracle.get("run_id") != run_id:
            raise ReplayArtifactError(f"seed={self.seed}: oracle identity mismatch")
        if any(event.schema_version != EVENT_SCHEMA_VERSION for event in self.events):
            raise ReplayArtifactError(f"seed={self.seed}: event schema mismatch")
        expected_digests = {
            "sellers": _digest(self.sellers_path),
            "chat_messages": _digest(self.chat_path),
            "scenario": _digest(self.scenario_path),
        }
        if self.manifest.get("input_digests") != expected_digests:
            raise ReplayArtifactError(f"seed={self.seed}: input digest mismatch")
        event_bytes = (self.run_directory / "events.jsonl").read_bytes()
        oracle_bytes = (self.run_directory / "oracle.json").read_bytes()
        if self.manifest.get("events_digest") != f"sha256:{sha256(event_bytes).hexdigest()}":
            raise ReplayArtifactError(f"seed={self.seed}: events digest mismatch")
        if self.manifest.get("oracle_digest") != f"sha256:{sha256(oracle_bytes).hexdigest()}":
            raise ReplayArtifactError(f"seed={self.seed}: oracle digest mismatch")
        if len(self.events) != int(self.manifest.get("event_count", -1)):
            raise ReplayArtifactError(f"seed={self.seed}: event count mismatch")
        if any(event.run_id != run_id for event in self.events):
            raise ReplayArtifactError(f"seed={self.seed}: event run mismatch")
        if set(event.seller_id for event in self.events) != set(seller_ids):
            raise ReplayArtifactError(f"seed={self.seed}: event seller mismatch")
        event_ids = [event.event_id for event in self.events]
        if len(set(event_ids)) != len(event_ids):
            raise ReplayArtifactError(f"seed={self.seed}: duplicate event ID")
        if [item["event_id"] for item in self.oracle["events"]] != event_ids:
            raise ReplayArtifactError(f"seed={self.seed}: oracle/event ordering mismatch")
        oracle_by_id = {item["event_id"]: item for item in self.oracle["events"]}
        if len(oracle_by_id) != len(self.oracle["events"]):
            raise ReplayArtifactError(f"seed={self.seed}: duplicate oracle event ID")
        try:
            run_started_at = datetime.fromisoformat(
                self.manifest["run_started_at"].replace("Z", "+00:00")
            )
            duration_ms = self.manifest["duration_ms"]
            quotas = self.manifest["per_seller_quotas"]
            manifest_counts = self.manifest["per_seller_counts"]
            window = self.manifest["burst_window"]
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise ReplayArtifactError(f"seed={self.seed}: malformed manifest contract") from error
        if run_started_at.tzinfo is None or run_started_at.utcoffset() != timedelta(0):
            raise ReplayArtifactError(f"seed={self.seed}: invalid run clock")
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int) or duration_ms <= 0:
            raise ReplayArtifactError(f"seed={self.seed}: invalid duration")
        by_seller: dict[str, list[RuntimeChatEvent]] = {}
        for event in self.events:
            by_seller.setdefault(event.seller_id, []).append(event)
        for seller_id, events in by_seller.items():
            if any(
                event.show_id != f"show_{seller_id.removeprefix('sel_')}"
                or not 0 <= event.at_ms < duration_ms
                or event.source_occurred_at != run_started_at + timedelta(milliseconds=event.at_ms)
                for event in events
            ):
                raise ReplayArtifactError(f"seed={self.seed} seller={seller_id}: event scope/time mismatch")
            if [event.show_seq for event in events] != list(range(1, len(events) + 1)):
                raise ReplayArtifactError(f"seed={self.seed} seller={seller_id}: show order mismatch")
            if any(events[index].at_ms > events[index + 1].at_ms for index in range(len(events) - 1)):
                raise ReplayArtifactError(f"seed={self.seed} seller={seller_id}: time order mismatch")
            burst_count = sum(
                window["start_ms"] <= event.at_ms < window["end_ms"] for event in events
            )
            if burst_count != window["event_count"]:
                raise ReplayArtifactError(f"seed={self.seed} seller={seller_id}: burst mismatch")
            counts: dict[str, int] = {}
            by_id = {event.event_id: event for event in events}
            for event in events:
                label = oracle_by_id[event.event_id]
                if label["seller_id"] != seller_id:
                    raise ReplayArtifactError(f"seed={self.seed} event_id={event.event_id}: oracle tenant mismatch")
                bucket = label["expected_bucket"]
                counts[bucket] = counts.get(bucket, 0) + 1
                if label["expected_route"] != _EXPECTED_ROUTES[bucket]:
                    raise ReplayArtifactError(
                        f"seed={self.seed} event_id={event.event_id}: oracle route mismatch"
                    )
                parent_id = label["canonical_event_id"]
                if bucket == "duplicate_child":
                    parent = by_id.get(parent_id)
                    if (
                        parent is None
                        or event.show_seq != parent.show_seq + 1
                        or event.at_ms != parent.at_ms + 1
                        or oracle_by_id[parent_id]["expected_bucket"] != "answerable_parent"
                    ):
                        raise ReplayArtifactError(
                            f"seed={self.seed} event_id={event.event_id}: invalid canonical link"
                        )
                elif parent_id is not None:
                    raise ReplayArtifactError(
                        f"seed={self.seed} event_id={event.event_id}: unexpected canonical link"
                    )
            if counts != quotas or manifest_counts.get(seller_id) != counts:
                raise ReplayArtifactError(f"seed={self.seed} seller={seller_id}: quota mismatch")


def _digest(path: Path) -> str:
    try:
        return f"sha256:{sha256(path.read_bytes()).hexdigest()}"
    except OSError as error:
        raise ReplayArtifactError(f"cannot digest input {path.name}") from error


def _reject_json_constant(value: str):
    raise ReplayArtifactError(f"non-finite JSON constant is forbidden: {value}")


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReplayArtifactError(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result
