# KIS Daily Backfill

## Purpose

Populate real `1d` OHLCV history for the active universe from KIS and replace corrupted daily rows.

This is needed because:
- `trading_loop` previously stored current-price snapshots as `1d`
- `Asset Detail` needs clean daily history for `1M+` ranges

## What The Backfill Does

- loads active symbols from `universe`
- fetches about one year of daily bars from KIS
- deletes existing `1d` rows for that symbol/date window
- inserts the fetched daily bars back into `ohlcv`

Script:
- [backfill_daily.py](/Users/woosj/DevelopMac/alpha_trade/core-engine/app/maintenance/backfill_daily.py)

## Runtime Command

```bash
docker compose exec -T core-engine python -m app.maintenance.backfill_daily
```

## Current Limitation

KIS mock environment may return `500` for some symbols. In that case:
- the script continues
- successful symbols are still backfilled
- failed symbols remain unchanged

## Related Fix

[loop.py](/Users/woosj/DevelopMac/alpha_trade/core-engine/app/trading/loop.py) was updated so live snapshots are stored as `1m`, not `1d`, to avoid re-corrupting daily history.
