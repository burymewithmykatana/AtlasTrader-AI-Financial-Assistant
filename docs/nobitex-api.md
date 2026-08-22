# Nobitex public API contract

AtlasTrader Phase 1 uses only unauthenticated endpoints at `https://api.nobitex.ir`.
The client configures no auth and no cookies. `NOBITEX_TOKEN` is neither required nor read
by this adapter.

| Endpoint | Use | Local limit | Pagination |
|---|---|---:|---|
| `GET /v2/options` | currencies, min orders, amount/price steps | 60/min conservative | none |
| `GET /v3/orderbook/all` | dynamic market universe | 300/min | none |
| `GET /v3/orderbook/{symbol}` | current order-book/ticker snapshot | 300/min | none |
| `GET /v2/trades/{symbol}` | up to 20 recent public trades | 60/min | `all` unsupported |
| `GET /market/udf/history` | TradingView UDF OHLCV | 60/min | `page`, 500 candles/page |

The infrastructure flow is strictly `JSON -> Nobitex DTO -> mapper -> domain model ->
application service`. Nobitex field names and UDF resolution values do not cross that edge.
Domain timeframes map to UDF as `1m=1`, `5m=5`, `15m=15`, `30m=30`, `1h=60`, `4h=240`,
and `1d=D`.

JSON numbers are decoded with `Decimal`; DTO validators also convert string amounts using
`Decimal(str(value))`. Financial values are never converted to float. Invalid response
shape/status, inconsistent UDF arrays, or an empty discovery universe aborts the operation.
An inconsistent market mapping aborts reconciliation so a partial vendor response cannot
incorrectly deactivate stored markets.

The pooled async client propagates `X-Correlation-ID`, uses configurable timeout and
User-Agent values, and maps request, response, rate-limit, and transport failures to stable
exceptions. It retries only connections, timeouts, HTTP 429, and selected 5xx responses.
Retries are bounded and use injectable exponential backoff/jitter; `Retry-After` is honored
within the configured maximum delay. Ordinary 4xx responses and invalid JSON are not
retried.

Contract source: the current official Nobitex API documentation. Static sanitized fixtures
make all normal tests network-independent; a live smoke check is optional.
