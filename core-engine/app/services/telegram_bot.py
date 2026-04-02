"""Telegram LLM Trading Assistant — FULL CONTROL.

All trading operations, system control, data access, and AI chat
available via Telegram. Authorized chat_id only.
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
- 시스템 운영 질문 안내

규칙:
- 한국어로 답변 (영어 질문에는 영어로)
- 숫자는 구체적으로
- 불확실한 정보는 "확인 필요"라고 답변
- 투자 권유가 아닌 정보 제공임을 인지

현재 시스템 상태:
{context}"""

COMMAND_HELP = """<b>🤖 AlphaTrade Bot — 전체 명령어</b>

<b>📊 조회</b>
/status — 포트폴리오 현황
/signal &lt;종목코드&gt; — 매매 시그널
/risk — 리스크 현황 (P&L, VaR)
/market — 시장 현황 (KOSPI/KOSDAQ/환율)
/positions — 보유 종목 상세
/orders — 최근 주문 내역
/quality — 실행 품질 (슬리피지)

<b>⚡ 매매 제어</b>
/buy &lt;종목코드&gt; &lt;수량&gt; — 매수 주문
/sell &lt;종목코드&gt; &lt;수량&gt; — 매도 주문
/cycle — 매매 사이클 실행
/monitor — 포지션 모니터링 (손절/익절)

<b>🛡️ 시스템 제어</b>
/kill on — 킬 스위치 활성화
/kill off — 킬 스위치 해제
/kill — 킬 스위치 상태
/mode — 현재 매매 모드 (모의/실전)
/mode paper — 모의투자 전환
/mode live — 실전 전환 (킬스위치 필수)
/strategy — 현재 전략 확인
/strategy &lt;프리셋&gt; — 전략 변경 (ensemble, momentum, etc.)

<b>📡 데이터 수집</b>
/collect news — 뉴스 수집
/collect ohlcv — 시세 수집
/collect stocks — 종목 마스터 갱신
/collect events — 이벤트 수집 (OpenAI)
/collect index — 지수 수집

<b>🔧 시스템 관리</b>
/health — 시스템 헬스체크
/reconcile — EOD 정합성 검증
/cleanup — 미체결 주문 정리
/fills — 체결 확인 폴링
/prelaunch — 실전 전환 점검
/stress — 스트레스 테스트
/var — VaR/CVaR 계산
/walkforward &lt;종목코드&gt; — Walk-Forward 검증

<b>💬 자유 질문</b>
아무 텍스트 → AI가 실시간 데이터 기반 답변
예: "삼성전자 지금 사도 될까?"
"""


class TelegramAssistant:
    """Telegram bot with FULL trading system control."""

    def __init__(self, pool: asyncpg.Pool, redis: aioredis.Redis):
        self.pool = pool
        self.redis = redis
        self.client = httpx.AsyncClient(timeout=30)
        self._base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
        self._api = f"http://localhost:{settings.core_engine_port}"

    async def handle_message(self, message: dict) -> str | None:
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "").strip()
        if not text or not chat_id:
            return None
        if str(chat_id) != settings.telegram_chat_id:
            logger.warning("Unauthorized Telegram chat: %s", chat_id)
            return None
        if text.startswith("/"):
            return await self._handle_command(text, chat_id)
        return await self._ask_llm(text, chat_id)

    async def _handle_command(self, text: str, chat_id: int) -> str:
        cmd = text.split()[0].lower().replace("@alphatrade38_bot", "")
        args = text.split()[1:] if len(text.split()) > 1 else []

        # === 조회 ===
        if cmd in ("/help", "/start"): return COMMAND_HELP
        if cmd == "/status": return await self._cmd_status()
        if cmd == "/signal": return await self._cmd_signal(args[0] if args else "005930")
        if cmd == "/risk": return await self._cmd_risk()
        if cmd == "/market": return await self._cmd_market()
        if cmd == "/positions": return await self._cmd_positions()
        if cmd == "/orders": return await self._cmd_orders()
        if cmd == "/quality": return await self._api_get("/trading/execution-quality?days=30", "실행 품질")

        # === 매매 제어 ===
        if cmd == "/buy": return await self._cmd_order("BUY", args)
        if cmd == "/sell": return await self._cmd_order("SELL", args)
        if cmd == "/cycle": return await self._api_post("/trading/run-cycle", "매매 사이클")
        if cmd == "/monitor": return await self._api_post("/trading/monitor", "포지션 모니터링")

        # === 시스템 제어 ===
        if cmd == "/kill": return await self._cmd_kill(args)
        if cmd == "/mode": return await self._cmd_mode(args)
        if cmd == "/strategy": return await self._cmd_strategy(args)

        # === 데이터 수집 ===
        if cmd == "/collect": return await self._cmd_collect(args)

        # === 시스템 관리 ===
        if cmd == "/health": return await self._api_get("/health", "헬스체크")
        if cmd == "/reconcile": return await self._cmd_reconcile(args)
        if cmd == "/cleanup": return await self._api_post("/trading/cleanup-orders", "주문 정리")
        if cmd == "/fills": return await self._api_post("/trading/check-fills", "체결 확인")
        if cmd == "/prelaunch": return await self._api_get("/trading/pre-launch-check", "실전 점검")
        if cmd == "/stress": return await self._api_get("/risk/stress-test", "스트레스 테스트")
        if cmd == "/var": return await self._api_get("/risk/var", "VaR/CVaR")
        if cmd == "/walkforward": return await self._cmd_walkforward(args)

        return f"알 수 없는 명령어: {cmd}\n/help 로 명령어 목록을 확인하세요."

    # === 조회 명령어 ===

    async def _cmd_status(self) -> str:
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

        tv, cash = float(snap["total_value"]), float(snap["cash"])
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
            lines.append("")
            for p in positions[:10]:
                name = p["stock_name"] or p["stock_code"]
                cur = float(p["current_price"]) if p["current_price"] else float(p["avg_price"])
                pnl = ((cur - float(p["avg_price"])) / float(p["avg_price"]) * 100) if float(p["avg_price"]) > 0 else 0
                lines.append(f"  {name} {p['quantity']}주 {cur:,.0f}원 ({pnl:+.1f}%)")
        return "\n".join(lines)

    async def _cmd_signal(self, stock_code: str) -> str:
        async with self.pool.acquire() as conn:
            sig = await conn.fetchrow(
                "SELECT signal, strength, reasons FROM strategy_signals WHERE stock_code = $1 ORDER BY time DESC LIMIT 1", stock_code)
            name_row = await conn.fetchrow("SELECT stock_name FROM stocks WHERE stock_code = $1", stock_code)
            price_row = await conn.fetchrow(
                "SELECT close FROM ohlcv WHERE stock_code = $1 AND interval = '1d' ORDER BY time DESC LIMIT 1", stock_code)
        name = name_row["stock_name"] if name_row else stock_code
        price = float(price_row["close"]) if price_row else 0
        if not sig:
            return f"{name} ({stock_code}): 시그널 없음\n현재가: {price:,.0f}원"
        emoji = "🟢" if sig["signal"] == "BUY" else "🔴" if sig["signal"] == "SELL" else "⚪"
        reasons = sig["reasons"] or "[]"
        if isinstance(reasons, str):
            try: reasons = json.loads(reasons)
            except Exception: reasons = [reasons]
        lines = [f"<b>{emoji} {name} ({stock_code})</b>", f"시그널: {sig['signal']} (강도 {float(sig['strength']):.2f})", f"현재가: {price:,.0f}원"]
        for r in (reasons or [])[:5]:
            lines.append(f"  • {r}")
        return "\n".join(lines)

    async def _cmd_risk(self) -> str:
        from app.risk.realtime_pnl import compute_realtime_pnl
        pnl = await compute_realtime_pnl(pool=self.pool, redis=self.redis)
        ks = await self.redis.get("trading:kill_switch")
        active = ks in ("active", b"active")
        return "\n".join([
            "<b>🛡️ 리스크 현황</b>",
            f"총 평가금: {pnl['total_value']:,.0f}원",
            f"미실현 손익: {pnl['total_unrealized_pnl']:+,.0f}원 ({pnl['total_unrealized_pct']:+.2f}%)",
            f"일간 손익: {pnl['daily_pnl']:+,.0f}원 ({pnl['daily_return_pct']:+.2f}%)",
            f"보유 {pnl['positions_count']}종목",
            f"\n킬 스위치: {'🔴 활성' if active else '🟢 비활성'}",
        ])

    async def _cmd_market(self) -> str:
        try:
            resp = await self.client.get(f"{self._api}/index/realtime")
            data = resp.json()
            lines = ["<b>💹 시장 현황</b>"]
            for idx in data.get("indexes", []):
                emoji = "📈" if idx["change"] > 0 else "📉" if idx["change"] < 0 else "➡️"
                lines.append(f"{emoji} {idx['name']}: {idx['price']:,.2f} ({idx['change_pct']:+.2f}%)")
            return "\n".join(lines)
        except Exception as e:
            return f"시장 데이터 조회 실패: {e}"

    async def _cmd_positions(self) -> str:
        async with self.pool.acquire() as conn:
            positions = await conn.fetch(
                "SELECT pp.stock_code, s.stock_name, pp.quantity, pp.avg_price, pp.current_price "
                "FROM portfolio_positions pp LEFT JOIN stocks s ON pp.stock_code = s.stock_code "
                "WHERE pp.quantity > 0 ORDER BY pp.quantity * pp.current_price DESC"
            )
        if not positions:
            return "보유 종목이 없습니다."
        lines = ["<b>📋 보유 종목 상세</b>", ""]
        for p in positions:
            name = p["stock_name"] or p["stock_code"]
            avg = float(p["avg_price"])
            cur = float(p["current_price"]) if p["current_price"] else avg
            val = p["quantity"] * cur
            pnl = (cur - avg) / avg * 100 if avg > 0 else 0
            lines.append(f"<b>{name}</b> ({p['stock_code']})")
            lines.append(f"  {p['quantity']}주 × {cur:,.0f}원 = {val:,.0f}원")
            lines.append(f"  평균가 {avg:,.0f}원 · 손익 {pnl:+.1f}%")
            lines.append("")
        return "\n".join(lines)

    async def _cmd_orders(self) -> str:
        async with self.pool.acquire() as conn:
            orders = await conn.fetch(
                "SELECT order_id, stock_code, side, quantity, filled_qty, status, time "
                "FROM orders ORDER BY time DESC LIMIT 10"
            )
        if not orders:
            return "최근 주문이 없습니다."
        lines = ["<b>📋 최근 주문 10건</b>", ""]
        for o in orders:
            emoji = "🟢" if o["side"] == "BUY" else "🔴"
            status = o["status"]
            lines.append(f"{emoji} {o['stock_code']} {o['side']} {o['quantity']}주 → {status}")
            lines.append(f"  {o['order_id'][:12]}.. {str(o['time'])[:16]}")
        return "\n".join(lines)

    # === 매매 제어 ===

    async def _cmd_order(self, side: str, args: list) -> str:
        if len(args) < 2:
            return f"사용법: /{side.lower()} <종목코드> <수량>\n예: /{side.lower()} 005930 10"
        code, qty = args[0], args[1]
        if not code.isdigit() or len(code) != 6:
            return f"종목코드 오류: {code} (6자리 숫자)"
        try:
            qty = int(qty)
        except ValueError:
            return f"수량 오류: {qty} (정수)"
        try:
            resp = await self.client.post(f"{self._api}/order/execute", json={
                "stock_code": code, "side": side, "quantity": qty, "order_type": "MARKET",
            }, timeout=15)
            data = resp.json()
            status = data.get("status", "UNKNOWN")
            msg = data.get("message", "")
            emoji = "✅" if status == "FILLED" else "⚠️" if status in ("ACKED", "SUBMITTED") else "❌"
            return f"{emoji} <b>{side} 주문 결과</b>\n종목: {code}\n수량: {qty}주\n상태: {status}\n{msg}"
        except Exception as e:
            return f"주문 실패: {e}"

    # === 시스템 제어 ===

    async def _cmd_kill(self, args: list) -> str:
        if not args:
            ks = await self.redis.get("trading:kill_switch")
            bf = await self.redis.get("trading:broker_failures")
            active = ks in ("active", b"active")
            return f"<b>{'🔴' if active else '🟢'} 킬 스위치: {'활성' if active else '비활성'}</b>\n브로커 실패: {int(bf) if bf else 0}/{settings.risk_broker_max_failures}"

        action = args[0].lower()
        if action == "on":
            resp = await self.client.post(f"{self._api}/trading/kill-switch/activate")
            return "🔴 <b>킬 스위치 활성화</b> — 모든 신규 주문 차단"
        elif action == "off":
            resp = await self.client.post(f"{self._api}/trading/kill-switch/deactivate")
            return "🟢 <b>킬 스위치 해제</b> — 신규 주문 허용"
        return "사용법: /kill on 또는 /kill off"

    async def _cmd_mode(self, args: list) -> str:
        if not args:
            resp = await self.client.get(f"{self._api}/trading/mode")
            data = resp.json()
            mode = data.get("mode", "paper")
            return f"현재 매매 모드: <b>{'🔴 실전' if mode == 'live' else '🔵 모의투자'}</b>"

        target = args[0].lower()
        if target not in ("paper", "live"):
            return "사용법: /mode paper 또는 /mode live"
        body = {"mode": target}
        if target == "live":
            body["confirm"] = True
        resp = await self.client.post(f"{self._api}/trading/mode", json=body)
        data = resp.json()
        if data.get("error"):
            return f"⚠️ 전환 실패: {data['error']}"
        return f"✅ 매매 모드 전환: <b>{data.get('mode', target)}</b>"

    async def _cmd_strategy(self, args: list) -> str:
        if not args:
            resp = await self.client.get(f"{self._api}/strategy/active")
            data = resp.json()
            preset = data.get("preset", "?")
            weights = data.get("weights", {})
            w_str = " ".join(f"{k[:3]}:{int(v*100)}%" for k, v in weights.items())
            return f"<b>⚙️ 현재 전략: {preset}</b>\n가중치: {w_str}\n매수 임계: {data.get('buy_threshold', '?')}\n매도 임계: {data.get('sell_threshold', '?')}"

        preset = args[0].lower()
        resp = await self.client.post(f"{self._api}/strategy/active", json={"preset": preset})
        data = resp.json()
        if data.get("error"):
            return f"⚠️ 전략 변경 실패: {data['error']}"
        return f"✅ 전략 변경: <b>{preset}</b>"

    # === 데이터 수집 ===

    async def _cmd_collect(self, args: list) -> str:
        if not args:
            return "사용법: /collect news|ohlcv|stocks|events|index"
        target = args[0].lower()
        routes = {
            "news": ("/collect/news", "뉴스 수집"),
            "ohlcv": ("/collect/ohlcv", "시세 수집"),
            "stocks": ("/collect/stocks", "종목 마스터"),
            "events": ("/events/collect?period=1개월", "이벤트 수집"),
            "index": ("/collect/indexes", "지수 수집"),
        }
        if target not in routes:
            return f"알 수 없는 수집 대상: {target}\n사용 가능: {', '.join(routes.keys())}"
        path, label = routes[target]
        return await self._api_post(path, label)

    async def _cmd_reconcile(self, args: list) -> str:
        force = "force" in args
        try:
            resp = await self.client.post(f"{self._api}/trading/reconcile{'?force=true' if force else ''}", timeout=30)
            data = resp.json()
            if data.get("status") == "blocked":
                return f"⚠️ <b>장중 대사 차단</b>\n{data.get('reason', '')}\n\n강제 실행: /reconcile force"
            mismatches = data.get("mismatches", 0)
            emoji = "✅" if mismatches == 0 else "⚠️"
            return f"{emoji} <b>EOD 정합성 검증 완료</b>\n불일치: {mismatches}건"
        except Exception as e:
            return f"❌ 정합성 검증 실패: {e}"

    # === Walk-Forward ===

    async def _cmd_walkforward(self, args: list) -> str:
        code = args[0] if args else "005930"
        try:
            resp = await self.client.post(f"{self._api}/strategy/walk-forward", json={
                "stock_code": code, "initial_capital": 10000000, "strategy": "ensemble",
            }, timeout=60)
            data = resp.json()
            s = data.get("summary", {})
            return "\n".join([
                f"<b>🧪 Walk-Forward: {code}</b>",
                f"윈도우: {data.get('total_windows', 0)}개",
                f"OOS 평균 수익: {s.get('avg_oos_return_pct', 0)}%",
                f"복리 수익: {s.get('compounded_oos_return_pct', 0)}%",
                f"OOS Sharpe: {s.get('avg_oos_sharpe', 'N/A')}",
                f"일관성: {s.get('consistency_ratio', 0)}",
                f"판정: <b>{s.get('verdict', '?')}</b>",
            ])
        except Exception as e:
            return f"Walk-Forward 실패: {e}"

    # === API 호출 헬퍼 ===

    async def _api_get(self, path: str, label: str) -> str:
        try:
            resp = await self.client.get(f"{self._api}{path}", timeout=30)
            data = resp.json()
            return f"<b>📡 {label}</b>\n<pre>{json.dumps(data, ensure_ascii=False, indent=2)[:3500]}</pre>"
        except Exception as e:
            return f"{label} 실패: {e}"

    async def _api_post(self, path: str, label: str) -> str:
        try:
            resp = await self.client.post(f"{self._api}{path}", timeout=30)
            data = resp.json()
            # Compact summary
            status = data.get("status", "")
            summary_parts = []
            for key in ("inserted", "updated", "duplicates", "errors", "mismatches", "checked", "expired"):
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        val = len(val)
                    summary_parts.append(f"{key}={val}")
            summary = ", ".join(summary_parts) if summary_parts else json.dumps(data, ensure_ascii=False)[:500]
            return f"<b>✅ {label}</b>\n상태: {status}\n{summary}"
        except Exception as e:
            return f"{label} 실패: {e}"

    # === LLM 질문 ===

    async def _ask_llm(self, question: str, chat_id: int) -> str:
        if not settings.openai_api_key and not settings.anthropic_api_key:
            return "LLM API 키가 설정되지 않았습니다."
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
        resp = await self.client.post("https://api.openai.com/v1/chat/completions", headers={
            "Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json",
        }, json={
            "model": "gpt-4o-mini", "max_tokens": 1000,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT.format(context=context)}, {"role": "user", "content": question}],
        }, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def _call_claude(self, question: str, context: str) -> str:
        resp = await self.client.post("https://api.anthropic.com/v1/messages", headers={
            "x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json",
        }, json={
            "model": "claude-haiku-4-5-20251001", "max_tokens": 1000,
            "system": SYSTEM_PROMPT.format(context=context),
            "messages": [{"role": "user", "content": question}],
        }, timeout=30)
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    async def _build_context(self, question: str) -> str:
        parts = []
        try:
            async with self.pool.acquire() as conn:
                snap = await conn.fetchrow("SELECT total_value, cash, daily_pnl, positions_count FROM portfolio_snapshots ORDER BY time DESC LIMIT 1")
            if snap:
                parts.append(f"포트폴리오: 총 {float(snap['total_value']):,.0f}원, 현금 {float(snap['cash']):,.0f}원, 일간 {float(snap['daily_pnl'] or 0):+,.0f}원, {snap['positions_count']}종목")
        except Exception: pass

        try:
            ks = await self.redis.get("trading:kill_switch")
            parts.append(f"킬스위치: {'활성' if ks in ('active', b'active') else '비활성'}")
        except Exception: pass

        import re
        code_match = re.search(r'\b(\d{6})\b', question)
        if code_match:
            code = code_match.group(1)
            try:
                async with self.pool.acquire() as conn:
                    sig = await conn.fetchrow("SELECT signal, strength FROM strategy_signals WHERE stock_code = $1 ORDER BY time DESC LIMIT 1", code)
                    price = await conn.fetchrow("SELECT close FROM ohlcv WHERE stock_code = $1 AND interval = '1d' ORDER BY time DESC LIMIT 1", code)
                if sig: parts.append(f"{code} 시그널: {sig['signal']} (강도 {float(sig['strength']):.2f})")
                if price: parts.append(f"{code} 현재가: {float(price['close']):,.0f}원")
            except Exception: pass

        from app.utils.market_calendar import KST
        parts.append(f"현재시각: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
        return "\n".join(parts) if parts else "컨텍스트 없음"

    async def send_response(self, chat_id: int | str, text: str):
        try:
            await self.client.post(f"{self._base_url}/sendMessage", json={
                "chat_id": chat_id, "text": text, "parse_mode": "HTML",
            })
        except Exception as e:
            logger.error("Telegram send failed: %s", e)

    async def close(self):
        await self.client.aclose()
