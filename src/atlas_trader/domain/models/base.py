"""Shared domain model behavior."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

ZERO = Decimal("0")


class DomainModel(BaseModel):
    """Immutable, strict value model used at domain boundaries."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
