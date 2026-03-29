"""Prometheus metrics definitions for AlphaTrade.

All metrics are defined here and imported where needed.
"""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

registry = CollectorRegistry()

# --- HTTP ---
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
    registry=registry,
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    registry=registry,
)

# --- Business ---
ORDERS_TOTAL = Counter(
    "orders_total",
    "Total trading orders",
    ["side", "status"],
    registry=registry,
)
SIGNALS_TOTAL = Counter(
    "signals_total",
    "Total strategy signals generated",
    ["signal"],
    registry=registry,
)
PORTFOLIO_VALUE = Gauge(
    "portfolio_value_krw",
    "Current portfolio total value in KRW",
    registry=registry,
)
COLLECTION_TOTAL = Counter(
    "data_collection_total",
    "Total data collection operations",
    ["source", "status"],
    registry=registry,
)
