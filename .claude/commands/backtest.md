Run a backtest for the given stock code with the production ensemble signal engine.

Arguments format: STOCK_CODE [STRATEGY] [DURATION]
- STOCK_CODE: 6-digit code (e.g., 005930)
- STRATEGY: ensemble (default), momentum, mean_reversion, conservative, aggressive
- DURATION: 1Y (default), 3M, 6M, 2Y, 3Y, 5Y, MAX

Example: /backtest 005930 momentum 2Y

Execute:
```
curl -s -X POST http://localhost:8000/strategy/backtest \
  -H 'Content-Type: application/json' \
  -d '{"stock_code":"STOCK_CODE","strategy":"STRATEGY","initial_capital":10000000,"interval":"1d","benchmark":"buy_and_hold","max_drawdown_stop":0.08}'
```

Parse $ARGUMENTS to extract stock_code, strategy, duration. Build start_date from duration.

Report:
1. Period and bars count
2. Total return vs benchmark
3. Sharpe ratio, MDD, win rate
4. Statistical warnings (if any)
5. Trade count and key trades
6. Brief interpretation of results
