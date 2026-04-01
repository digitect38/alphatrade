"""Telegram LLM Trading Assistant.

Receives user messages via Telegram webhook, gathers live trading context
(portfolio, signals, market state, risk), sends to Claude API with
system prompt, and returns the AI response.

Setup:
1. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
2. Register webhook: POST /telegram/register-webhook
3. Or run polling mode: called from main.py lifespan
"""

import json
import logging
from datetime import datetime, timezone

import asyncpg
import httpx
import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 AlphaTrade AI 트레이딩 어시스턴트입니다.
한국 주식시장(KOSPI/KOSDAQ) 자동매매 시스템의 운영을 돕습니다.

역할:
- 종목 분석 질문에 실시간 데이터 기반으로 답변
- 매매 판단 보조 (최종 결정은 사용자 몫임을 명시)
- 포트폴리오 현황/리스크 설명
- 시스템 운영 질문 (킬스위치, 전략 변경 등) 안내

규칙:
- 한국어로 답변 (영어 질문에는 영어로)
- 숫자는 구체적으로 (가격, 수익률, 비중 등)
- 불확실한 정보는 솔직히 "확인 필요"라고 답변
- 투자 권유가 아닌 정보 제공임을 인지

현재 시스템 상태:
{context}"""

COMMAND_HELP = """<b>AlphaTrade Bot 명령어</b>

/status — 포트폴리오 현황
/signal <종목코드> — 매매 시그널 조회
/risk — 리스크 현황 (VaR, 스트레스)
/market — 시장 현황 (KOSPI/KOSDAQ/환율)
/kill — 킬 스위치 상태
/help — 명령어 목록

그 외 자유 질문도 가능합니다.
예: "삼성전자 지금 사도 될까?"
예: "오늘 포트폴리오 왜 빠졌어?"
예: "모멘텀 전략으로 바꿔줘"
"""


class TelegramAssistant:
    """Telegram bot that answers trading questions with LLM + live context."""

    def __init__(self, pool: asyncpg.Pool, redis: aioredis.Redis):
        self.pool = pool
        self.redis = redis
        self.client = httpx.AsyncClient(timeout=30)
        self._base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

    async def handle_message(self, message: dict) -> str | None:
        """Process incoming Telegram message and return response text."""
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()

        if not text or not chat_id:
            return None

        # Security: only respond to authorized chat
        if str(chat_id) != settings.telegram_chat_id:
            logger.warning("Unauthorized Telegram chat: %s", chat_id)
            return None

        # Handle commands
        if text.startswith("/"):
            return await self._handle_command(text, chat_id)

        # Free-form question → LLM
        return await self._ask_llm(text, chat_id)

    async def _handle_command(self, text: str, chat_id: int) -> str:
        """Handle bot commands."""
        cmd = text.split()[0].lower().replace("@alphatrade38_bot", "")
        args = text.split()[1:] if len(text.split()) > 1 else []

        if cmd == "/help" or cmd == "/start":
            return COMMAND_HELP

        if cmd == "/status":
            return await self._cmd_status()

        if cmd == "/signal":
            code = args[0] if args else "005930"
            return await self._cmd_signal(code)

        if cmd == "/risk":
            return await self._cmd_risk()

        if cmd == "/market":
            return await self._cmd_market()

        if cmd == "/kill":
            return await self._cmd_kill_status()

        return f"알 수 없는 명령어: {cmd}\n/help 로 명령어 목록을 확인하세요."

    async def _cmd_status(self) -> str:
        """Portfolio status summary."""
        async with self.pool.acquire() as conn:
            snap = await conn.fetchrow(
                "SELECT total_value, cash, invested, daily_pnl, daily_return, cumulative_return, positions_count "
                "FROM portfolio_snapshots ORDER BY time DESC LIMIT 1"
            )
            positions = await conn.fetch(
                "SELECT pp.stock_code, s.stock_name, pp.quantity, pp.avg_price, pp.current_price "
                "FROM portfolio_positions pp LEFT JOIN stocks s ON pp.stock_code = s.stock_code "
                "WHERE pp.quantity > 0 ORDER BY pp.quantity * pp.current_price DESC"
            )

        if not snap:
            return "포트폴리오 스냅샷이 없습니다."

        tv = float(snap["total_value"])
        cash = float(snap["cash"])
        dp = float(snap["daily_pnl"]) if snap["daily_pnl"] else 0
        dr = float(snap["daily_return"]) * 100 if snap["daily_return"] else 0
        cr = float(snap["cumulative_return"]) * 100 if snap["cumulative_return"] else 0

        lines = [
            "<b>📊 포트폴리오 현황</b>",
            f"총 평가금: {tv:,.0f}원",
            f"현금: {cash:,.0f}원",
            f"일간 손익: {dp:+,.0f}원 ({dr:+.2f}%)",
            f"누적 수익률: {cr:+.2f}%",
            f"보유 종목: {snap['positions_count']}개",
        ]

        if positions:
            lines.append("\n<b>보유 종목:</b>")
            for p in positions[:10]:
                name = p["stock_name"] or p["stock_code"]
                qty = p["quantity"]
                avg = float(p["avg_price"])
                cur = float(p["current_price"]) if p["current_price"] else avg
                pnl_pct = ((cur - avg) / avg * 100) if avg > 0 else 0
                lines.append(f"  {name} {qty}주 {cur:,.0f}원 ({pnl_pct:+.1f}%)")

        return "\n".join(lines)

    async def _cmd_signal(self, stock_code: str) -> str:
        """Get latest signal for a stock."""
        async with self.pool.acquire() as conn:
            sig = await conn.fetchrow(
                "SELECT signal, strength, reasons FROM strategy_signals "
                "WHERE stock_code = $1 ORDER BY time DESC LIMIT 1", stock_code,
            )
            name_row = await conn.fetchrow(
                "SELECT stock_name FROM stocks WHERE stock_code = $1", stock_code,
            )
            price_row = await conn.fetchrow(
                "SELECT close FROM ohlcv WHERE stock_code = $1 AND interval = '1d' ORDER BY time DESC LIMIT 1",
                stock_code,
            )

        name = name_row["stock_name"] if name_row else stock_code
        price = float(price_row["close"]) if price_row else 0

        if not sig:
            return f"{name} ({stock_code}): 시그널 없음\n현재가: {price:,.0f}원"

        signal = sig["signal"]
        strength = float(sig["strength"])
        emoji = "🟢" if signal == "BUY" else "🔴" if signal == "SELL" else "⚪"
        reasons = sig["reasons"] if sig["reasons"] else "[]"
        if isinstance(reasons, str):
            import json as _json
            try:
                reasons = _json.loads(reasons)
            except Exception:
                reasons = [reasons]

        lines = [
            f"<b>{emoji} {name} ({stock_code})</b>",
            f"시그널: {signal} (강도 {strength:.2f})",
            f"현재가: {price:,.0f}원",
        ]
        if reasons:
            lines.append("근거:")
            for r in reasons[:5]:
                lines.append(f"  • {r}")

        return "\n".join(lines)

    async def _cmd_risk(self) -> str:
        """Risk summary."""
        from app.risk.realtime_pnl import compute_realtime_pnl
        pnl = await compute_realtime_pnl(pool=self.pool, redis=self.redis)

        lines = [
            "<b>🛡️ 리스크 현황</b>",
            f"총 평가금: {pnl['total_value']:,.0f}원",
            f"미실현 손익: {pnl['total_unrealized_pnl']:+,.0f}원 ({pnl['total_unrealized_pct']:+.2f}%)",
            f"일간 손익: {pnl['daily_pnl']:+,.0f}원 ({pnl['daily_return_pct']:+.2f}%)",
            f"보유 {pnl['positions_count']}종목",
        ]

        # Kill switch status
        ks = await self.redis.get("trading:kill_switch")
        lines.append(f"\n킬 스위치: {'🔴 활성' if ks == 'active' else '🟢 비활성'}")

        return "\n".join(lines)

    async def _cmd_market(self) -> str:
        """Market overview."""
        try:
            resp = await self.client.get(f"http://localhost:{settings.core_engine_port}/index/realtime")
            data = resp.json()
            lines = ["<b>💹 시장 현황</b>"]
            for idx in data.get("indexes", []):
                emoji = "📈" if idx["change"] > 0 else "📉" if idx["change"] < 0 else "➡️"
                lines.append(f"{emoji} {idx['name']}: {idx['price']:,.2f} ({idx['change_pct']:+.2f}%)")
            return "\n".join(lines)
        except Exception as e:
            return f"시장 데이터 조회 실패: {e}"

    async def _cmd_kill_status(self) -> str:
        """Kill switch status."""
        ks = await self.redis.get("trading:kill_switch")
        bf = await self.redis.get("trading:broker_failures")
        active = ks == "active" or (isinstance(ks, bytes) and ks == b"active")
        fails = int(bf) if bf else 0

        return (
            f"<b>{'🔴' if active else '🟢'} 킬 스위치: {'활성' if active else '비활성'}</b>\n"
            f"브로커 실패: {fails}/{settings.risk_broker_max_failures}"
        )

    async def _ask_llm(self, question: str, chat_id: int) -> str:
        """Send question to LLM with live trading context.

        Uses OpenAI (GPT-4o-mini) if available, falls back to Claude Haiku.
        """
        if not settings.openai_api_key and not settings.anthropic_api_key:
            return "LLM API 키가 설정되지 않았습니다. (OPENAI_API_KEY 또는 ANTHROPIC_API_KEY)"

        context = await self._build_context(question)

        try:
            if settings.openai_api_key:
                answer = await self._call_openai(question, context)
            else:
                answer = await self._call_claude(question, context)

            if len(answer) > 3800:
                answer = answer[:3800] + "\n\n...(생략)"
            return answer

        except Exception as e:
            logger.error("LLM call failed: %s", e)
            return f"AI 응답 실패: {e}\n\n/help 명령어를 사용해보세요."

    async def _call_openai(self, question: str, context: str) -> str:
        """Call OpenAI GPT-4o-mini."""
        resp = await self.client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "max_tokens": 1000,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
                    {"role": "user", "content": question},
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def _call_claude(self, question: str, context: str) -> str:
        """Call Anthropic Claude Haiku (fallback)."""
        resp = await self.client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1000,
                "system": SYSTEM_PROMPT.format(context=context),
                "messages": [{"role": "user", "content": question}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]

    async def _build_context(self, question: str) -> str:
        """Build live trading context for the LLM system prompt."""
        parts = []

        # Portfolio snapshot
        try:
            async with self.pool.acquire() as conn:
                snap = await conn.fetchrow(
                    "SELECT total_value, cash, daily_pnl, daily_return, positions_count "
                    "FROM portfolio_snapshots ORDER BY time DESC LIMIT 1"
                )
            if snap:
                parts.append(
                    f"포트폴리오: 총 {float(snap['total_value']):,.0f}원, "
                    f"현금 {float(snap['cash']):,.0f}원, "
                    f"일간 {float(snap['daily_pnl'] or 0):+,.0f}원, "
                    f"보유 {snap['positions_count']}종목"
                )
        except Exception:
            pass

        # Positions
        try:
            async with self.pool.acquire() as conn:
                positions = await conn.fetch(
                    "SELECT pp.stock_code, s.stock_name, pp.quantity, pp.avg_price, pp.current_price "
                    "FROM portfolio_positions pp LEFT JOIN stocks s ON pp.stock_code = s.stock_code "
                    "WHERE pp.quantity > 0 LIMIT 10"
                )
            if positions:
                pos_lines = []
                for p in positions:
                    name = p["stock_name"] or p["stock_code"]
                    avg = float(p["avg_price"])
                    cur = float(p["current_price"]) if p["current_price"] else avg
                    pnl = ((cur - avg) / avg * 100) if avg > 0 else 0
                    pos_lines.append(f"{name}({p['stock_code']}) {p['quantity']}주 {cur:,.0f}원 ({pnl:+.1f}%)")
                parts.append("보유종목: " + ", ".join(pos_lines))
        except Exception:
            pass

        # Kill switch
        try:
            ks = await self.redis.get("trading:kill_switch")
            active = ks == "active" or (isinstance(ks, bytes) and ks == b"active")
            parts.append(f"킬스위치: {'활성(거래중단)' if active else '비활성(정상)'}")
        except Exception:
            pass

        # If question mentions a stock code, include its signal
        import re
        code_match = re.search(r'\b(\d{6})\b', question)
        if code_match:
            code = code_match.group(1)
            try:
                async with self.pool.acquire() as conn:
                    sig = await conn.fetchrow(
                        "SELECT signal, strength FROM strategy_signals WHERE stock_code = $1 ORDER BY time DESC LIMIT 1", code,
                    )
                    price = await conn.fetchrow(
                        "SELECT close FROM ohlcv WHERE stock_code = $1 AND interval = '1d' ORDER BY time DESC LIMIT 1", code,
                    )
                if sig:
                    parts.append(f"{code} 시그널: {sig['signal']} (강도 {float(sig['strength']):.2f})")
                if price:
                    parts.append(f"{code} 현재가: {float(price['close']):,.0f}원")
            except Exception:
                pass

        # Current time
        from app.utils.market_calendar import KST
        now_kst = datetime.now(KST)
        parts.append(f"현재시각: {now_kst.strftime('%Y-%m-%d %H:%M KST')}")

        return "\n".join(parts) if parts else "컨텍스트 없음"

    async def send_response(self, chat_id: int | str, text: str):
        """Send response back to Telegram."""
        try:
            await self.client.post(
                f"{self._base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                },
            )
        except Exception as e:
            logger.error("Telegram send failed: %s", e)

    async def close(self):
        await self.client.aclose()
