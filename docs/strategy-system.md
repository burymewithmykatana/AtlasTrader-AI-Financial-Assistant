# Strategy system

A strategy is an exchange-independent protocol with a stable name/version, required
history, and `evaluate(candles) -> Signal`. It sees immutable normalized candles only and
has no client, database, portfolio, or execution access. A persisted signal is unique by
strategy name/version, exchange, symbol, timeframe, and candle open time.

Phase 1 implements `ema_atr` version 1. Defaults are fast EMA 12, slow EMA 26, Wilder ATR
14, and a 2x ATR diagnostic stop. EMA seeds with the simple mean and ATR seeds with the
mean true range. All calculations use `Decimal`; no numerical library or float conversion
is involved. A BUY/SELL occurs only on a confirmed EMA crossover; otherwise the action is
HOLD. The signal records current indicator values, score, reference price, and optional
ATR stop.

Backtest requests may provide `strategy_parameters` containing `fast_period`,
`slow_period`, `atr_period`, and `atr_stop_multiple` (the latter should be a decimal string).
Unknown or invalid parameters fail validation. Strategy tests prove deterministic output
and that modifying a later candle cannot change a signal calculated from an earlier slice.
