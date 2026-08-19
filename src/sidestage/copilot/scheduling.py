"""FIFO admission for the full eligible livesell reply path."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Optional

from sidestage.copilot.profile import (
    GLOBAL_CONCURRENCY,
    PER_SHOW_CAPACITY,
    PER_SHOW_CONCURRENCY,
)


class WorkQueueFullError(RuntimeError):
    pass


class WorkQueueDeadlineError(RuntimeError):
    def __init__(self, queued_at: float) -> None:
        super().__init__("eligible reply work exceeded its queue deadline")
        self.queued_at = queued_at


@dataclass
class WorkTicket:
    show_id: str
    future: asyncio.Future
    queued_at: float
    depth_at_enqueue: int
    dispatched_at: Optional[float] = None
    released: bool = False

    @property
    def queue_ms(self) -> float:
        dispatched = self.dispatched_at if self.dispatched_at is not None else self.queued_at
        return max(0.0, (dispatched - self.queued_at) * 1_000)


class LivesellWorkScheduler:
    """Admit at most 64 candidates/show, five/show, and fifteen globally."""

    def __init__(self, *, monotonic: Callable[[], float]) -> None:
        self.monotonic = monotonic
        self.waiting: Deque[WorkTicket] = deque()
        self.show_total: Dict[str, int] = defaultdict(int)
        self.show_active: Dict[str, int] = defaultdict(int)
        self.global_active = 0
        self.max_global_active = 0
        self.max_show_active: Dict[str, int] = defaultdict(int)
        self.accepted_count = 0
        self.capacity_rejection_count = 0
        self.queue_timeout_count = 0

    async def acquire(self, show_id: str, *, deadline: float) -> WorkTicket:
        queued_at = self.monotonic()
        if deadline <= queued_at:
            self.queue_timeout_count += 1
            raise WorkQueueDeadlineError(queued_at)
        if self.show_total[show_id] >= PER_SHOW_CAPACITY:
            self.capacity_rejection_count += 1
            raise WorkQueueFullError("per-show eligible reply queue is full")
        ticket = WorkTicket(
            show_id=show_id,
            future=asyncio.get_running_loop().create_future(),
            queued_at=queued_at,
            depth_at_enqueue=self.show_total[show_id] + 1,
        )
        self.accepted_count += 1
        self.show_total[show_id] += 1
        self.waiting.append(ticket)
        self._dispatch()
        remaining = deadline - self.monotonic()
        if remaining <= 0:
            self.release(ticket)
            self.queue_timeout_count += 1
            raise WorkQueueDeadlineError(queued_at)
        try:
            await asyncio.wait_for(asyncio.shield(ticket.future), timeout=remaining)
        except asyncio.TimeoutError as error:
            self.release(ticket)
            self.queue_timeout_count += 1
            raise WorkQueueDeadlineError(queued_at) from error
        except asyncio.CancelledError:
            self.release(ticket)
            raise
        return ticket

    def release(self, ticket: WorkTicket) -> None:
        if ticket.released:
            return
        ticket.released = True
        if ticket.dispatched_at is None:
            try:
                self.waiting.remove(ticket)
            except ValueError:
                pass
        else:
            self.show_active[ticket.show_id] -= 1
            self.global_active -= 1
        self.show_total[ticket.show_id] -= 1
        self._dispatch()

    def snapshot(self) -> dict:
        return {
            "per_show_capacity": PER_SHOW_CAPACITY,
            "per_show_concurrency": PER_SHOW_CONCURRENCY,
            "global_concurrency": GLOBAL_CONCURRENCY,
            "active_global": self.global_active,
            "waiting_global": len(self.waiting),
            "max_global_active": self.max_global_active,
            "max_show_active": dict(self.max_show_active),
            "accepted_count": self.accepted_count,
            "capacity_rejection_count": self.capacity_rejection_count,
            "queue_timeout_count": self.queue_timeout_count,
        }

    def _dispatch(self) -> None:
        while self.global_active < GLOBAL_CONCURRENCY:
            eligible = next(
                (
                    ticket
                    for ticket in self.waiting
                    if not ticket.released
                    and self.show_active[ticket.show_id] < PER_SHOW_CONCURRENCY
                ),
                None,
            )
            if eligible is None:
                return
            self.waiting.remove(eligible)
            eligible.dispatched_at = self.monotonic()
            self.show_active[eligible.show_id] += 1
            self.global_active += 1
            self.max_global_active = max(self.max_global_active, self.global_active)
            self.max_show_active[eligible.show_id] = max(
                self.max_show_active[eligible.show_id],
                self.show_active[eligible.show_id],
            )
            if not eligible.future.done():
                eligible.future.set_result(None)
