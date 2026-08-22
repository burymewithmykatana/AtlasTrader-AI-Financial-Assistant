"""Credential-free async HTTP transport for Nobitex public endpoints."""

import asyncio
import json
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
import structlog

from atlas_trader.infrastructure.exchanges.nobitex.errors import (
    NobitexRateLimitError,
    NobitexRequestError,
    NobitexResponseError,
    NobitexTransportError,
)
from atlas_trader.infrastructure.exchanges.nobitex.rate_limit import (
    AsyncRateLimiter,
    InMemoryRateLimiter,
    PublicEndpoint,
)

JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 15.0
    jitter_ratio: float = 0.20
    retry_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504})

    def delay(self, attempt: int, random_value: float) -> float:
        base: float = min(
            self.max_delay_seconds,
            self.base_delay_seconds * float(2 ** (attempt - 1)),
        )
        jitter = base * self.jitter_ratio * random_value
        return float(min(self.max_delay_seconds, base + jitter))


class NobitexPublicClient:
    """Public-only transport that never configures authentication or cookies."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.nobitex.ir",
        timeout_seconds: float = 15.0,
        user_agent: str = "AtlasTrader/0.1.0",
        retry_policy: RetryPolicy | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self._retry = retry_policy or RetryPolicy()
        self._limiter = rate_limiter or InMemoryRateLimiter()
        self._sleeper = sleeper
        self._random = random_source
        self._logger = structlog.get_logger()
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Accept": "application/json", "User-Agent": user_agent},
            auth=None,
            cookies=None,
            follow_redirects=False,
            transport=transport,
            trust_env=False,
        )

    async def __aenter__(self) -> "NobitexPublicClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_options(self, *, correlation_id: str) -> JsonObject:
        return await self._get("/v2/options", PublicEndpoint.OPTIONS, correlation_id=correlation_id)

    async def get_all_orderbooks(self, *, correlation_id: str) -> JsonObject:
        return await self._get(
            "/v3/orderbook/all", PublicEndpoint.ORDERBOOK, correlation_id=correlation_id
        )

    async def get_orderbook(self, symbol: str, *, correlation_id: str) -> JsonObject:
        return await self._get(
            f"/v3/orderbook/{symbol}", PublicEndpoint.ORDERBOOK, correlation_id=correlation_id
        )

    async def get_trades(self, symbol: str, *, correlation_id: str) -> JsonObject:
        return await self._get(
            f"/v2/trades/{symbol}", PublicEndpoint.TRADES, correlation_id=correlation_id
        )

    async def get_udf_history(
        self,
        *,
        symbol: str,
        resolution: str,
        start_epoch: int,
        end_epoch: int,
        page: int,
        correlation_id: str,
    ) -> JsonObject:
        return await self._get(
            "/market/udf/history",
            PublicEndpoint.OHLC,
            params={
                "symbol": symbol,
                "resolution": resolution,
                "from": start_epoch,
                "to": end_epoch,
                "page": page,
            },
            correlation_id=correlation_id,
        )

    async def _get(
        self,
        path: str,
        endpoint: PublicEndpoint,
        *,
        correlation_id: str,
        params: Mapping[str, str | int] | None = None,
    ) -> JsonObject:
        for attempt in range(1, self._retry.max_attempts + 1):
            await self._limiter.acquire(endpoint)
            try:
                response = await self._client.get(
                    path,
                    params=params,
                    headers={"X-Correlation-ID": correlation_id},
                )
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if attempt == self._retry.max_attempts:
                    raise NobitexTransportError(
                        f"public request failed after {attempt} attempts"
                    ) from exc
                await self._wait_before_retry(attempt, None)
                continue

            if response.status_code in self._retry.retry_statuses:
                if attempt == self._retry.max_attempts:
                    error_type = (
                        NobitexRateLimitError
                        if response.status_code == 429
                        else NobitexTransportError
                    )
                    raise error_type(
                        f"public request failed with HTTP {response.status_code} "
                        f"after {attempt} attempts"
                    )
                await self._wait_before_retry(attempt, response.headers.get("Retry-After"))
                continue
            if 400 <= response.status_code < 500:
                raise NobitexRequestError(
                    f"public request rejected with HTTP {response.status_code}"
                )
            if response.status_code >= 500:
                raise NobitexTransportError(
                    f"public request failed with HTTP {response.status_code}"
                )

            payload = self._decode_json(response)
            self._logger.info(
                "nobitex_public_request_succeeded",
                event_type="exchange.public_request.succeeded",
                exchange="nobitex",
                endpoint=endpoint.value,
                correlation_id=correlation_id,
                status_code=response.status_code,
                attempt=attempt,
            )
            return payload
        raise AssertionError("bounded retry loop exited unexpectedly")

    async def _wait_before_retry(self, attempt: int, retry_after: str | None) -> None:
        delay = self._parse_retry_after(retry_after)
        if delay is None:
            delay = self._retry.delay(attempt, self._random())
        await self._sleeper(min(delay, self._retry.max_delay_seconds))

    @staticmethod
    def _decode_json(response: httpx.Response) -> JsonObject:
        try:
            payload = json.loads(response.text, parse_float=Decimal)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise NobitexResponseError("public endpoint returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise NobitexResponseError("public endpoint returned a non-object JSON value")
        return payload

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                return max(0.0, (parsed - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None
