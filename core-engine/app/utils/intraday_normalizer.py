"""
Unified intraday snapshot normalization.

KIS API's quote endpoint returns session-wide OHLC (day open/high/low),
not true per-minute bars. All storage and display paths must normalize
these into close-only snapshots (open=high=low=close) before use.
"""


def normalize_intraday_snapshot(record):
    """Mutate a record's OHLC to close-only snapshot. Returns the record."""
    if getattr(record, "interval", None) != "1m":
        return record
    record.open = record.close
    record.high = record.close
    record.low = record.close
    return record


def is_synthetic_intraday(rows) -> bool:
    """Detect whether 1m rows contain leaked session OHLC rather than true per-minute bars."""
    if len(rows) < 10:
        return False

    unique_bars = {
        (
            float(row["open"] or 0),
            float(row["high"] or 0),
            float(row["low"] or 0),
            float(row["close"] or 0),
            int(row["volume"] or 0),
        )
        for row in rows
    }
    if len(unique_bars) <= 3:
        return True

    opens = [float(row["open"] or 0) for row in rows]
    highs = [float(row["high"] or 0) for row in rows]
    closes = [float(row["close"] or 0) for row in rows]

    return len(set(opens)) <= 3 and len(set(highs)) <= 3 and len(set(closes)) > 3


def normalize_intraday_rows(rows):
    """Transform DB rows into close-only snapshots for charting."""
    return [
        {
            "time": row["time"],
            "open": row["close"],
            "high": row["close"],
            "low": row["close"],
            "close": row["close"],
            "volume": row["volume"],
        }
        for row in rows
    ]
