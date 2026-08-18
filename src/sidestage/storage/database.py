"""Connection and transaction boundary for the marketplace emulator."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Iterator

from sidestage.fixtures.loader import SellerCatalog
from sidestage.storage.repositories import (
    initialize_schema,
    seed_catalog,
    seed_copilot_evidence,
)


class MarketplaceDatabase:
    """A small SQLite store with one atomic boundary for each seller action."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(
        self,
        catalog: SellerCatalog,
        *,
        evidence_imported_at: str | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            initialize_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                seed_catalog(connection, catalog)
                seed_copilot_evidence(
                    connection,
                    catalog,
                    imported_at=evidence_imported_at or _utc_millis(),
                )
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self.connect() as connection:
            yield connection

    def journal_mode(self) -> str:
        with self.read() as connection:
            return str(connection.execute("PRAGMA journal_mode").fetchone()[0])


def _utc_millis() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
