from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

import pytest

from sidestage.app import create_app
from sidestage.copilot.pipeline import RawCustomerReplyEvent, process_customer_reply
from sidestage.marketplace.authority import SellerAuthority
from sidestage.marketplace.service import PushRequest
from sidestage.trace.recorder import BufferedTraceSink, TraceRecorder
from sidestage.trace.pressure import evaluate_pressure
from .test_r3_safety import R3ScenarioRunner
from .test_reply_pipeline_trace import _raw, _services


FIXED_TIME = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
PRESSURE_SCENARIO = Path(__file__).parents[2] / "fixtures" / "scenarios" / "pressure_v1.json"


class BlockingScenarioRunner(R3ScenarioRunner):
    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()
        self.active = 0
        self.max_active = 0

    async def run(self, invocation):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await self.release.wait()
            return await super().run(invocation)
        finally:
            self.active -= 1


class FakeMonotonic:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class AdvancingScenarioRunner(R3ScenarioRunner):
    def __init__(self, clock: FakeMonotonic, delays: list[float]) -> None:
        super().__init__()
        self.clock = clock
        self.delays = iter(delays)

    async def run(self, invocation):
        self.clock.value += next(self.delays)
        return await super().run(invocation)


def _authority(seller_id: str) -> SellerAuthority:
    return SellerAuthority(
        seller_id=seller_id,
        show_id=f"show_{seller_id.removeprefix('sel_')}",
        actor_id=f"latency_{seller_id.removeprefix('sel_')}",
    )


def _push_first_listing(app, authority: SellerAuthority) -> None:
    listing_id = app.state.pipeline_services.catalog.seller(
        authority.seller_id
    ).products[0].listing.listing_id
    receipt = app.state.marketplace.push(
        authority,
        PushRequest(target_listing_id=listing_id, expected_show_version=1),
        idempotency_key=f"latency-push-{authority.seller_id}",
    )
    assert receipt.status == "applied"


def _raw_question(authority: SellerAuthority, ordinal: int) -> RawCustomerReplyEvent:
    return RawCustomerReplyEvent(
        authority=authority,
        customer_display_name=f"tester_{ordinal}",
        raw_text=f"How much is this pair question {ordinal}?",
        input_origin="custom",
    )


def test_sixty_fifth_candidate_is_seller_visible_without_starting_any_model_call(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        runner = BlockingScenarioRunner()
        app = create_app(
            database_path=tmp_path / "capacity.sqlite3",
            wall_clock=lambda: FIXED_TIME,
            model_runner=runner,
        )
        authority = _authority("sel_velocity_kicks")
        _push_first_listing(app, authority)
        try:
            tasks = [
                asyncio.create_task(
                    process_customer_reply(
                        _raw_question(authority, index),
                        app.state.pipeline_services,
                    )
                )
                for index in range(64)
            ]
            for _ in range(500):
                if app.state.work_scheduler.accepted_count == 64 and runner.active == 4:
                    break
                await asyncio.sleep(0.001)
            assert app.state.work_scheduler.accepted_count == 64
            assert len(runner.calls) == 0
            assert runner.active == 4

            rejected = await process_customer_reply(
                _raw_question(authority, 64),
                app.state.pipeline_services,
            )
            assert rejected.reason_code == "capacity_exceeded"
            assert rejected.publication["state"] == "needs_seller"
            assert rejected.latency.boundary == "r2_inbox_sse"
            assert runner.active == 4
            assert len(runner.calls) == 0

            runner.release.set()
            results = await asyncio.gather(*tasks)
            assert all(result.publication["state"] == "awaiting_review" for result in results)
            assert len(runner.calls) == 128
            assert app.state.work_scheduler.max_show_active[authority.show_id] == 4
            assert app.state.work_scheduler.capacity_rejection_count == 1
            with app.state.database.read() as connection:
                assert connection.execute("SELECT COUNT(*) FROM chat_events").fetchone()[0] == 65
        finally:
            app.state.trace_sink.close()

    asyncio.run(exercise())


def test_three_sellers_are_capped_at_four_each_and_twelve_globally(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        runner = BlockingScenarioRunner()
        app = create_app(
            database_path=tmp_path / "global-concurrency.sqlite3",
            wall_clock=lambda: FIXED_TIME,
            model_runner=runner,
        )
        authorities = [
            _authority("sel_velocity_kicks"),
            _authority("sel_vault_consign"),
            _authority("sel_rotation_kicks"),
        ]
        for authority in authorities:
            _push_first_listing(app, authority)
        try:
            tasks = [
                asyncio.create_task(
                    process_customer_reply(
                        _raw_question(authority, seller_index * 10 + ordinal),
                        app.state.pipeline_services,
                    )
                )
                for seller_index, authority in enumerate(authorities)
                for ordinal in range(5)
            ]
            for _ in range(500):
                if runner.active == 12:
                    break
                await asyncio.sleep(0.001)
            assert runner.active == 12
            snapshot = app.state.work_scheduler.snapshot()
            assert snapshot["max_global_active"] == 12
            assert snapshot["max_show_active"] == {
                authority.show_id: 4 for authority in authorities
            }
            runner.release.set()
            await asyncio.gather(*tasks)
        finally:
            app.state.trace_sink.close()

    asyncio.run(exercise())


def test_acceptance_to_r2_publication_counts_slo_miss_without_discard(
    tmp_path: Path,
) -> None:
    clock = FakeMonotonic()
    runner = AdvancingScenarioRunner(clock, [1.05, 1.05])
    app = create_app(
        database_path=tmp_path / "slo-miss.sqlite3",
        wall_clock=lambda: FIXED_TIME,
        monotonic_clock=clock,
        model_runner=runner,
    )
    authority = _authority("sel_velocity_kicks")
    _push_first_listing(app, authority)
    try:
        result = asyncio.run(
            process_customer_reply(_raw_question(authority, 1), app.state.pipeline_services)
        )
    finally:
        app.state.trace_sink.close()

    assert result.status.value == "completed"
    assert result.publication["state"] == "awaiting_review"
    assert result.latency.boundary == "r2_inbox_sse"
    assert result.latency.total_ms == pytest.approx(2100.0)
    assert result.latency.slo_missed is True
    assert result.latency.hard_timeout_outcome is False


def test_result_after_hard_deadline_becomes_typed_needs_seller_timeout(
    tmp_path: Path,
) -> None:
    clock = FakeMonotonic()
    runner = AdvancingScenarioRunner(clock, [5.01])
    app = create_app(
        database_path=tmp_path / "hard-timeout.sqlite3",
        wall_clock=lambda: FIXED_TIME,
        monotonic_clock=clock,
        model_runner=runner,
    )
    authority = _authority("sel_velocity_kicks")
    _push_first_listing(app, authority)
    try:
        result = asyncio.run(
            process_customer_reply(_raw_question(authority, 1), app.state.pipeline_services)
        )
    finally:
        app.state.trace_sink.close()

    assert result.status.value == "failed"
    assert result.reason_code == "hard_timeout"
    assert result.publication == {
        "question_id": result.question_id,
        "state": "needs_seller",
        "reason_code": "hard_timeout",
    }
    assert result.latency.total_ms == pytest.approx(5010.0)
    assert result.latency.slo_missed is True
    assert result.latency.hard_timeout_outcome is True
    assert len(runner.calls) == 1


def test_blocked_trace_persistence_cannot_block_reply_completion() -> None:
    class BlockingTraceSink:
        def __init__(self) -> None:
            self.release = Event()
            self.observations = []
            self.artifacts = []

        def emit(self, observation) -> None:
            self.release.wait(timeout=2)
            self.observations.append(observation)

        def record_artifact(self, **artifact) -> None:
            self.release.wait(timeout=2)
            self.artifacts.append(artifact)

    async def exercise():
        backing = BlockingTraceSink()
        buffered = BufferedTraceSink(backing, capacity=128)
        recorder = TraceRecorder(
            sink=buffered,
            wall_clock=lambda: FIXED_TIME,
            monotonic=lambda: 100.0,
        )
        calls: list[str] = []
        result = await asyncio.wait_for(
            process_customer_reply(_raw(), _services(calls, recorder)),
            timeout=0.25,
        )
        assert result.status.value == "completed"
        assert buffered.snapshot()["queued"] > 0
        backing.release.set()
        buffered.flush()
        snapshot = buffered.snapshot()
        buffered.close()
        return backing, snapshot

    backing, snapshot = asyncio.run(exercise())
    assert len(backing.observations) == 16
    assert Counter(item.status.value for item in backing.observations) == {
        "started": 8,
        "completed": 8,
    }
    assert snapshot["dropped_count"] == 0
    assert snapshot["failure_count"] == 0


def test_scripted_pressure_replays_three_exact_workloads_with_full_accounting() -> None:
    report = evaluate_pressure(
        PRESSURE_SCENARIO,
        seed=20260817,
        model_mode="scripted",
        time_scale=0.0,
    )

    assert report["evaluation_scope"] == "sidestage_e2e"
    assert report["evaluation_mode"] == "scripted"
    assert report["evidence_maturity"] == "Implemented"
    assert report["event_count"] == report["raw_event_count"] == 360
    assert report["seller_count"] == 3
    assert report["per_seller_chat_count"] == 120
    assert report["burst_window"] == {
        "start_ms": 10_000,
        "end_ms": 12_000,
        "event_count": 20,
    }
    assert report["control_event_count"] == 3
    assert all(not item["chat_denominator"] for item in report["control_events"])
    assert set(report["invariants"].values()) == {0}
    assert report["scheduler"]["max_global_active"] == 12
    assert set(report["scheduler"]["max_show_active"].values()) == {4}
    assert report["latency"]["total_ms"]["count"] == 360
    assert report["stage_latency"]["registered_reply_agent"]["count"] > 0
    assert report["scorecard"]["answerable_supported_suggestions"] == {
        "total": 72,
        "passed": 72,
        "rate": 1.0,
        "minimum_rate": 0.95,
    }
    assert report["scorecard_passed"] is True
    assert report["slo_applicable"] is False
    assert report["profile_digest"] == report["model"]["profile_digest"]
    assert report["implementation_commit"]
    assert report["worktree_dirty"] is True
    assert report["passed"] is True
    assert "does not establish GMV" in report["claims_boundary"]


def test_one_call_pressure_uses_one_request_per_admitted_parent_and_same_safety_gates() -> None:
    report = evaluate_pressure(
        PRESSURE_SCENARIO,
        seed=20260817,
        model_mode="scripted",
        time_scale=0.0,
        strategy="one_call_template",
    )

    assert report["workflow_strategy"] == "one_call_template"
    assert report["model_request_count"] == 135
    assert set(report["invariants"].values()) == {0}
    assert report["scorecard"]["answerable_supported_suggestions"] == {
        "total": 72,
        "passed": 72,
        "rate": 1.0,
        "minimum_rate": 0.95,
    }
    assert report["passed"] is True
