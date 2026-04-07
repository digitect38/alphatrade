Fetch real-time KIS stock price for the given stock code.

Execute via the core-engine API:
```
curl -s http://localhost:8000/asset/$ARGUMENTS/overview
```

Also check Redis real-time cache:
```
docker exec alphatrade-redis redis-cli -a redis_dev_2026 --no-auth-warning HGETALL "market:state:$ARGUMENTS"
```

Report: stock name, current price, change %, volume, and whether the data is real-time (Redis) or DB fallback.
