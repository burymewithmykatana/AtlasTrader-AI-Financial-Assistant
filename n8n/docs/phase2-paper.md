# Phase 2 PAPER workflows

Import the five JSON files from `n8n/workflows/` and review them before activating any
schedule. They require only AtlasTrader's HTTP API; no Nobitex token, wallet credential,
Telegram token, or database credential is used by these workflows.

Configure these n8n environment variables:

- `ATLAS_BASE_URL`, for example `http://application:8000` inside Compose.
- `ATLAS_EXCHANGE`, `ATLAS_SYMBOL`, and `ATLAS_TIMEFRAME` for market synchronization.

The workflow set is deliberately thin:

1. `01_market_data_sync` requests a bounded public-data synchronization.
2. `02_paper_trading_cycle` reads the latest stored signal and submits only its ID. The
   API resolves configured quantity, risk, idempotency, and execution.
3. `03_paper_reconciliation` checks durable intent/fill/portfolio state.
4. `04_watchdog` checks `/health` and `/admin/status`. PAUSED or KILLED goes only to an
   operator-review stop; the workflow never calls resume or reset-kill.
5. `05_daily_report` reads PAPER portfolio and order state for a downstream reporting
   destination chosen by the operator.

All exports are inactive by default. Configure an n8n Error Workflow for operational
alerts. HTTP failures stop the execution and enter that error path; do not configure
blind retries outside n8n's bounded retry settings. AtlasTrader makes cycle retries safe
through deterministic order IDs and unique fills, but repeated failures still require
operator review.

If reconciliation reports `consistent=false`, if `/health` repeatedly fails, or if the
system state is KILLED, disable the PAPER cycle schedule and investigate AtlasTrader's
system events. Never add an n8n path that automatically calls `/admin/reset-kill` or
`/admin/resume`.
