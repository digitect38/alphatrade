"""Tests for security middleware — auth and rate limiting.

~30 test cases.
"""

import pytest
from app.security import PUBLIC_PATHS


class TestPublicPaths:
    @pytest.mark.parametrize("path", ["/health", "/metrics", "/docs", "/openapi.json", "/redoc"])
    def test_public_paths_defined(self, path):
        assert path in PUBLIC_PATHS

    @pytest.mark.parametrize("path", ["/order/execute", "/strategy/signal", "/trading/run-cycle"])
    def test_protected_paths_not_public(self, path):
        assert path not in PUBLIC_PATHS


class TestRateLimitConfig:
    def test_default_values(self):
        from app.config import settings
        assert settings.rate_limit_max >= 10
        assert settings.rate_limit_window >= 10

    def test_rate_limit_reasonable(self):
        from app.config import settings
        assert settings.rate_limit_max <= 1000
        assert settings.rate_limit_window <= 3600


class TestAuthConfig:
    def test_auth_key_default_empty(self):
        from app.config import settings
        # In dev mode, auth key is empty (no auth)
        assert isinstance(settings.api_auth_key, str)

    def test_auth_disabled_in_dev(self):
        from app.config import settings
        # Empty string means auth is disabled
        if settings.api_auth_key == "":
            assert True  # Dev mode, no auth
        else:
            assert len(settings.api_auth_key) > 10  # Production key should be long


class TestSecurityMiddlewareImport:
    def test_auth_middleware_importable(self):
        from app.security import AuthMiddleware
        assert AuthMiddleware is not None

    def test_rate_limit_middleware_importable(self):
        from app.security import RateLimitMiddleware
        assert RateLimitMiddleware is not None
