from decimal import Decimal

import httpx
import pytest

from atlas_trader.domain.exceptions import ExchangeOrderRejectedError
from atlas_trader.infrastructure.exchanges.nobitex.adapter import NobitexPublicAdapter
from atlas_trader.infrastructure.exchanges.nobitex.client import (
    NobitexPublicClient,
    RetryPolicy,
)
from atlas_trader.infrastructure.exchanges.nobitex.errors import (
    NobitexRequestError,
    NobitexResponseError,
)


@pytest.mark.asyncio
async def test_public_client_sends_no_credentials_and_preserves_json_decimal() -> None:
    seen_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, text='{"status":"ok","value":0.1}')

    async with NobitexPublicClient(transport=httpx.MockTransport(handler)) as client:
        payload = await client.get_options(correlation_id="cycle-1")

    assert payload["value"] == Decimal("0.1")
    assert seen_request is not None
    assert "authorization" not in seen_request.headers
    assert "cookie" not in seen_request.headers
    assert seen_request.headers["x-correlation-id"] == "cycle-1"
    assert seen_request.headers["user-agent"].startswith("AtlasTrader/")


@pytest.mark.asyncio
async def test_retry_policy_is_bounded_and_honors_retry_after() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={"status": "failed"})
        return httpx.Response(200, json={"status": "ok"})

    async def sleeper(delay: float) -> None:
        delays.append(delay)

    async with NobitexPublicClient(
        transport=httpx.MockTransport(handler),
        retry_policy=RetryPolicy(max_attempts=2, max_delay_seconds=5),
        sleeper=sleeper,
    ) as client:
        payload = await client.get_options(correlation_id="cycle-2")

    assert payload == {"status": "ok"}
    assert attempts == 2
    assert delays == [2.0]


@pytest.mark.asyncio
async def test_client_does_not_retry_ordinary_4xx() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, json={"status": "failed"})

    async with NobitexPublicClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NobitexRequestError, match="HTTP 404"):
            await client.get_orderbook("INVALID", correlation_id="cycle-3")

    assert attempts == 1


@pytest.mark.asyncio
async def test_invalid_json_has_explicit_exception_mapping() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, text="not-json"))

    async with NobitexPublicClient(transport=transport) as client:
        with pytest.raises(NobitexResponseError, match="invalid JSON"):
            await client.get_options(correlation_id="cycle-4")


def test_retry_delay_is_deterministic_when_random_source_is_injected() -> None:
    policy = RetryPolicy(base_delay_seconds=0.5, jitter_ratio=0.2)

    assert policy.delay(3, 0.0) == 2.0
    assert policy.delay(3, 1.0) == 2.4


@pytest.mark.asyncio
async def test_public_adapter_fails_closed_for_authenticated_operations() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(500))

    async with NobitexPublicClient(transport=transport) as client:
        adapter = NobitexPublicAdapter(client)
        with pytest.raises(ExchangeOrderRejectedError, match="no authenticated"):
            await adapter.get_balances()
