from enum import StrEnum


class ExecutionMode(StrEnum):
    BACKTEST = "backtest"
    PAPER = "paper"
    TESTNET = "testnet"
    LIVE = "live"
