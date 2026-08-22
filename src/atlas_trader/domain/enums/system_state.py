from enum import StrEnum


class SystemState(StrEnum):
    ENABLED = "enabled"
    PAUSED = "paused"
    KILLED = "killed"
