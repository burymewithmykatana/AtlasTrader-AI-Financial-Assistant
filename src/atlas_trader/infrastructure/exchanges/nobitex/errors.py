from atlas_trader.domain.exceptions import ExchangeError, ExchangeRequestError


class NobitexPublicError(ExchangeError):
    """Base error for the unauthenticated public API."""


class NobitexTransportError(NobitexPublicError):
    """The public API could not be reached after bounded retries."""


class NobitexRateLimitError(NobitexPublicError):
    """The public API continued rate-limiting after bounded retries."""


class NobitexResponseError(NobitexPublicError):
    """The public API returned invalid JSON or an invalid response contract."""


class NobitexRequestError(ExchangeRequestError):
    """The public API rejected a non-retryable request."""
