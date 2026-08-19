"""Schema and fixture seeding for the local marketplace store."""

from __future__ import annotations

from hashlib import sha256
import sqlite3

from sidestage.fixtures.loader import SellerCatalog


SCHEMA = """
CREATE TABLE IF NOT EXISTS sellers (
    seller_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shows (
    show_id TEXT PRIMARY KEY,
    seller_id TEXT NOT NULL REFERENCES sellers(seller_id),
    active_listing_id TEXT,
    version INTEGER NOT NULL CHECK (version > 0),
    show_seq INTEGER NOT NULL CHECK (show_seq >= 0)
);
CREATE TABLE IF NOT EXISTS listings (
    listing_id TEXT PRIMARY KEY,
    seller_id TEXT NOT NULL REFERENCES sellers(seller_id),
    price_cents INTEGER NOT NULL CHECK (price_cents > 0),
    floor_price_cents INTEGER NOT NULL CHECK (floor_price_cents > 0),
    status TEXT NOT NULL CHECK (status IN ('available', 'unlisted')),
    version INTEGER NOT NULL CHECK (version > 0)
);
CREATE TABLE IF NOT EXISTS inventory (
    variant_id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    seller_id TEXT NOT NULL REFERENCES sellers(seller_id),
    available_quantity INTEGER NOT NULL CHECK (available_quantity >= 0),
    version INTEGER NOT NULL CHECK (version > 0)
);
CREATE TABLE IF NOT EXISTS listing_epochs (
    epoch_number INTEGER PRIMARY KEY AUTOINCREMENT,
    epoch_id TEXT UNIQUE,
    seller_id TEXT NOT NULL REFERENCES sellers(seller_id),
    show_id TEXT NOT NULL REFERENCES shows(show_id),
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    start_seq INTEGER NOT NULL,
    end_seq INTEGER,
    CHECK (end_seq IS NULL OR end_seq >= start_seq)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_epoch_per_show
    ON listing_epochs(show_id) WHERE end_seq IS NULL;
CREATE TABLE IF NOT EXISTS operation_receipts (
    row_number INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id TEXT NOT NULL UNIQUE,
    operation_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    status TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    seller_id TEXT NOT NULL,
    show_id TEXT NOT NULL,
    listing_id TEXT,
    variant_id TEXT,
    request_json TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    expected_versions_json TEXT NOT NULL,
    resulting_versions_json TEXT NOT NULL,
    authorization_verdict TEXT NOT NULL,
    policy_verdict TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    compensation_for_receipt_id TEXT,
    requested_at TEXT NOT NULL,
    executed_at TEXT,
    recorded_at TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    error_code TEXT
);
CREATE TABLE IF NOT EXISTS idempotency_registry (
    seller_id TEXT NOT NULL,
    show_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    receipt_id TEXT NOT NULL REFERENCES operation_receipts(receipt_id),
    PRIMARY KEY (seller_id, show_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS chat_events (
    event_number INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    seller_id TEXT NOT NULL REFERENCES sellers(seller_id),
    show_id TEXT NOT NULL REFERENCES shows(show_id),
    customer_display_name TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    input_origin TEXT NOT NULL CHECK (input_origin IN ('prepared', 'custom')),
    accepted_at TEXT NOT NULL,
    show_seq INTEGER NOT NULL,
    trace_id TEXT NOT NULL UNIQUE,
    source_epoch_id TEXT,
    source_listing_id TEXT,
    workflow_id TEXT,
    model_profile_id TEXT,
    requested_model_id TEXT,
    model_config_ref TEXT,
    model_provider TEXT,
    selection_version INTEGER,
    selection_selected_at TEXT,
    UNIQUE (show_id, show_seq)
);
CREATE TABLE IF NOT EXISTS stream_events (
    stream_offset INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id TEXT NOT NULL REFERENCES sellers(seller_id),
    show_id TEXT NOT NULL REFERENCES shows(show_id),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS stream_events_by_show
    ON stream_events(show_id, stream_offset);
CREATE TABLE IF NOT EXISTS challenge_usage (
    usage_number INTEGER PRIMARY KEY AUTOINCREMENT,
    usage_day TEXT NOT NULL,
    session_token_digest TEXT NOT NULL,
    units INTEGER NOT NULL CHECK (units > 0),
    accepted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS challenge_usage_by_day
    ON challenge_usage(usage_day, session_token_digest);
CREATE TABLE IF NOT EXISTS copilot_questions (
    question_number INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT NOT NULL UNIQUE,
    event_id TEXT NOT NULL UNIQUE REFERENCES chat_events(event_id),
    seller_id TEXT NOT NULL REFERENCES sellers(seller_id),
    show_id TEXT NOT NULL REFERENCES shows(show_id),
    raw_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    canonical_scope TEXT NOT NULL,
    canonical_question_id TEXT REFERENCES copilot_questions(question_id),
    route TEXT NOT NULL,
    state TEXT,
    reason_code TEXT NOT NULL,
    bound_epoch_id TEXT,
    bound_listing_id TEXT,
    bound_sku TEXT,
    binding_basis TEXT,
    binding_status TEXT,
    workflow_id TEXT,
    model_profile_id TEXT,
    requested_model_id TEXT,
    model_config_ref TEXT,
    model_provider TEXT,
    selection_version INTEGER,
    selection_selected_at TEXT,
    sample_phase TEXT,
    resolved_model_id TEXT,
    resolved_provider TEXT,
    asked_at TEXT NOT NULL,
    state_changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS canonical_question_dedup_lookup
    ON copilot_questions(
        seller_id, show_id, canonical_scope, canonical_key, asked_at
    ) WHERE canonical_question_id IS NULL AND route != 'noise';
CREATE INDEX IF NOT EXISTS copilot_questions_by_show
    ON copilot_questions(show_id, question_number);
CREATE TABLE IF NOT EXISTS copilot_question_transitions (
    transition_number INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT NOT NULL REFERENCES copilot_questions(question_id),
    from_state TEXT,
    to_state TEXT NOT NULL,
    asked_at TEXT NOT NULL,
    state_changed_at TEXT NOT NULL,
    reason_code TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS copilot_transitions_by_question
    ON copilot_question_transitions(question_id, transition_number);
CREATE TABLE IF NOT EXISTS copilot_evidence_records (
    evidence_id TEXT PRIMARY KEY,
    seller_id TEXT NOT NULL REFERENCES sellers(seller_id),
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    fact_type TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_version INTEGER NOT NULL CHECK (source_version > 0),
    observed_at TEXT NOT NULL,
    provenance TEXT NOT NULL CHECK (provenance = 'synthetic_seller_data')
);
CREATE INDEX IF NOT EXISTS copilot_evidence_by_scope
    ON copilot_evidence_records(seller_id, listing_id, fact_type);
CREATE VIRTUAL TABLE IF NOT EXISTS copilot_research_fts USING fts5(
    evidence_id UNINDEXED,
    seller_id UNINDEXED,
    listing_id UNINDEXED,
    fact_type UNINDEXED,
    search_text
);
CREATE TABLE IF NOT EXISTS copilot_trace_observations (
    observation_number INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_id TEXT NOT NULL UNIQUE,
    trace_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    stage_number INTEGER NOT NULL CHECK (stage_number BETWEEN 1 AND 8),
    component_id TEXT NOT NULL,
    status TEXT NOT NULL,
    seller_id TEXT,
    show_id TEXT,
    event_id TEXT,
    question_id TEXT,
    analysis_call_id TEXT,
    agent_run_id TEXT,
    profile_digest TEXT,
    snapshot_id TEXT,
    workflow_id TEXT,
    model_profile_id TEXT,
    selection_version INTEGER,
    sample_phase TEXT,
    occurred_at TEXT NOT NULL,
    duration_ms REAL,
    input_ref TEXT,
    output_ref TEXT,
    verdict TEXT,
    reason_code TEXT
);
CREATE INDEX IF NOT EXISTS copilot_trace_by_trace
    ON copilot_trace_observations(trace_id, observation_number);
CREATE TABLE IF NOT EXISTS copilot_trace_artifacts (
    artifact_number INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_id TEXT NOT NULL UNIQUE,
    trace_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS copilot_artifacts_by_trace
    ON copilot_trace_artifacts(trace_id, artifact_number);
CREATE TABLE IF NOT EXISTS copilot_trace_oracle_labels (
    event_id TEXT PRIMARY KEY REFERENCES chat_events(event_id),
    run_id TEXT NOT NULL,
    expected_bucket TEXT NOT NULL,
    expected_route TEXT NOT NULL,
    canonical_event_id TEXT
);
CREATE TABLE IF NOT EXISTS copilot_suggestions (
    suggestion_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL UNIQUE REFERENCES copilot_questions(question_id),
    seller_id TEXT NOT NULL REFERENCES sellers(seller_id),
    show_id TEXT NOT NULL REFERENCES shows(show_id),
    listing_id TEXT NOT NULL REFERENCES listings(listing_id),
    epoch_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    reply_text TEXT NOT NULL,
    answer_category TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    evidence_snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS copilot_r3_capabilities (
    show_id TEXT PRIMARY KEY REFERENCES shows(show_id),
    seller_id TEXT NOT NULL REFERENCES sellers(seller_id),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS copilot_outbound_replies (
    reply_number INTEGER PRIMARY KEY AUTOINCREMENT,
    reply_id TEXT NOT NULL UNIQUE,
    question_id TEXT NOT NULL REFERENCES copilot_questions(question_id),
    canonical_question_id TEXT NOT NULL UNIQUE REFERENCES copilot_questions(question_id),
    seller_id TEXT NOT NULL REFERENCES sellers(seller_id),
    show_id TEXT NOT NULL REFERENCES shows(show_id),
    actor_id TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('r2', 'r3')),
    reply_text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS copilot_reply_receipts (
    receipt_number INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id TEXT NOT NULL UNIQUE,
    reply_id TEXT NOT NULL UNIQUE REFERENCES copilot_outbound_replies(reply_id),
    question_id TEXT NOT NULL REFERENCES copilot_questions(question_id),
    canonical_question_id TEXT NOT NULL,
    seller_id TEXT NOT NULL,
    show_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('r2', 'r3')),
    reply_text TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    broker_outcome TEXT NOT NULL,
    guardrail_verdict TEXT NOT NULL,
    authorization_version INTEGER,
    validated_versions_json TEXT NOT NULL DEFAULT '{}',
    workflow_id TEXT,
    model_profile_id TEXT,
    requested_model_id TEXT,
    model_config_ref TEXT,
    model_provider TEXT,
    selection_version INTEGER,
    sample_phase TEXT,
    resolved_model_id TEXT,
    resolved_provider TEXT,
    warnings_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS copilot_reply_idempotency (
    seller_id TEXT NOT NULL,
    show_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    receipt_id TEXT NOT NULL REFERENCES copilot_reply_receipts(receipt_id),
    PRIMARY KEY (seller_id, show_id, idempotency_key)
);
"""


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.execute("DROP INDEX IF EXISTS one_canonical_question_per_scope")
    connection.execute(
        """CREATE INDEX IF NOT EXISTS canonical_question_dedup_lookup
           ON copilot_questions(
               seller_id, show_id, canonical_scope, canonical_key, asked_at
           ) WHERE canonical_question_id IS NULL AND route != 'noise'"""
    )
    connection.execute(
        """UPDATE copilot_r3_capabilities
           SET enabled = 1, version = version + 1
           WHERE enabled = 0 AND updated_by = 'system_default'"""
    )
    _ensure_column(
        connection,
        "copilot_reply_receipts",
        "authorization_version",
        "INTEGER",
    )
    _ensure_column(
        connection,
        "copilot_reply_receipts",
        "validated_versions_json",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    runtime_columns = {
        "chat_events": (
            ("workflow_id", "TEXT"),
            ("model_profile_id", "TEXT"),
            ("requested_model_id", "TEXT"),
            ("model_config_ref", "TEXT"),
            ("model_provider", "TEXT"),
            ("selection_version", "INTEGER"),
            ("selection_selected_at", "TEXT"),
        ),
        "copilot_questions": (
            ("workflow_id", "TEXT"),
            ("model_profile_id", "TEXT"),
            ("requested_model_id", "TEXT"),
            ("model_config_ref", "TEXT"),
            ("model_provider", "TEXT"),
            ("selection_version", "INTEGER"),
            ("selection_selected_at", "TEXT"),
            ("sample_phase", "TEXT"),
            ("resolved_model_id", "TEXT"),
            ("resolved_provider", "TEXT"),
        ),
        "copilot_trace_observations": (
            ("workflow_id", "TEXT"),
            ("model_profile_id", "TEXT"),
            ("selection_version", "INTEGER"),
            ("sample_phase", "TEXT"),
        ),
        "copilot_reply_receipts": (
            ("workflow_id", "TEXT"),
            ("model_profile_id", "TEXT"),
            ("requested_model_id", "TEXT"),
            ("model_config_ref", "TEXT"),
            ("model_provider", "TEXT"),
            ("selection_version", "INTEGER"),
            ("sample_phase", "TEXT"),
            ("resolved_model_id", "TEXT"),
            ("resolved_provider", "TEXT"),
        ),
    }
    for table, columns in runtime_columns.items():
        for column, definition in columns:
            _ensure_column(connection, table, column, definition)


def seed_catalog(connection: sqlite3.Connection, catalog: SellerCatalog) -> None:
    """Seed immutable fixture facts once; runtime versions start at one."""

    existing = connection.execute("SELECT COUNT(*) FROM sellers").fetchone()[0]
    if existing:
        for seller in catalog.document.sellers:
            show_id = f"show_{seller.seller_id.removeprefix('sel_')}"
            connection.execute(
                """INSERT OR IGNORE INTO copilot_r3_capabilities(
                       show_id, seller_id, enabled, version, updated_by, updated_at
                   ) VALUES (?, ?, 1, 1, 'system_default', '1970-01-01T00:00:00.000Z')""",
                (show_id, seller.seller_id),
            )
        return

    for seller in catalog.document.sellers:
        connection.execute(
            "INSERT INTO sellers(seller_id, display_name) VALUES (?, ?)",
            (seller.seller_id, seller.display_name),
        )
        show_id = f"show_{seller.seller_id.removeprefix('sel_')}"
        connection.execute(
            """INSERT INTO shows(
                   show_id, seller_id, active_listing_id, version, show_seq
               ) VALUES (?, ?, NULL, 1, 0)""",
            (show_id, seller.seller_id),
        )
        connection.execute(
            """INSERT INTO copilot_r3_capabilities(
                   show_id, seller_id, enabled, version, updated_by, updated_at
               ) VALUES (?, ?, 1, 1, 'system_default', '1970-01-01T00:00:00.000Z')""",
            (show_id, seller.seller_id),
        )
        for product in seller.products:
            listing = product.listing
            connection.execute(
                """INSERT INTO listings(
                       listing_id, seller_id, price_cents, floor_price_cents, status, version
                   ) VALUES (?, ?, ?, ?, ?, 1)""",
                (
                    listing.listing_id,
                    seller.seller_id,
                    listing.price_cents,
                    listing.floor_price_cents,
                    listing.status,
                ),
            )
            for variant in product.variants:
                connection.execute(
                    """INSERT INTO inventory(
                           variant_id, listing_id, seller_id, available_quantity, version
                       ) VALUES (?, ?, ?, ?, 1)""",
                    (
                        variant.variant_id,
                        listing.listing_id,
                        seller.seller_id,
                        variant.available_quantity,
                    ),
                )


def seed_copilot_evidence(
    connection: sqlite3.Connection,
    catalog: SellerCatalog,
    *,
    imported_at: str,
) -> None:
    """Project static synthetic facts into stable, source-backed evidence rows."""

    research_fields = (
        ("release_date", "release_date"),
        ("msrp", "msrp_cents"),
        ("materials", "materials"),
        ("sizing", "sizing"),
        ("authenticity", "authenticity_status"),
        ("condition", "condition"),
    )
    policy_fields = (
        ("shipping_policy", "shipping"),
        ("payment_policy", "payment"),
        ("returns_policy", "returns"),
    )
    for seller_index, seller in enumerate(catalog.document.sellers):
        for product_index, product in enumerate(seller.products):
            listing_id = product.listing.listing_id
            base_pointer = f"/sellers/{seller_index}/products/{product_index}"
            identity_value = (
                f"{product.brand} {product.model_name} {product.colorway}; "
                f"SKU {product.sku}; listing {product.listing.title}"
            )
            _insert_evidence(
                connection,
                evidence_id=_evidence_id(seller.seller_id, listing_id, "listing_identity"),
                seller_id=seller.seller_id,
                listing_id=listing_id,
                fact_type="listing_identity",
                value=identity_value,
                source="product_catalog",
                source_ref=f"{base_pointer}/listing/title",
                source_version=1,
                observed_at=imported_at,
                search_text=None,
            )
            for fact_type, field_name in research_fields:
                raw_value = getattr(product.facts, field_name)
                value = str(raw_value)
                if field_name == "msrp_cents":
                    value = f"USD {int(raw_value) / 100:.2f}"
                search_text = " ".join(
                    (
                        product.sku,
                        product.brand,
                        product.model_name,
                        product.colorway,
                        product.listing.title,
                        fact_type.replace("_", " "),
                        value,
                    )
                )
                _insert_evidence(
                    connection,
                    evidence_id=_evidence_id(seller.seller_id, listing_id, fact_type),
                    seller_id=seller.seller_id,
                    listing_id=listing_id,
                    fact_type=fact_type,
                    value=value,
                    source="product_research",
                    source_ref=f"{base_pointer}/facts/{field_name}",
                    source_version=1,
                    observed_at=imported_at,
                    search_text=search_text,
                )
            for fact_type, field_name in policy_fields:
                value = str(getattr(seller.policies, field_name))
                _insert_evidence(
                    connection,
                    evidence_id=_evidence_id(seller.seller_id, listing_id, fact_type),
                    seller_id=seller.seller_id,
                    listing_id=listing_id,
                    fact_type=fact_type,
                    value=value,
                    source="seller_policy",
                    source_ref=f"/sellers/{seller_index}/policies/{field_name}",
                    source_version=1,
                    observed_at=imported_at,
                    search_text=None,
                )


def _evidence_id(seller_id: str, listing_id: str, fact_identity: str) -> str:
    digest = sha256(f"{seller_id}:{listing_id}:{fact_identity}".encode("utf-8")).hexdigest()
    return f"evd_{digest[:24]}"


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _insert_evidence(
    connection: sqlite3.Connection,
    *,
    evidence_id: str,
    seller_id: str,
    listing_id: str,
    fact_type: str,
    value: str,
    source: str,
    source_ref: str,
    source_version: int,
    observed_at: str,
    search_text: str | None,
) -> None:
    cursor = connection.execute(
        """INSERT OR IGNORE INTO copilot_evidence_records(
               evidence_id, seller_id, listing_id, fact_type, value,
               source, source_ref, source_version, observed_at, provenance
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'synthetic_seller_data')""",
        (
            evidence_id,
            seller_id,
            listing_id,
            fact_type,
            value,
            source,
            source_ref,
            source_version,
            observed_at,
        ),
    )
    if cursor.rowcount and search_text is not None:
        connection.execute(
            """INSERT INTO copilot_research_fts(
                   evidence_id, seller_id, listing_id, fact_type, search_text
               ) VALUES (?, ?, ?, ?, ?)""",
            (evidence_id, seller_id, listing_id, fact_type, search_text),
        )
