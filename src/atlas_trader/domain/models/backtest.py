from decimal import Decimal
from uuid import UUID

from pydantic import AwareDatetime, Field

from atlas_trader.domain.enums.backtest import BacktestExecutionModel, BacktestStatus
from atlas_trader.domain.enums.order_side import OrderSide
from atlas_trader.domain.enums.timeframe import Timeframe
from atlas_trader.domain.metadata import Metadata
from atlas_trader.domain.models.base import ZERO, DomainModel


class BacktestConfig(DomainModel):
    exchange: str
    symbol: str
    timeframe: Timeframe
    start_time: AwareDatetime
    end_time: AwareDatetime
    initial_capital: Decimal = Field(gt=ZERO)
    fee_rate: Decimal = Field(default=Decimal("0.001"), ge=ZERO, lt=Decimal("1"))
    slippage_bps: Decimal = Field(default=ZERO, ge=ZERO, le=Decimal("1000"))
    execution_model: BacktestExecutionModel = BacktestExecutionModel.NEXT_CANDLE_OPEN
    strategy_parameters: Metadata = Field(default_factory=dict)


class BacktestTrade(DomainModel):
    sequence: int = Field(ge=1)
    side: OrderSide
    signal_time: AwareDatetime
    execution_time: AwareDatetime
    price: Decimal = Field(gt=ZERO)
    quantity: Decimal = Field(gt=ZERO)
    fee: Decimal = Field(ge=ZERO)
    realized_pnl: Decimal | None = None


class BacktestMetrics(DomainModel):
    initial_capital: Decimal = Field(gt=ZERO)
    ending_equity: Decimal = Field(ge=ZERO)
    absolute_pnl: Decimal
    return_pct: Decimal
    number_of_entries: int = Field(ge=0)
    number_of_exits: int = Field(ge=0)
    completed_trades: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    win_rate_pct: Decimal = Field(ge=ZERO, le=Decimal("100"))
    gross_profit: Decimal = Field(ge=ZERO)
    gross_loss: Decimal = Field(ge=ZERO)
    profit_factor: Decimal | None = Field(default=None, ge=ZERO)
    maximum_drawdown_amount: Decimal = Field(ge=ZERO)
    maximum_drawdown_pct: Decimal = Field(ge=ZERO, le=Decimal("100"))
    total_fees: Decimal = Field(ge=ZERO)
    unrealized_pnl: Decimal
    buy_and_hold_return_pct: Decimal
    exposure_pct: Decimal = Field(ge=ZERO, le=Decimal("100"))


class BacktestResult(DomainModel):
    id: UUID
    status: BacktestStatus
    strategy_name: str
    strategy_version: str
    strategy_parameters: Metadata
    config: BacktestConfig
    metrics: BacktestMetrics
    trades: tuple[BacktestTrade, ...]
    execution_assumptions: Metadata
    code_version: str | None = None
    started_at: AwareDatetime
    completed_at: AwareDatetime
