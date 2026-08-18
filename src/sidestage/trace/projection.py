"""Read-only backend projection for the runtime M3B developer tracer."""

from __future__ import annotations

from collections import Counter
import json
from typing import Optional

from sidestage.storage.database import MarketplaceDatabase


TERMINAL_STATUSES = frozenset({"completed", "failed", "exited", "skipped"})
ROUTE_FILTERS = frozenset(
    {
        "eligible",
        "noise",
        "duplicate",
        "ambiguous_or_unsupported",
        "adversarial",
    }
)


def runtime_trace_projection(
    database: MarketplaceDatabase,
    *,
    seller_id: str,
    show_id: str,
    actual_route: Optional[str] = None,
) -> dict:
    if actual_route is not None and actual_route not in ROUTE_FILTERS:
        raise ValueError("unknown actual-route filter")
    with database.read() as connection:
        all_questions = connection.execute(
            """SELECT q.*, c.customer_display_name, c.accepted_at, c.show_seq,
                      c.trace_id, o.expected_bucket, o.expected_route,
                      o.canonical_event_id
               FROM copilot_questions q
               JOIN chat_events c ON c.event_id = q.event_id
               LEFT JOIN copilot_trace_oracle_labels o ON o.event_id = q.event_id
               WHERE q.seller_id = ? AND q.show_id = ?
               ORDER BY c.show_seq""",
            (seller_id, show_id),
        ).fetchall()
        questions = [
            row for row in all_questions if actual_route is None or row["route"] == actual_route
        ]
        traces = [
            _trace(connection, row)
            for row in questions
        ]
    route_counts = Counter(row["route"] for row in all_questions)
    return {
        "schema_version": "sidestage.runtime_trace_projection.v1",
        "runtime_source": "process_customer_reply.sqlite",
        "seller_id": seller_id,
        "show_id": show_id,
        "actual_route_filter": actual_route or "all",
        "route_counts": {
            route: route_counts.get(route, 0)
            for route in sorted(ROUTE_FILTERS)
        },
        "trace_count": len(traces),
        "traces": traces,
    }


def _trace(connection, question) -> dict:
    observation_rows = connection.execute(
        """SELECT * FROM copilot_trace_observations
           WHERE trace_id = ? ORDER BY observation_number""",
        (question["trace_id"],),
    ).fetchall()
    artifact_rows = connection.execute(
        """SELECT * FROM copilot_trace_artifacts
           WHERE trace_id = ? ORDER BY artifact_number""",
        (question["trace_id"],),
    ).fetchall()
    transition_rows = connection.execute(
        """SELECT * FROM copilot_question_transitions
           WHERE question_id = ? ORDER BY transition_number""",
        (question["question_id"],),
    ).fetchall()
    suggestion = connection.execute(
        "SELECT * FROM copilot_suggestions WHERE question_id = ?",
        (question["question_id"],),
    ).fetchone()
    outbound = connection.execute(
        "SELECT * FROM copilot_outbound_replies WHERE question_id = ?",
        (question["question_id"],),
    ).fetchone()
    receipt = connection.execute(
        "SELECT * FROM copilot_reply_receipts WHERE question_id = ?",
        (question["question_id"],),
    ).fetchone()
    artifacts_by_stage: dict[str, list[dict]] = {}
    for artifact in artifact_rows:
        artifacts_by_stage.setdefault(artifact["stage"], []).append(
            {
                "artifact_id": artifact["artifact_id"],
                "artifact_kind": artifact["artifact_kind"],
                "recorded_at": artifact["recorded_at"],
                "payload": json.loads(artifact["payload_json"]),
            }
        )
    stage_numbers = sorted({int(row["stage_number"]) for row in observation_rows})
    stages = []
    complete = stage_numbers == list(range(1, 9))
    for stage_number in stage_numbers:
        rows = [row for row in observation_rows if int(row["stage_number"]) == stage_number]
        terminals = [row for row in rows if row["status"] in TERMINAL_STATUSES]
        starts = [row for row in rows if row["status"] == "started"]
        if len(terminals) != 1 or len(starts) > 1:
            complete = False
        terminal = terminals[0] if terminals else rows[-1]
        stages.append(
            {
                "stage_number": stage_number,
                "stage": terminal["stage"],
                "component_id": terminal["component_id"],
                "observation_id": terminal["observation_id"],
                "started_observation_id": starts[0]["observation_id"] if starts else None,
                "status": terminal["status"],
                "occurred_at": terminal["occurred_at"],
                "duration_ms": terminal["duration_ms"],
                "input_ref": terminal["input_ref"],
                "output_ref": terminal["output_ref"],
                "verdict": terminal["verdict"],
                "reason_code": terminal["reason_code"],
                "analysis_call_id": terminal["analysis_call_id"],
                "snapshot_id": terminal["snapshot_id"],
                "agent_run_id": terminal["agent_run_id"],
                "profile_digest": terminal["profile_digest"],
                "artifacts": artifacts_by_stage.get(terminal["stage"], []),
            }
        )
    total_duration = sum(
        float(stage["duration_ms"] or 0)
        for stage in stages
        if stage["status"] != "skipped"
    )
    return {
        "trace_id": question["trace_id"],
        "event_id": question["event_id"],
        "question_id": question["question_id"],
        "show_seq": int(question["show_seq"]),
        "customer_display_name": question["customer_display_name"],
        "raw_text": question["raw_text"],
        "accepted_at": question["accepted_at"],
        "actual_route": question["route"],
        "state": question["state"],
        "reason_code": question["reason_code"],
        "bound_sku": question["bound_sku"],
        "bound_listing_id": question["bound_listing_id"],
        "bound_epoch_id": question["bound_epoch_id"],
        "canonical_question_id": question["canonical_question_id"],
        "expected_bucket": question["expected_bucket"],
        "expected_route": question["expected_route"],
        "canonical_event_id": question["canonical_event_id"],
        "complete": complete,
        "total_duration_ms": total_duration,
        "stages": stages,
        "transitions": [dict(row) for row in transition_rows],
        "suggestion": _suggestion(suggestion),
        "outbound_reply": dict(outbound) if outbound is not None else None,
        "reply_receipt": _receipt(receipt),
    }


def _suggestion(row):
    if row is None:
        return None
    return {
        **dict(row),
        "evidence_ids": json.loads(row["evidence_ids_json"]),
        "evidence_snapshot": json.loads(row["evidence_snapshot_json"]),
    }


def _receipt(row):
    if row is None:
        return None
    return {
        **dict(row),
        "evidence_ids": json.loads(row["evidence_ids_json"]),
        "validated_versions": json.loads(row["validated_versions_json"]),
        "warnings": json.loads(row["warnings_json"]),
    }
