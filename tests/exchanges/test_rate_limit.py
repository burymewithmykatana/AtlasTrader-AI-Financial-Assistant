import pytest

from atlas_trader.infrastructure.exchanges.nobitex.rate_limit import (
    InMemoryRateLimiter,
    PublicEndpoint,
    RateLimit,
)


@pytest.mark.asyncio
async def test_rate_limiter_waits_at_endpoint_boundary() -> None:
    now = 0.0
    waits: list[float] = []

    def clock() -> float:
        return now

    async def sleeper(delay: float) -> None:
        nonlocal now
        waits.append(delay)
        now += delay

    limiter = InMemoryRateLimiter(
        {PublicEndpoint.OHLC: RateLimit(requests=2, period_seconds=10)},
        clock=clock,
        sleeper=sleeper,
    )

    await limiter.acquire(PublicEndpoint.OHLC)
    await limiter.acquire(PublicEndpoint.OHLC)
    await limiter.acquire(PublicEndpoint.OHLC)

    assert waits == [10.0]
