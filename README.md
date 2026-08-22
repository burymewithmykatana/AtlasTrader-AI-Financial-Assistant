# AtlasTrader

AtlasTrader is a safety-first, exchange-agnostic trading research platform. Phase 1 adds
credential-free Nobitex public market data and deterministic backtesting on top of the
audited Phase 0 foundation.

> **PHASE 1 HAS NO REAL TRADING CAPABILITY.** It cannot authenticate to Nobitex, read a
> wallet, or place/cancel an order. No API token is required or sent.

## Current scope

- Python 3.12 package with FastAPI and Pydantic v2
- immutable domain models using `Decimal` for all financial quantities
- async `ExchangeAdapter` protocol and deterministic `MockExchangeAdapter`
- safe execution-mode configuration (`BACKTEST`, `PAPER`, `TESTNET`, `LIVE`)
- two-key live-trading interlock; live mode is disabled by default
- PostgreSQL 16, SQLAlchemy 2 async sessions, and Alembic
- JSON structured logging with correlation IDs and secret redaction
- dynamic public Nobitex market discovery and idempotent OHLCV synchronization
- Decimal-only EMA/ATR signals and next-candle-open backtests
- `GET /health`, `/markets`, `/market-data/candles`, and `/backtests`
- `POST /market-data/sync` and `/backtests`
- unit and integration tests
- strict static type checking and migration validation in CI

Nobitex authentication, paper/actual execution, wallet access, withdrawals, transfers,
margin, and Telegram trading commands are not implemented. Never commit a populated
`.env` file.

## Prerequisites

- Python 3.12+
- Docker Desktop with Docker Compose (for the container workflow)

## Local setup

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Review `.env` before starting. The defaults use paper mode. A local Python process talks
to PostgreSQL on `localhost`; the Compose application overrides that host to `postgres`.

Start only PostgreSQL and run the API locally:

```bash
docker compose up -d postgres
alembic upgrade head
uvicorn atlas_trader.main:app --reload
```

Or run the entire stack:

```bash
docker compose up --build
```

Then open `http://localhost:8000/health` or `http://localhost:8000/docs`.

## Phase 1 workflow

Discover current markets (no symbols are hard-coded):

```bash
atlas-trader markets-sync
```

Synchronize candles and run the default EMA(12/26) + ATR(14) strategy backtest:

```bash
atlas-trader candles-sync --symbol BTCUSDT --timeframe 15m \
  --start 2026-01-01T00:00:00Z --end 2026-01-08T00:00:00Z
atlas-trader backtest --symbol BTCUSDT --timeframe 15m \
  --start 2026-01-01T00:00:00Z --end 2026-01-08T00:00:00Z
```

The symbol above is only an example; select a value returned by `GET /markets`. Supported
domain timeframes are `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, and `1d`. See
[market data](docs/market-data.md), [backtesting](docs/backtesting.md), and the
[strategy system](docs/strategy-system.md).

## Quality checks

```bash
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy
alembic check
```

The tests do not require an exchange or a running PostgreSQL instance. Alembic migration
execution does require PostgreSQL.

## Safety controls

`LIVE` is valid only when both settings are explicit:

```dotenv
TRADING_MODE=live
LIVE_TRADING_ENABLED=true
```

Either setting alone is rejected during startup. This configuration guard is only one
layer; later phases will add centralized risk, persistent order intents, reconciliation,
and the global kill switch before any production adapter can be enabled.

## Project layout

```text
alembic/                         database migrations
docs/architecture.md             boundaries and design decisions
src/atlas_trader/
  api/                           HTTP delivery adapter
  application/                   market sync, signal, and backtest use cases
  config/                        typed environment settings
  domain/                        exchange-independent models and ports
  infrastructure/
    database/                    SQLAlchemy adapter
    exchanges/mock/              deterministic test adapter
    exchanges/nobitex/           public-only client, DTOs, mapper, limiter
tests/                           unit, exchange, and API integration tests
```

See [architecture](docs/architecture.md) and the [public API contract](docs/nobitex-api.md).

## Common commands

On systems with `make`: `make install`, `make test`, `make lint`, `make run`, `make up`,
and `make down`. The underlying commands shown above work directly on Windows.
