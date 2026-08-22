"""Injectable in-process asynchronous rate limiting."""

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class PublicEndpoint(StrEnum):
    OPTIONS = "options"
    ORDERBOOK = "orderbook"
    TRADES = "trades"
    OHLC = "ohlc"


@dataclass(frozen=True, slots=True)
class RateLimit:
    requests: int
    period_seconds: float = 60.0


DEFAULT_PUBLIC_LIMITS = {
    PublicEndpoint.OPTIONS: RateLimit(60),
    PublicEndpoint.ORDERBOOK: RateLimit(300),
    PublicEndpoint.TRADES: RateLimit(60),
    PublicEndpoint.OHLC: RateLimit(60),
}


class AsyncRateLimiter(Protocol):
    async def acquire(self, endpoint: PublicEndpoint) -> None: ...


class InMemoryRateLimiter:
    def __init__(
        self,
        limits: dict[PublicEndpoint, RateLimit] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._limits = limits or DEFAULT_PUBLIC_LIMITS
        self._clock = clock
        self._sleeper = sleeper
        self._events: dict[PublicEndpoint, deque[float]] = defaultdict(deque)
        self._locks: dict[PublicEndpoint, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def acquire(self, endpoint: PublicEndpoint) -> None:
        limit = self._limits[endpoint]
        async with self._locks[endpoint]:
            events = self._events[endpoint]
            while True:
                now = self._clock()
                cutoff = now - limit.period_seconds
                while events and events[0] <= cutoff:
                    events.popleft()
                if len(events) < limit.requests:
                    events.append(now)
                    return
                await self._sleeper(max(0.0, events[0] + limit.period_seconds - now))
