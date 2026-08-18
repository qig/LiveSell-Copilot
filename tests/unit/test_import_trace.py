from __future__ import annotations

import copy
import json
from pathlib import Path

from sidestage.fixtures.import_trace import IMPORT_STAGE_KEYS, trace_seller_fixture_import
from sidestage.fixtures.loader import SellerCatalog, load_seller_fixture


ROOT = Path(__file__).resolve().parents[2]
SELLER_FIXTURE = ROOT / "fixtures" / "sellers.json"


def write_fixture(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "sellers.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def serialized(trace: dict) -> str:
    return json.dumps(trace, sort_keys=True)


def test_accepted_trace_uses_real_m2_1_import_and_reports_bounded_counts() -> None:
    trace = trace_seller_fixture_import(SELLER_FIXTURE)

    assert trace["schema_version"] == "sidestage.import_trace.v1"
    assert trace["runtime_source"] == "m2_1_typed_loader"
    assert trace["durability"] == "ephemeral"
    assert trace["status"] == "accepted"
    assert trace["first_stop"] is None
    assert [stage["key"] for stage in trace["stages"]] == IMPORT_STAGE_KEYS
    assert [stage["state"] for stage in trace["stages"]] == ["passed"] * 4
    assert trace["source"]["filename"] == "sellers.json"
    assert len(trace["source"]["sha256"]) == 64
    assert trace["source"]["byte_count"] > 0
    assert trace["outcome"]["counts"] == {
        "sellers": 3,
        "products": 10,
        "listings": 10,
        "variants": 18,
        "available_units": 21,
    }
    source_seller_ids = [
        seller["seller_id"]
        for seller in json.loads(SELLER_FIXTURE.read_text(encoding="utf-8"))["sellers"]
    ]
    assert trace["outcome"]["seller_ids"] == source_seller_ids
    assert str(ROOT) not in serialized(trace)


def test_contract_rejection_stops_at_validation_without_echoing_source(
    tmp_path: Path,
) -> None:
    payload = json.loads(SELLER_FIXTURE.read_text(encoding="utf-8"))
    invalid = copy.deepcopy(payload)
    marker = "seller_invalid_SHOULD_NOT_LEAK"
    invalid["sellers"][0]["seller_id"] = marker

    trace = trace_seller_fixture_import(write_fixture(tmp_path, invalid))

    assert trace["status"] == "rejected"
    assert trace["first_stop"] == {
        "stage": 2,
        "key": "contract_validation",
        "reason_code": "FIXTURE_CONTRACT_INVALID",
    }
    assert [stage["state"] for stage in trace["stages"]] == [
        "passed",
        "failed",
        "skipped",
        "skipped",
    ]
    assert trace["outcome"] is None
    assert marker not in serialized(trace)
    assert str(tmp_path) not in serialized(trace)


def test_missing_source_stops_before_validation_and_sanitizes_path(tmp_path: Path) -> None:
    missing = tmp_path / "private-parent" / "missing-sellers.json"

    trace = trace_seller_fixture_import(missing)

    assert trace["status"] == "rejected"
    assert trace["source"] == {
        "filename": "missing-sellers.json",
        "sha256": None,
        "byte_count": None,
    }
    assert trace["first_stop"] == {
        "stage": 1,
        "key": "source_read",
        "reason_code": "FIXTURE_UNAVAILABLE",
    }
    assert [stage["state"] for stage in trace["stages"]] == [
        "failed",
        "skipped",
        "skipped",
        "skipped",
    ]
    assert str(tmp_path) not in serialized(trace)


def test_trace_payload_excludes_secrets_source_values_and_stack_details() -> None:
    trace = trace_seller_fixture_import(SELLER_FIXTURE)
    keys: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                keys.add(key)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(trace)
    assert not keys.intersection(
        {"raw_json", "document", "policies", "facts", "traceback", "api_key", "secret"}
    )


def test_diagnostic_observer_cannot_change_import_success() -> None:
    def broken_observer(_stage: str, _state: str, _details: dict) -> None:
        raise RuntimeError("diagnostic sink unavailable")

    catalog = load_seller_fixture(observer=broken_observer)

    assert catalog.counts.sellers == 3


def test_unexpected_index_failure_still_returns_a_sanitized_stage_trace(
    monkeypatch,
) -> None:
    def fail_index_build(_document) -> None:
        raise RuntimeError("private database detail")

    monkeypatch.setattr(SellerCatalog, "from_document", fail_index_build)

    trace = trace_seller_fixture_import(SELLER_FIXTURE)

    assert trace["status"] == "rejected"
    assert trace["first_stop"] == {
        "stage": 4,
        "key": "tenant_index_build",
        "reason_code": "TENANT_INDEX_BUILD_FAILED",
    }
    assert "private database detail" not in serialized(trace)
