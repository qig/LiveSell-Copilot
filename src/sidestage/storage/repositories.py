"""Schema and fixture seeding for the local marketplace store."""

from __future__ import annotations

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
"""


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def seed_catalog(connection: sqlite3.Connection, catalog: SellerCatalog) -> None:
    """Seed immutable fixture facts once; runtime versions start at one."""

    existing = connection.execute("SELECT COUNT(*) FROM sellers").fetchone()[0]
    if existing:
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
