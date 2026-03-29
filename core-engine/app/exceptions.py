"""Custom exception hierarchy for AlphaTrade.

Usage:
    raise BrokerError("KIS API token expired", retryable=True)
    raise DataError("No OHLCV data for 005930")
    raise RiskViolation("종목당 한도 초과: 250,000원")
"""


class AlphaTradeError(Exception):
    """Base exception for all AlphaTrade errors."""

    def __init__(self, message: str = "", retryable: bool = False):
        self.message = message
        self.retryable = retryable
        super().__init__(message)


class DataError(AlphaTradeError):
    """Data collection or query errors (DB, API responses)."""
    pass


class BrokerError(AlphaTradeError):
    """Broker API errors (KIS order submission, token refresh)."""
    pass


class AnalysisError(AlphaTradeError):
    """Analysis computation errors (insufficient data, calculation failure)."""
    pass


class RiskViolation(AlphaTradeError):
    """Risk management rule violations (position limit, daily loss, etc.)."""
    pass


class ExternalAPIError(AlphaTradeError):
    """External API errors (DART, Naver, LLM APIs)."""
    pass
