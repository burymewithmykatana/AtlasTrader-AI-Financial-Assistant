from enum import StrEnum


class AssetClass(StrEnum):
    CRYPTO = "crypto"
    STABLECOIN = "stablecoin"
    GOLD_BACKED = "gold_backed"
    FIAT = "fiat"
    UNKNOWN = "unknown"
