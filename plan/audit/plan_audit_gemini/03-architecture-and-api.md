# Architecture and API (Gemini Evaluation)

## 4.1 Hybrid Blocks

| Block | Status | Evidence | Evaluation |
|---|---|---|---|
| Data Collection | Match | `core-engine/app/routes/collect.py` | News, disclosures, OHLCV endpoints exist. |
| Analysis Engine | Match | `core-engine/app/analysis/*` | Technical, volume, sector, sentiment, correlation, causality modules. |
| NLP Sentiment | Partial | `core-engine/app/analysis/sentiment.py` | Direct API calls to Claude/OpenAI are used, instead of the planned n8n AI Node routing. |
| Strategy Engine | Match | `core-engine/app/strategy/ensemble.py` | Implements the planned signal ensemble logic. |
| Execution Engine | Match | `core-engine/app/execution/*` | Broker integration, risk management, and order manager. |
| Notification | Partial | `core-engine/app/services/notification.py` | Direct notification logic in core-engine. n8n workflow-based reporting is missing. |

## 4.2 Communication Patterns

| Pattern | Status | Evidence | Evaluation |
|---|---|---|---|
| n8n -> Engine (REST) | Partial | `core-engine/app/main.py` | API exists and is used by `trading-cycle.json`, but other planned flows are missing. |
| Engine -> n8n (Webhook) | Gap | repo search | No code path found calling n8n webhooks for event triggering. |
| Engine -> DB (SQL) | Match | `core-engine/app/database.py` | Fully implemented using `asyncpg`. |
| Realtime communication | Match | `core-engine/app/services/redis_publisher.py` | Event-driven architecture with Redis Pub/Sub for core signals. |
| Dashboard communication | Partial | `dashboard/src/hooks/useApi.ts` | Uses REST API. WebSocket is configured in Nginx but not in core-engine. |

## FastAPI Route Count

Total routes: **37**
- `collect`: 4
- `analysis`: 3
- `strategy`: 3
- `order`: 3
- `portfolio`: 3
- `market`: 6
- `scanner`: 4
- `trading`: 5
- `webhook`: 2 (TradingView, n8n)
- `index`: 2
- `alert`: 2

## Observed Divergence

The "Sentiment Analysis" and "Notification" modules are currently implemented as self-contained Python services within `core-engine`. This deviates from the **Hybrid Architecture** plan, which aimed to offload these responsibilities to n8n workflows for better flexibility.
