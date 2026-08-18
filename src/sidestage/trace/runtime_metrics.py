"""Cold, steady, and combined runtime comparison projection for M3B.5."""

from __future__ import annotations

from collections import defaultdict
import json
import math
from typing import Iterable

from sidestage.storage.database import MarketplaceDatabase


def runtime_latency_projection(
    database: MarketplaceDatabase,
    *,
    seller_id: str,
    show_id: str,
) -> dict:
    with database.read() as connection:
        rows = connection.execute(
            """SELECT q.*, c.trace_id
               FROM copilot_questions q
               JOIN chat_events c ON c.event_id = q.event_id
               WHERE q.seller_id = ? AND q.show_id = ?
                 AND q.sample_phase IS NOT NULL
               ORDER BY q.question_number""",
            (seller_id, show_id),
        ).fetchall()
        samples = [_sample(connection, row) for row in rows]

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for sample in samples:
        grouped[(sample["workflow_id"], sample["model_profile_id"])].append(sample)
    groups = []
    for (workflow_id, model_profile_id), values in sorted(grouped.items()):
        complete_values = [value for value in values if value["total_ms"] is not None]
        cold = [value for value in complete_values if value["sample_phase"] == "cold"]
        steady = [value for value in complete_values if value["sample_phase"] == "steady"]
        groups.append(
            {
                "workflow_id": workflow_id,
                "model_profile_id": model_profile_id,
                "requested_model_id": values[0]["requested_model_id"],
                "provider": values[0]["provider"],
                "resolved_model_ids": sorted(
                    {value["resolved_model_id"] for value in values if value["resolved_model_id"]}
                ),
                "resolved_providers": sorted(
                    {value["resolved_provider"] for value in values if value["resolved_provider"]}
                ),
                "selection_versions": sorted(
                    {int(value["selection_version"]) for value in values}
                ),
                "model_backed_count": len(values),
                "completed_latency_count": len(complete_values),
                "cold": {
                    **_distribution(value["total_ms"] for value in cold),
                    "samples": [_sample_summary(value) for value in cold],
                },
                "steady": _distribution(value["total_ms"] for value in steady),
                "combined": {
                    **_distribution(value["total_ms"] for value in complete_values),
                    "slo_misses": sum(bool(value["slo_missed"]) for value in complete_values),
                    "hard_timeouts": sum(
                        bool(value["hard_timeout_outcome"]) for value in complete_values
                    ),
                },
                "components": {
                    "queue_ms": _distribution(
                        value["queue_ms"] for value in complete_values
                    ),
                    "provider_ms": _distribution(
                        value["provider_ms"] for value in complete_values
                    ),
                    "parse_ms": _distribution(
                        value["parse_ms"] for value in complete_values
                    ),
                    "render_ms": _distribution(
                        value["render_ms"] for value in complete_values
                    ),
                    "broker_publication_ms": _distribution(
                        value["broker_publication_ms"] for value in complete_values
                    ),
                },
                "provider_calls": [
                    call for value in values for call in value["provider_calls"]
                ],
                "token_usage": _usage(values),
                "cost": _cost(values),
            }
        )
    return {
        "schema_version": "sidestage.runtime_latency.v1",
        "seller_id": seller_id,
        "show_id": show_id,
        "percentile_method": "nearest_rank",
        "groups": groups,
    }


def _sample(connection, row) -> dict:
    artifacts = connection.execute(
        """SELECT stage, artifact_kind, payload_json
           FROM copilot_trace_artifacts
           WHERE trace_id = ? ORDER BY artifact_number""",
        (row["trace_id"],),
    ).fetchall()
    latency = None
    provider_calls = []
    provider_ms = 0.0
    parse_ms = 0.0
    for artifact in artifacts:
        payload = json.loads(artifact["payload_json"])
        if artifact["artifact_kind"] == "end_to_end_latency":
            latency = payload
        if artifact["artifact_kind"] not in {"analysis_result", "agent_run_result"}:
            continue
        breakdown = payload.get("latency") or {}
        metadata = payload.get("provider_metadata") or {}
        call = {
            "trace_id": row["trace_id"],
            "stage": artifact["stage"],
            "model_id": payload.get("model_id"),
            "queue_ms": breakdown.get("queue_ms"),
            "provider_ms": breakdown.get("provider_ms"),
            "parse_ms": breakdown.get("parse_ms"),
            "total_ms": breakdown.get("total_ms") or payload.get("duration_ms"),
            "usage": metadata.get("usage"),
            "resolved_provider": metadata.get("resolved_provider"),
            "routing_attempts": metadata.get("routing_attempts"),
        }
        provider_calls.append(call)
        provider_ms += float(call["provider_ms"] or 0.0)
        parse_ms += float(call["parse_ms"] or 0.0)
    stage_rows = connection.execute(
        """SELECT stage_number, duration_ms FROM copilot_trace_observations
           WHERE trace_id = ? AND status IN ('completed', 'failed', 'exited')
             AND stage_number IN (6, 7, 8)""",
        (row["trace_id"],),
    ).fetchall()
    reply_stage_ms = sum(
        float(item["duration_ms"] or 0.0)
        for item in stage_rows
        if int(item["stage_number"]) == 6
    )
    reply_call_ms = sum(
        float(call["total_ms"] or 0.0)
        for call in provider_calls
        if call["stage"] == "registered_reply_agent"
    )
    return {
        "trace_id": row["trace_id"],
        "question_id": row["question_id"],
        "workflow_id": row["workflow_id"],
        "model_profile_id": row["model_profile_id"],
        "requested_model_id": row["requested_model_id"],
        "provider": row["model_provider"],
        "resolved_model_id": row["resolved_model_id"],
        "resolved_provider": row["resolved_provider"],
        "selection_version": row["selection_version"],
        "sample_phase": row["sample_phase"],
        "total_ms": latency.get("total_ms") if latency else None,
        "queue_ms": latency.get("queue_ms") if latency else 0.0,
        "slo_missed": latency.get("slo_missed") if latency else False,
        "hard_timeout_outcome": (
            latency.get("hard_timeout_outcome") if latency else False
        ),
        "provider_ms": provider_ms,
        "parse_ms": parse_ms,
        "render_ms": (
            max(0.0, reply_stage_ms - reply_call_ms)
            if row["workflow_id"] == "one_call_template"
            else 0.0
        ),
        "broker_publication_ms": sum(
            float(item["duration_ms"] or 0.0)
            for item in stage_rows
            if int(item["stage_number"]) in {7, 8}
        ),
        "provider_calls": provider_calls,
    }


def _sample_summary(value: dict) -> dict:
    return {
        "trace_id": value["trace_id"],
        "question_id": value["question_id"],
        "selection_version": value["selection_version"],
        "total_ms": value["total_ms"],
    }


def _distribution(values: Iterable[float | None]) -> dict:
    ordered = sorted(float(value) for value in values if value is not None)
    if not ordered:
        return {"count": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}
    return {
        "count": len(ordered),
        "p50_ms": _nearest_rank(ordered, 0.50),
        "p95_ms": _nearest_rank(ordered, 0.95),
        "max_ms": ordered[-1],
    }


def _nearest_rank(ordered: list[float], percentile: float) -> float:
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _usage(values: list[dict]) -> dict:
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    observed = False
    for value in values:
        for call in value["provider_calls"]:
            usage = call.get("usage")
            if not isinstance(usage, dict):
                continue
            observed = True
            for key in totals:
                token_count = usage.get(key)
                if isinstance(token_count, int):
                    totals[key] += token_count
    return totals if observed else None


def _cost(values: list[dict]) -> dict | None:
    total = 0.0
    upstream_total = 0.0
    observed = 0
    for value in values:
        for call in value["provider_calls"]:
            usage = call.get("usage")
            if not isinstance(usage, dict):
                continue
            cost = usage.get("cost")
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                total += float(cost)
                observed += 1
            upstream = usage.get("upstream_inference_cost")
            if isinstance(upstream, (int, float)) and not isinstance(upstream, bool):
                upstream_total += float(upstream)
    if not observed:
        return None
    return {
        "currency": "USD",
        "observed_call_count": observed,
        "total": total,
        "upstream_inference_total": upstream_total,
    }
