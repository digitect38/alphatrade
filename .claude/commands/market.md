Show current market overview — indexes, top movers, and system status.

Execute these in parallel:
```
curl -s http://localhost:8000/index/realtime
curl -s http://localhost:8000/market/movers?limit=10
curl -s http://localhost:8000/trading/mode
curl -s http://localhost:8000/trading/kill-switch/status
```

Report:
1. Market indexes (KOSPI, KOSDAQ, NASDAQ, DOW, BTC, USD/KRW)
2. Top 10 movers with price and change %
3. Trading mode (live/paper) and kill switch status
