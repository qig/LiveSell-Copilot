"""Sanitized, ephemeral observations of the authoritative M2.1 fixture import."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic_ns
from typing import Dict, Mapping, Optional
from uuid import uuid4

from sidestage.config import DEFAULT_SELLERS_FIXTURE
from sidestage.fixtures.loader import load_seller_fixture


IMPORT_STAGE_CATALOG = (
    (1, "source_read", "Read source"),
    (2, "contract_validation", "Validate contract"),
    (3, "approved_seller_set", "Approve sellers"),
    (4, "tenant_index_build", "Build tenant indexes"),
)
IMPORT_STAGE_KEYS = [stage[1] for stage in IMPORT_STAGE_CATALOG]


class ImportTraceRecorder:
    """Collect loader observations without retaining source or exception payloads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.trace_id = f"import_{uuid4().hex[:16]}"
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._started_ns: Dict[str, int] = {}
        self._observations: Dict[str, dict] = {}

    def observe(self, stage: str, state: str, details: Mapping[str, object]) -> None:
        if stage not in IMPORT_STAGE_KEYS:
            return
        if state == "started":
            self._started_ns[stage] = monotonic_ns()
            return

        started_ns = self._started_ns.get(stage, monotonic_ns())
        duration_ms = max(0, round((monotonic_ns() - started_ns) / 1_000_000, 3))
        allowed_details = _sanitize_details(stage, details)
        self._observations[stage] = {
            "state": state,
            "duration_ms": duration_ms,
            "reason_code": allowed_details.pop("reason_code", None),
            "details": allowed_details,
        }

    def build(self, catalog: object = None) -> dict:
        stages = []
        failure_seen = False
        first_stop: Optional[dict] = None

        for number, key, label in IMPORT_STAGE_CATALOG:
            observation = self._observations.get(key)
            if observation is None or failure_seen:
                stage = {
                    "number": number,
                    "key": key,
                    "label": label,
                    "state": "skipped",
                    "duration_ms": 0,
                    "reason_code": None,
                    "details": {},
                }
            else:
                stage = {"number": number, "key": key, "label": label, **observation}

            if stage["state"] == "failed" and first_stop is None:
                failure_seen = True
                first_stop = {
                    "stage": number,
                    "key": key,
                    "reason_code": stage["reason_code"],
                }
            stages.append(stage)

        accepted = first_stop is None and catalog is not None
        source_observation = self._observations.get("source_read", {})
        source_details = source_observation.get("details", {})
        outcome = None
        if accepted:
            counts = catalog.counts
            outcome = {
                "counts": asdict(counts),
                "seller_ids": [seller.seller_id for seller in catalog.document.sellers],
            }

        return {
            "schema_version": "sidestage.import_trace.v1",
            "runtime_source": "m2_1_typed_loader",
            "durability": "ephemeral",
            "trace_id": self.trace_id,
            "started_at": self.started_at,
            "status": "accepted" if accepted else "rejected",
            "source": {
                "filename": self.path.name,
                "sha256": source_details.get("sha256"),
                "byte_count": source_details.get("byte_count"),
            },
            "stages": stages,
            "first_stop": first_stop,
            "outcome": outcome,
        }


def _sanitize_details(stage: str, details: Mapping[str, object]) -> dict:
    allowed_by_stage = {
        "source_read": {"byte_count", "sha256", "reason_code"},
        "contract_validation": {
            "seller_count",
            "validation_error_count",
            "reason_code",
        },
        "approved_seller_set": {"seller_ids", "reason_code"},
        "tenant_index_build": {
            "products",
            "listings",
            "variants",
            "reason_code",
        },
    }
    return {key: value for key, value in details.items() if key in allowed_by_stage[stage]}


def trace_seller_fixture_import(path: Path = DEFAULT_SELLERS_FIXTURE) -> dict:
    """Run the actual M2.1 import and return a sanitized diagnostic projection."""

    recorder = ImportTraceRecorder(path)
    catalog = None
    try:
        catalog = load_seller_fixture(path, observer=recorder.observe)
    except Exception:
        pass
    return recorder.build(catalog)
