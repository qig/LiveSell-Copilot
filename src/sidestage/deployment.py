"""Challenge-only access protection and conservative model-usage admission."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import os
import secrets
from typing import Awaitable, Callable, Optional

from starlette.responses import PlainTextResponse

from sidestage.storage.database import MarketplaceDatabase


AsgiApp = Callable[
    [dict, Callable[[], Awaitable[dict]], Callable[[dict], Awaitable[None]]],
    Awaitable[None],
]


@dataclass(frozen=True)
class ChallengeDeploymentConfig:
    """Server-only settings required by the reviewer-facing challenge factory."""

    username: str
    password: str
    max_requests_per_session: int = 20
    max_requests_per_day: int = 100
    realm: str = "SideStage challenge"

    @classmethod
    def from_environment(cls) -> "ChallengeDeploymentConfig":
        username = _required_environment("SIDESTAGE_DEMO_USERNAME")
        password = _required_environment("SIDESTAGE_DEMO_PASSWORD")
        if ":" in username:
            raise RuntimeError("SIDESTAGE_DEMO_USERNAME cannot contain ':'")
        return cls(
            username=username,
            password=password,
            max_requests_per_session=_nonnegative_environment_integer(
                "SIDESTAGE_DEMO_MAX_REQUESTS_PER_SESSION", 20
            ),
            max_requests_per_day=_nonnegative_environment_integer(
                "SIDESTAGE_DEMO_MAX_REQUESTS_PER_DAY", 100
            ),
        )


class ChallengeAccessMiddleware:
    """Protect the complete ASGI surface without buffering streaming responses."""

    def __init__(
        self,
        app: AsgiApp,
        *,
        username: str,
        password: str,
        realm: str,
        unprotected_paths: tuple[str, ...] = ("/healthz",),
    ) -> None:
        self.app = app
        self.username = username
        self.password = password
        self.realm = realm
        self.unprotected_paths = frozenset(unprotected_paths)

    async def __call__(self, scope: dict, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("path") not in self.unprotected_paths and not self._authorized(scope):
            response = PlainTextResponse(
                "Authentication required",
                status_code=401,
                headers={"WWW-Authenticate": f'Basic realm="{self.realm}"'},
            )
            await response(scope, receive, self._secure_send(send))
            return
        await self.app(scope, receive, self._secure_send(send))

    def _authorized(self, scope: dict) -> bool:
        value: Optional[bytes] = None
        for name, header_value in scope.get("headers", ()):
            if name.lower() == b"authorization":
                value = header_value
                break
        if value is None or not value.startswith(b"Basic "):
            return False
        try:
            decoded = base64.b64decode(value[6:], validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return False
        supplied_username, separator, supplied_password = decoded.partition(":")
        if not separator:
            return False
        username_matches = secrets.compare_digest(supplied_username, self.username)
        password_matches = secrets.compare_digest(supplied_password, self.password)
        return username_matches and password_matches

    @staticmethod
    def _secure_send(send):
        async def secured(message: dict) -> None:
            if message.get("type") == "http.response.start":
                excluded = {
                    b"cache-control",
                    b"permissions-policy",
                    b"referrer-policy",
                    b"x-content-type-options",
                    b"x-frame-options",
                }
                headers = [
                    (name, value)
                    for name, value in message.get("headers", ())
                    if name.lower() not in excluded
                ]
                headers.extend(
                    (
                        (b"cache-control", b"no-store"),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                    )
                )
                message = {**message, "headers": headers}
            await send(message)

        return secured


@dataclass(frozen=True)
class ChallengeUsageReservation:
    session_remaining: int
    global_remaining: int


class ChallengeUsageLimitError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ChallengeUsageLimiter:
    """Atomically reserve conservative chat units in the authoritative SQLite store."""

    def __init__(
        self,
        database: MarketplaceDatabase,
        *,
        max_requests_per_session: int,
        max_requests_per_day: int,
    ) -> None:
        if max_requests_per_session < 0 or max_requests_per_day < 0:
            raise ValueError("challenge usage limits must be nonnegative")
        self.database = database
        self.max_requests_per_session = max_requests_per_session
        self.max_requests_per_day = max_requests_per_day

    def reserve(
        self,
        session_token: str,
        *,
        units: int,
        now: Optional[datetime] = None,
    ) -> ChallengeUsageReservation:
        if units <= 0:
            raise ValueError("challenge usage reservation must be positive")
        timestamp = now or datetime.now(timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("challenge usage timestamp must be timezone-aware")
        timestamp = timestamp.astimezone(timezone.utc)
        usage_day = timestamp.date().isoformat()
        token_digest = sha256(session_token.encode("utf-8")).hexdigest()
        accepted_at = timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self.database.transaction() as connection:
            global_used = int(
                connection.execute(
                    "SELECT COALESCE(SUM(units), 0) FROM challenge_usage WHERE usage_day = ?",
                    (usage_day,),
                ).fetchone()[0]
            )
            session_used = int(
                connection.execute(
                    """SELECT COALESCE(SUM(units), 0)
                       FROM challenge_usage
                       WHERE usage_day = ? AND session_token_digest = ?""",
                    (usage_day, token_digest),
                ).fetchone()[0]
            )
            if global_used + units > self.max_requests_per_day:
                raise ChallengeUsageLimitError("global_limit_reached")
            if session_used + units > self.max_requests_per_session:
                raise ChallengeUsageLimitError("session_limit_reached")
            connection.execute(
                """INSERT INTO challenge_usage(
                       usage_day, session_token_digest, units, accepted_at
                   ) VALUES (?, ?, ?, ?)""",
                (usage_day, token_digest, units, accepted_at),
            )
        return ChallengeUsageReservation(
            session_remaining=self.max_requests_per_session - session_used - units,
            global_remaining=self.max_requests_per_day - global_used - units,
        )


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value:
        raise RuntimeError(f"challenge deployment requires {name}")
    return value


def _nonnegative_environment_integer(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a nonnegative integer") from error
    if value < 0:
        raise RuntimeError(f"{name} must be a nonnegative integer")
    return value
