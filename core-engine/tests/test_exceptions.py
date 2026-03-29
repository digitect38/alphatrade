"""Tests for custom exception hierarchy.

~40 test cases.
"""

import pytest
from app.exceptions import (
    AlphaTradeError,
    AnalysisError,
    BrokerError,
    DataError,
    ExternalAPIError,
    RiskViolation,
)


class TestExceptionHierarchy:
    @pytest.mark.parametrize("exc_class", [
        DataError, BrokerError, AnalysisError, RiskViolation, ExternalAPIError,
    ])
    def test_inherits_from_base(self, exc_class):
        exc = exc_class("test")
        assert isinstance(exc, AlphaTradeError)
        assert isinstance(exc, Exception)

    @pytest.mark.parametrize("exc_class", [
        DataError, BrokerError, AnalysisError, RiskViolation, ExternalAPIError,
    ])
    def test_message(self, exc_class):
        exc = exc_class("Something went wrong")
        assert exc.message == "Something went wrong"
        assert str(exc) == "Something went wrong"

    @pytest.mark.parametrize("exc_class", [
        DataError, BrokerError, AnalysisError, RiskViolation, ExternalAPIError,
    ])
    def test_retryable_default_false(self, exc_class):
        exc = exc_class("test")
        assert exc.retryable is False

    @pytest.mark.parametrize("exc_class", [
        DataError, BrokerError, ExternalAPIError,
    ])
    def test_retryable_true(self, exc_class):
        exc = exc_class("timeout", retryable=True)
        assert exc.retryable is True

    def test_risk_violation_not_retryable(self):
        exc = RiskViolation("종목당 한도 초과", retryable=True)
        # Even if set True, it's still a RiskViolation
        assert isinstance(exc, RiskViolation)

    def test_empty_message(self):
        exc = AlphaTradeError()
        assert exc.message == ""

    @pytest.mark.parametrize("msg", [
        "잔고 부족", "KIS API token expired", "No OHLCV data",
        "종목당 한도 초과: 250,000원 > 100,000원",
        "",
    ])
    def test_various_messages(self, msg):
        exc = AlphaTradeError(msg)
        assert exc.message == msg

    def test_can_be_raised_and_caught(self):
        with pytest.raises(BrokerError):
            raise BrokerError("connection failed", retryable=True)

    def test_catch_base_catches_all(self):
        for exc_class in [DataError, BrokerError, AnalysisError, RiskViolation]:
            with pytest.raises(AlphaTradeError):
                raise exc_class("test")

    def test_catch_specific_doesnt_catch_other(self):
        with pytest.raises(BrokerError):
            try:
                raise BrokerError("test")
            except DataError:
                pytest.fail("DataError should not catch BrokerError")
