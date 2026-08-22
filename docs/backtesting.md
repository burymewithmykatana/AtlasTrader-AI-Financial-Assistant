# Deterministic backtesting

The Phase 1 backtester is deliberately small: spot, long-only, all-in, single-market, no
leverage, shorting, margin, intrabar fills, or paper/live orders. It uses stored candles and
`Decimal` arithmetic.

`NEXT_CANDLE_OPEN` is the only execution model. A signal evaluated from candle N executes
no earlier than candle N+1 open. Buy slippage is `open * (1 + bps/10000)`; sell slippage is
`open * (1 - bps/10000)`. Fees apply independently to each fill notional. The engine gives
the strategy only `candles[:N+1]`, preventing future values from influencing a historical
decision.

Every result stores run ID/status, strategy name/version/parameters, market/timeframe and
period, initial capital, fee/slippage settings, execution assumptions, code SHA when
available, ordered trades, and metrics. Metrics include ending equity, absolute/percentage
return, entries/exits, completed trades, wins/losses/win rate, gross profit/loss, profit
factor, maximum drawdown amount/percentage, fees, unrealized PnL, buy-and-hold return, and
exposure. Sharpe is intentionally omitted because no return sampling/risk-free-rate
assumption is defined. Fill/accounting results are quantized at the documented 18-decimal
PostgreSQL boundary before they are returned, preventing silent persistence rounding.

Run through `POST /backtests` or:

```bash
atlas-trader backtest --symbol BTCUSDT --timeframe 15m \
  --start 2026-01-01T00:00:00Z --end 2026-01-08T00:00:00Z \
  --initial-capital 10000 --fee-rate 0.001 --slippage-bps 5
```

`GET /backtests/{id}` and `GET /backtests` return persisted runs. Identical data,
parameters, and engine version reproduce signals, fills, and metrics; run IDs and wall-clock
timestamps are intentionally unique audit metadata.
