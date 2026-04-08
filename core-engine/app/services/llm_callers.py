"""LLM Chat — API callers for OpenAI, Anthropic, and Ollama."""

import asyncio
import logging
import os

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_OPENAI_RESPONSES_MODELS = {"gpt-5.4", "gpt-5.4-pro", "gpt-5.4-mini", "gpt-5.4-nano"}
_OPENAI_FALLBACK_CHAIN = ["gpt-5.4", "gpt-4.1", "gpt-4o-mini"]


def _build_vision_content(text: str, image_data: str, provider: str):
    """Build multimodal content for vision-capable LLMs."""
    if image_data.startswith("data:"):
        header, b64 = image_data.split(",", 1)
        media_type = header.split(":")[1].split(";")[0]
    else:
        b64 = image_data
        media_type = "image/png"

    if provider == "anthropic":
        return [
            {"type": "text", "text": text},
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
        ]
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
    ]


async def call_claude(messages: list[dict], system: str, api_key: str, model: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 4000, "system": system, "messages": messages},
            timeout=settings.http_timeout_llm,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]


async def call_ollama(messages: list[dict], system: str, model: str = "exaone3.5:2.4b") -> str:
    host = "host.docker.internal" if os.path.exists("/.dockerenv") else "localhost"
    full_messages = [{"role": "system", "content": system}] + messages
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"http://{host}:11434/api/chat",
            json={"model": model, "messages": full_messages, "stream": False, "options": {"num_ctx": 2048}},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "Ollama 응답 없음")


async def call_openai(messages: list[dict], system: str, api_key: str, model: str) -> str:
    models_to_try = [model] + [m for m in _OPENAI_FALLBACK_CHAIN if m != model]
    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        last_error = None
        for attempt_model in models_to_try:
            for retry in range(2):
                try:
                    if attempt_model in _OPENAI_RESPONSES_MODELS:
                        input_parts = [{"role": "developer", "content": system}]
                        input_parts.extend(messages)
                        resp = await client.post("https://api.openai.com/v1/responses", headers=headers,
                            json={"model": attempt_model, "input": input_parts}, timeout=settings.http_timeout_llm)
                    else:
                        full_messages = [{"role": "system", "content": system}] + messages
                        resp = await client.post("https://api.openai.com/v1/chat/completions", headers=headers,
                            json={"model": attempt_model, "max_tokens": 4000, "messages": full_messages}, timeout=settings.http_timeout_llm)
                    if resp.status_code == 429:
                        wait = int(resp.headers.get("retry-after", "3"))
                        logger.warning("OpenAI 429 on %s, waiting %ds (retry %d)", attempt_model, wait, retry)
                        await asyncio.sleep(min(wait, 10))
                        continue
                    resp.raise_for_status()
                    if attempt_model in _OPENAI_RESPONSES_MODELS:
                        data = resp.json()
                        for item in data.get("output", []):
                            if item.get("type") == "message":
                                for c in item.get("content", []):
                                    if c.get("type") == "output_text":
                                        if attempt_model != model:
                                            logger.info("OpenAI fallback: %s → %s", model, attempt_model)
                                        return c["text"]
                        return data.get("output_text", "응답을 파싱할 수 없습니다.")
                    else:
                        if attempt_model != model:
                            logger.info("OpenAI fallback: %s → %s", model, attempt_model)
                        return resp.json()["choices"][0]["message"]["content"]
                except httpx.HTTPStatusError as e:
                    last_error = e
                    if e.response.status_code == 429:
                        await asyncio.sleep(3)
                        continue
                    break
                except Exception as e:
                    last_error = e
                    break
            logger.warning("OpenAI model %s failed, trying next fallback", attempt_model)
        raise last_error or Exception("All OpenAI models failed")
