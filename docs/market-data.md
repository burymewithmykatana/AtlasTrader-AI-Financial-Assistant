# Market data

`MarketDiscoveryService` fetches options and all order books, derives the current universe,
maps precision/minimum-order metadata, and reconciles `(exchange, symbol)` records. Missing
markets are marked inactive; records are never deleted. Asset classification comes from
`ASSET_CLASSIFICATIONS`. Unknown assets remain valid as `unknown`, so a newly listed or
gold-backed asset needs only configuration—not adapter code.

`CandleSyncService` accepts exchange, exchange-native symbol, domain timeframe, and aware
start/end timestamps. It follows the Nobitex 500-row pages with a deterministic safety
bound, rejects out-of-range/duplicate/invalid OHLCV rows, orders normalized timestamps,
upserts them, and reports exact internal gaps. The candle identity is `(exchange, symbol,
timeframe, open_time)` and the lookup index ends with `open_time DESC`.

Use the CLI:

```bash
atlas-trader markets-sync
atlas-trader candles-sync --symbol BTCUSDT --timeframe 15m \
  --start 2026-01-01T00:00:00Z --end 2026-01-08T00:00:00Z
```

Or call `POST /market-data/sync` with `kind=markets`, or with `kind=candles` plus `symbol`,
`timeframe`, `start`, and `end`. Read stored data through `GET /markets` and
`GET /market-data/candles`. Symbols are opaque exchange identifiers; query discovery rather
than assuming a universal format.
