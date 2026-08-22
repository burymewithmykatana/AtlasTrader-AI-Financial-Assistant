# n8n integration

Phase 1 defines only the future `01_market_data_sync` scheduling concept. No trading
workflow exists. Workflows call AtlasTrader HTTP use cases and never contain strategy,
portfolio, risk, or exchange-specific business logic.

See [01_market_data_sync.md](01_market_data_sync.md).
