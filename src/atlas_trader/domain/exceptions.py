"""Stable domain-level errors exposed by ports and use cases."""


class AtlasTraderError(Exception):
    """Base class for expected application and domain failures."""


class ExchangeError(AtlasTraderError):
    """Base class for exchange-port failures."""


class ExchangeDataNotFoundError(ExchangeError):
    """Requested exchange data or an order does not exist."""


class ExchangeRequestError(ExchangeError):
    """An exchange operation was requested with invalid inputs."""


class ExchangeOrderRejectedError(ExchangeError):
    """The adapter deliberately rejected an order request."""


class IdempotencyConflictError(ExchangeError):
    """A client order ID was reused for different execution parameters."""


class InvalidOrderStateError(ExchangeError):
    """An order transition is invalid for its current terminal state."""


class PaperExecutionRejectedError(AtlasTraderError):
    """A PAPER fill cannot be safely simulated from the supplied state."""


class ReconciliationError(AtlasTraderError):
    """Persisted PAPER execution state is internally inconsistent."""


class InvalidSystemStateTransitionError(AtlasTraderError):
    """An operator requested a prohibited system-state transition."""
