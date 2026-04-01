"""Telegram bot webhook and polling endpoints."""

import asyncio
import logging

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request

from app.config import settings
from app.deps import get_db, get_redis
from app.services.telegram_bot import TelegramAssistant

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Receive Telegram webhook updates.

    Register this endpoint as webhook URL:
    POST /telegram/register-webhook
    """
    body = await request.json()
    message = body.get("message")
    if not message:
        return {"ok": True}

    assistant = TelegramAssistant(pool=pool, redis=redis)
    try:
        response = await assistant.handle_message(message)
        if response:
            chat_id = message["chat"]["id"]
            await assistant.send_response(chat_id, response)
    except Exception as e:
        logger.error("Telegram webhook handler error: %s", e)
    finally:
        await assistant.close()

    return {"ok": True}


@router.post("/register-webhook")
async def register_telegram_webhook(request: Request):
    """Register this server as Telegram webhook.

    Body (optional): {"url": "https://your-domain.com/telegram/webhook"}
    If no url provided, uses Cloudflare tunnel domain.
    """
    import httpx

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    webhook_url = body.get("url", f"https://alphatrade.visualfactory.ai/telegram/webhook")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/setWebhook",
            json={"url": webhook_url},
        )
        result = resp.json()

    logger.info("Telegram webhook registered: %s → %s", webhook_url, result)
    return {"status": "registered", "url": webhook_url, "telegram_response": result}


@router.post("/unregister-webhook")
async def unregister_telegram_webhook():
    """Remove Telegram webhook (switch to polling mode)."""
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/deleteWebhook",
        )
        result = resp.json()

    return {"status": "unregistered", "telegram_response": result}


async def run_telegram_polling(pool: asyncpg.Pool, redis: aioredis.Redis):
    """Long-polling mode for Telegram bot (no webhook needed).

    Called from main.py lifespan as a background task.
    """
    import httpx

    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.info("Telegram bot not configured, skipping polling")
        return

    base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    offset = 0

    logger.info("Telegram bot polling started")

    async with httpx.AsyncClient(timeout=35) as client:
        while True:
            try:
                resp = await client.get(
                    f"{base_url}/getUpdates",
                    params={"offset": offset, "timeout": 30, "allowed_updates": '["message"]'},
                )
                data = resp.json()

                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    message = update.get("message")
                    if not message:
                        continue

                    assistant = TelegramAssistant(pool=pool, redis=redis)
                    try:
                        response = await assistant.handle_message(message)
                        if response:
                            chat_id = message["chat"]["id"]
                            await assistant.send_response(chat_id, response)
                    except Exception as e:
                        logger.error("Telegram polling handler error: %s", e)
                    finally:
                        await assistant.close()

            except asyncio.CancelledError:
                logger.info("Telegram polling cancelled")
                break
            except Exception as e:
                logger.error("Telegram polling error: %s", e)
                await asyncio.sleep(5)
