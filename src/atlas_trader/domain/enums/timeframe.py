from datetime import timedelta
from enum import StrEnum


class Timeframe(StrEnum):
    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    THIRTY_MINUTES = "30m"
    ONE_HOUR = "1h"
    FOUR_HOURS = "4h"
    ONE_DAY = "1d"

    @property
    def duration(self) -> timedelta:
        return {
            Timeframe.ONE_MINUTE: timedelta(minutes=1),
            Timeframe.FIVE_MINUTES: timedelta(minutes=5),
            Timeframe.FIFTEEN_MINUTES: timedelta(minutes=15),
            Timeframe.THIRTY_MINUTES: timedelta(minutes=30),
            Timeframe.ONE_HOUR: timedelta(hours=1),
            Timeframe.FOUR_HOURS: timedelta(hours=4),
            Timeframe.ONE_DAY: timedelta(days=1),
        }[self]
