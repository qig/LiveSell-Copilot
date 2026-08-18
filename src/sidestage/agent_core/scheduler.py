"""Bounded per-profile FIFO admission for the static agent core."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Iterable, Optional

from sidestage.agent_core.contracts import AgentProfile


ProfileIdentity = tuple[str, str]


class SchedulerQueueFullError(RuntimeError):
    """The immutable profile capacity has no active or waiting slot available."""


class SchedulerDeadlineError(RuntimeError):
    """A queued task reached its absolute deadline before provider dispatch."""

    def __init__(self, queued_at: float) -> None:
        super().__init__("queued task reached its hard deadline")
        self.queued_at = queued_at


class SchedulerCancelledError(RuntimeError):
    """A queued task was cancelled before provider dispatch."""

    def __init__(self, queued_at: float) -> None:
        super().__init__("queued task was cancelled")
        self.queued_at = queued_at


@dataclass
class _Ticket:
    lane: "_Lane"
    future: asyncio.Future[None]
    queued_at: float
    dispatched_at: Optional[float] = None
    released: bool = False


@dataclass
class _Lane:
    capacity: int
    max_concurrency: int
    active: int
    waiting: Deque[_Ticket]


class SchedulerLease:
    """One dispatched concurrency slot that must be released exactly once."""

    def __init__(self, scheduler: "BoundedFifoScheduler", ticket: _Ticket) -> None:
        if ticket.dispatched_at is None:
            raise RuntimeError("cannot lease an undispatched scheduler ticket")
        self._scheduler = scheduler
        self._ticket = ticket
        self.queued_at = ticket.queued_at
        self.dispatched_at = ticket.dispatched_at

    @property
    def queue_ms(self) -> float:
        return max(0.0, (self.dispatched_at - self.queued_at) * 1_000)

    def release(self) -> None:
        self._scheduler.release(self._ticket)


class BoundedFifoScheduler:
    """One immutable FIFO lane per registered profile identity."""

    def __init__(
        self,
        profiles: Iterable[AgentProfile],
        *,
        monotonic: Callable[[], float],
    ) -> None:
        self._monotonic = monotonic
        self._lanes = {
            (profile.adapter_id, profile.profile_version): _Lane(
                capacity=profile.queue_policy.capacity,
                max_concurrency=profile.queue_policy.max_concurrency,
                active=0,
                waiting=deque(),
            )
            for profile in profiles
        }

    async def acquire(
        self,
        identity: ProfileIdentity,
        *,
        deadline_monotonic_s: float,
        on_queued: Optional[Callable[[float], None]] = None,
    ) -> SchedulerLease:
        lane = self._lanes[identity]
        queued_at = self._monotonic()
        if deadline_monotonic_s <= queued_at:
            raise SchedulerDeadlineError(queued_at)
        if lane.active + len(lane.waiting) >= lane.capacity:
            raise SchedulerQueueFullError("agent profile queue is full")

        future = asyncio.get_running_loop().create_future()
        ticket = _Ticket(lane=lane, future=future, queued_at=queued_at)
        lane.waiting.append(ticket)
        if on_queued is not None:
            on_queued(queued_at)
        self._dispatch(lane)

        remaining_s = deadline_monotonic_s - self._monotonic()
        if remaining_s <= 0:
            self._cancel(ticket)
            raise SchedulerDeadlineError(queued_at)
        try:
            await asyncio.wait_for(asyncio.shield(future), timeout=remaining_s)
        except asyncio.TimeoutError as exc:
            self._cancel(ticket)
            raise SchedulerDeadlineError(queued_at) from exc
        except asyncio.CancelledError as exc:
            self._cancel(ticket)
            raise SchedulerCancelledError(queued_at) from exc
        return SchedulerLease(self, ticket)

    def release(self, ticket: _Ticket) -> None:
        if ticket.released:
            return
        ticket.released = True
        if ticket.dispatched_at is not None:
            ticket.lane.active -= 1
        else:
            self._remove_waiting(ticket)
        self._dispatch(ticket.lane)

    def _cancel(self, ticket: _Ticket) -> None:
        self.release(ticket)

    @staticmethod
    def _remove_waiting(ticket: _Ticket) -> None:
        try:
            ticket.lane.waiting.remove(ticket)
        except ValueError:
            return

    def _dispatch(self, lane: _Lane) -> None:
        while lane.active < lane.max_concurrency and lane.waiting:
            ticket = lane.waiting.popleft()
            if ticket.released:
                continue
            ticket.dispatched_at = self._monotonic()
            lane.active += 1
            if not ticket.future.done():
                ticket.future.set_result(None)
