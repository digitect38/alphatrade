import json
import logging

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RedisPublisher:
    def __init__(self, client: aioredis.Redis):
        self.client = client

    async def publish_ohlcv(self, stock_code: str, data: dict) -> int:
        channel = f"ohlcv:{stock_code}"
        payload = json.dumps(data, default=str)
        count = await self.client.publish(channel, payload)
        logger.debug("Published to %s, subscribers=%d", channel, count)
        return count

    async def publish_event(self, event_type: str, data: dict) -> int:
        channel = f"events:{event_type}"
        payload = json.dumps(data, default=str)
        count = await self.client.publish(channel, payload)
        logger.debug("Published to %s, subscribers=%d", channel, count)
        return count
