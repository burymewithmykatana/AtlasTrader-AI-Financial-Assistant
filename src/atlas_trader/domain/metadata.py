"""Typed metadata values that cannot hide binary floating-point amounts."""

from decimal import Decimal

type MetadataValue = (
    str
    | int
    | bool
    | Decimal
    | None
    | tuple[MetadataValue, ...]
    | list[MetadataValue]
    | dict[str, MetadataValue]
)
type Metadata = dict[str, MetadataValue]
