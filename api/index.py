"""Vercel ASGI entrypoint for the protected SideStage challenge preview."""

from __future__ import annotations

import os
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from sidestage.app import create_challenge_app  # noqa: E402


# Vercel Functions provide writable temporary storage, not a shared durable
# database. This preview path intentionally resets when its function instance
# is recycled; use a stateful ASGI deployment for the final reliable reviewer URL.
app = create_challenge_app(
    database_path=Path(
        os.environ.get("SIDESTAGE_DATABASE_PATH", "/tmp/sidestage.sqlite3")
    )
)
