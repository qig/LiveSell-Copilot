"""Repository-local configuration used by the synthetic prototype."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SELLERS_FIXTURE = REPOSITORY_ROOT / "fixtures" / "sellers.json"
DEFAULT_CHAT_FIXTURE = REPOSITORY_ROOT / "fixtures" / "chat_messages.json"
DEFAULT_RUNTIME_DATABASE = REPOSITORY_ROOT / "var" / "sidestage.sqlite3"


@dataclass(frozen=True)
class RuntimeConfig:
    """Paths required by the M2 seller-data import boundary."""

    sellers_fixture: Path = DEFAULT_SELLERS_FIXTURE
