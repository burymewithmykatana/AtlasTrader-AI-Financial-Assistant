# AtlasTrader architecture

## Phase 1 boundary

AtlasTrader uses a hexagonal design so market/strategy policy remains independent from
exchange APIs, databases, HTTP frameworks, and workflow tools. Phase 1 implements public
market data and research while stopping before paper fills, wallet access, risk-driven
execution, or authenticated Nobitex calls.

> **PHASE 1 HAS NO REAL TRADING CAPABILITY.**

## Dependency rule

Dependencies point inward:

```text
HTTP / CLI / future scheduler
             |
             v
     application use cases
       |               |
       v               v
 domain models     domain ports
                       ^
                       |
 infrastructure adapters (PostgreSQL, Mock, Nobitex public API)
```

- **Domain** contains immutable financial models, enums, and protocols. It imports no
  FastAPI, SQLAlchemy, config, or vendor module.
- **Application** coordinates market discovery, candle synchronization, signal generation,
  and deterministic backtests through domain-facing protocols.
- **Infrastructure** owns Nobitex JSON DTOs/mapping, the async public client/rate limiter,
  and SQLAlchemy repositories.
- **API/CLI** validate delivery input and invoke use cases; they contain no strategy or
  portfolio calculations.

Strategies receive normalized candles and return signals. They never receive an exchange
client or repository. The mandatory later execution path remains:

```text
Market data -> Strategy -> Signal -> Risk engine -> Order intent
            -> Execution engine -> Exchange adapter -> Reconciliation
```

None of the path after `Signal` is implemented in Phase 1.

## Financial and time correctness

Prices, quantities, balances, OHLCV, fees, indicators, and PnL are `Decimal` in the domain.
Strict immutable models reject float input, including nested financial metadata. PostgreSQL
financial columns are fixed-point `NUMERIC`. Times are aware UTC `datetime` values at
boundaries and `TIMESTAMP WITH TIME ZONE` in storage.

## Exchange boundary

The Phase 1 Nobitex adapter implements only public market discovery, ticker/order books,
recent public trades, and OHLCV. The boundary is:

```text
Nobitex JSON -> Nobitex DTO -> mapper -> exchange-neutral domain model
```

Vendor field names and UDF resolution codes never enter the domain. The HTTP client is
constructed with `auth=None`, `cookies=None`, and proxy inheritance disabled. Authenticated
protocol methods fail closed. A malformed/partial discovery response aborts reconciliation
instead of risking false market deactivation.

## Persistence

SQLAlchemy uses an async `asyncpg` engine and transaction-scoped sessions. The schema has:

- `markets`, unique by `(exchange, symbol)` and retained when inactive
- `system_events`, an append-oriented audit stream
- `candles`, unique by `(exchange, symbol, timeframe, open_time)`
- `signals`, unique by strategy/version/market/timeframe/candle
- `backtest_runs` and ordered `backtest_trades`

Database uniqueness is the final idempotency/concurrency boundary. Order intents, exchange
fills, positions, portfolio snapshots, and persistent risk state remain future work.

## Backtest boundary

The first execution model is spot, long-only, single-market `NEXT_CANDLE_OPEN`. A signal
calculated after candle N closes is eligible only at candle N+1 open. Fees apply to each
fill and fixed-basis-point slippage is adverse by side. The engine passes only the available
historical prefix to a strategy and stores strategy parameters, execution assumptions,
metrics, and trades with each run.

## Configuration and secrets

Settings use `pydantic-settings`; secrets use `SecretStr` and logs recursively redact
credential-like fields. Paper mode remains the safe default and the Phase 0 two-key live
configuration interlock remains unchanged. The Nobitex public client does not consult the
token setting. A production execution adapter, operator authorization, risk engine,
reconciliation, and kill switch do not exist yet.

## Runtime and tests

Docker Compose runs PostgreSQL 16 and a non-root FastAPI container. PostgreSQL must become
healthy before the app runs migrations. Redis and n8n are not runtime dependencies.

The combined Phase 0/1 suite covers strict Decimal behavior, domain isolation, secret
redaction, offline Nobitex DTO/mapper fixtures, endpoint-specific rate limiting and retries,
dynamic market reconciliation, idempotent candle/signal writes, EMA/ATR determinism,
future-data isolation, next-candle execution, backtest accounting/metrics, and schema
constraints. CI never needs the live Nobitex API.

## Planned increments

1. **Phase 1 (current):** public Nobitex data, candle/signal persistence, EMA/ATR, and
   deterministic backtesting.
2. **Phase 2:** deterministic order intents, centralized risk, paper portfolio/execution,
   kill switch, reconciliation architecture, and HTTP-triggered workflow integration.
3. **Phase 3:** authenticated testnet orders, partial fills, and crash recovery.
4. **Phase 4:** production market-data shadow mode with paper execution.
5. **Phase 5:** deliberately limited live execution after operational gates and explicit
   operator arming.
