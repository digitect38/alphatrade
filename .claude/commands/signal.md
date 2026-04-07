Get the latest trading signal for a stock.

Arguments: STOCK_CODE (e.g., 005930)

Execute:
```
curl -s -X POST http://localhost:8000/strategy/signal \
  -H 'Content-Type: application/json' \
  -d '{"stock_code":"$ARGUMENTS","interval":"1d"}'
```

Report: signal (BUY/SELL/HOLD), strength, ensemble score, component breakdown (momentum, mean_reversion, volume, sentiment), and reasons.
