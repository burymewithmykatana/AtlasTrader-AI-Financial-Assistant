from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from atlas_trader.domain.metadata import Metadata, MetadataValue

DECIMAL_TAG = "__atlas_decimal__"


@dataclass(frozen=True, slots=True)
class UpsertStats:
    inserted: int
    updated: int


def encode_metadata(metadata: Metadata) -> dict[str, Any]:
    """Preserve Decimal types in JSONB without converting through binary float."""
    return {key: _encode_value(value) for key, value in metadata.items()}


def decode_metadata(metadata: dict[str, Any]) -> Metadata:
    return {key: _decode_value(value) for key, value in metadata.items()}


def _encode_value(value: MetadataValue) -> Any:
    if isinstance(value, Decimal):
        return {DECIMAL_TAG: str(value)}
    if isinstance(value, dict):
        return {key: _encode_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_encode_value(item) for item in value]
    return value


def _decode_value(value: Any) -> MetadataValue:
    if isinstance(value, dict):
        if set(value) == {DECIMAL_TAG} and isinstance(value[DECIMAL_TAG], str):
            return Decimal(value[DECIMAL_TAG])
        return {str(key): _decode_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise ValueError(f"unsupported metadata value from persistence: {type(value).__name__}")
