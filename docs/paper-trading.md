# PAPER trading safety contract

Phase 2 is a deterministic simulation layer. It never authenticates to Nobitex and never
submits, cancels, or queries an exchange order. Current public quotes are used only as
inputs to a local fill model.

## Canonical cycle

`POST /trading/cycle` accepts a persisted signal ID and an optional quantity. When the
quantity is omitted, AtlasTrader uses `PAPER_DEFAULT_ORDER_QUANTITY`; n8n never calculates
position size.

The application performs these boundaries in order:

1. load the stored signal, market, public quote, portfolio, and persistent risk state;
2. evaluate every configured risk rule and persist an APPROVED or REJECTED OrderIntent;
3. commit that intent before attempting execution;
4. for APPROVED intents only, calculate a deterministic adverse-slippage fill;
5. atomically persist the unique fill, cash/position updates, snapshot, and FILLED state;
6. reconcile intents, fills, cash, and positions; and
7. persist correlation-linked system events.

HOLD creates no intent. Rejected decisions create an auditable REJECTED intent and no
fill. A retry uses the deterministic `client_order_id`; changed execution parameters are
an explicit conflict. A retry after a committed fill returns the existing fill.

## Execution and accounting

- Spot, long-only, one PAPER account; no leverage, shorting, or margin.
- BUY uses best ask plus configured adverse fixed-bps slippage.
- SELL uses best bid minus configured adverse fixed-bps slippage.
- Fees are a separate configured percentage of fill notional.
- BUY cost basis includes its fee; SELL realized PnL deducts its fee.
- Every financial domain/database value is Decimal/NUMERIC.

## Operational state

`ENABLED` permits risk-reviewed cycles. `PAUSED` and `KILLED` block both new intent
approval and pending execution, while reads and reconciliation remain available. Routine
`POST /admin/resume` only handles PAUSED. A KILLED state requires the separate
`POST /admin/reset-kill` transition to PAUSED, operator review, and only then resume.

Reconciliation mismatches persist an event and force KILLED. A later clean reconciliation
never clears it automatically.

## Known limitations

- The first fill model is full-fill only and uses one public best price; order-book depth
  and partial fills are deferred.
- One configured quote asset and initial PAPER funding baseline are reconciled.
- The cycle consumes existing stored signals; scheduling strategy generation remains a
  separate application/API concern.
- No private exchange, wallet, testnet, live, Telegram-command, or cancellation path is
  present in Phase 2.
