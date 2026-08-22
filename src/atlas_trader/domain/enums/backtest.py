from enum import StrEnum


class BacktestExecutionModel(StrEnum):
    NEXT_CANDLE_OPEN = "next_candle_open"


class BacktestStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
