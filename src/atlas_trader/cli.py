"""Phase 1 developer CLI; no authenticated or trading commands exist."""

import argparse
import asyncio
import json
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from atlas_trader.api.dependencies import (
    create_nobitex_public_adapter,
    create_nobitex_public_client,
)
from atlas_trader.application.backtest import BacktestEngine
from atlas_trader.application.market_data import (
    CandleSyncResult,
    CandleSyncService,
    MarketDiscoveryResult,
    MarketDiscoveryService,
)
from atlas_trader.config.settings import get_settings
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.models.backtest import BacktestConfig, BacktestResult
from atlas_trader.infrastructure.database.repositories.backtests import (
    SqlAlchemyBacktestRepository,
)
from atlas_trader.infrastructure.database.repositories.candles import SqlAlchemyCandleRepository
from atlas_trader.infrastructure.database.repositories.markets import SqlAlchemyMarketRepository
from atlas_trader.infrastructure.database.session import get_session_factory
from atlas_trader.strategies.ema_atr import EmaAtrStrategy


def aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed


async def run_command(args: argparse.Namespace) -> None:
    settings = get_settings()
    session_factory = get_session_factory()
    result: MarketDiscoveryResult | CandleSyncResult | BacktestResult
    async with session_factory() as session:
        try:
            if args.command == "markets-sync":
                async with create_nobitex_public_client(settings) as client:
                    result = await MarketDiscoveryService(
                        create_nobitex_public_adapter(client, settings),
                        SqlAlchemyMarketRepository(session),
                    ).run(correlation_id=str(uuid4()))
            elif args.command == "candles-sync":
                async with create_nobitex_public_client(settings) as client:
                    result = await CandleSyncService(
                        create_nobitex_public_adapter(client, settings),
                        SqlAlchemyCandleRepository(session),
                    ).sync(
                        exchange="nobitex",
                        symbol=args.symbol,
                        timeframe=Timeframe(args.timeframe),
                        start=args.start,
                        end=args.end,
                        correlation_id=str(uuid4()),
                    )
            elif args.command == "backtest":
                config = BacktestConfig(
                    exchange="nobitex",
                    symbol=args.symbol,
                    timeframe=Timeframe(args.timeframe),
                    start_time=args.start,
                    end_time=args.end,
                    initial_capital=Decimal(args.initial_capital),
                    fee_rate=Decimal(args.fee_rate),
                    slippage_bps=Decimal(args.slippage_bps),
                    strategy_parameters={
                        "fast_period": args.fast_period,
                        "slow_period": args.slow_period,
                        "atr_period": args.atr_period,
                        "atr_stop_multiple": args.atr_stop_multiple,
                    },
                )
                candles = await SqlAlchemyCandleRepository(session).list_range(
                    config.exchange,
                    config.symbol,
                    config.timeframe,
                    config.start_time,
                    config.end_time,
                )
                strategy = EmaAtrStrategy.from_parameters(config.strategy_parameters)
                result = BacktestEngine().run(strategy, candles, config)
                await SqlAlchemyBacktestRepository(session).save(result)
            else:
                raise ValueError(f"unsupported command {args.command}")
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    print(json.dumps(result.model_dump(mode="json"), indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlas-trader")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("markets-sync")

    candles = subparsers.add_parser("candles-sync")
    _add_market_period_arguments(candles)

    backtest = subparsers.add_parser("backtest")
    _add_market_period_arguments(backtest)
    backtest.add_argument("--initial-capital", default="10000")
    backtest.add_argument("--fee-rate", default="0.001")
    backtest.add_argument("--slippage-bps", default="0")
    backtest.add_argument("--fast-period", type=int, default=12)
    backtest.add_argument("--slow-period", type=int, default=26)
    backtest.add_argument("--atr-period", type=int, default=14)
    backtest.add_argument("--atr-stop-multiple", default="2")
    return parser


def _add_market_period_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", choices=[item.value for item in Timeframe], required=True)
    parser.add_argument("--start", type=aware_datetime, required=True)
    parser.add_argument("--end", type=aware_datetime, required=True)


def main() -> None:
    asyncio.run(run_command(build_parser().parse_args()))


if __name__ == "__main__":
    main()
