"""LLM Chat API — Direct chat with AI trading assistant.

Provides the same trading-context-aware assistant as the Telegram bot,
but via REST API for the dashboard UI.
"""

import logging
from datetime import datetime, timezone

import asyncpg
import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import settings
from app.deps import get_db, get_redis

logger = logging.getLogger(__name__)

router = APIRouter()

SYSTEM_PROMPT = """당신은 AlphaTrade AI 트레이딩 어시스턴트입니다.
한국 주식시장(KOSPI/KOSDAQ) 자동매매 시스템의 운영을 돕습니다.

역할:
- 종목 분석 질문에 실시간 데이터 기반으로 답변
- 매매 판단 보조 (최종 결정은 사용자 몫임을 명시)
- 포트폴리오 현황/리스크 설명
- 시스템 운영 질문 안내

도구 (필요할 때만 사용):
아래 도구를 호출하려면 답변에 정확히 이 형식을 포함하세요. 한 답변에 여러 도구를 사용할 수 있습니다.

[TOOL:kis_price:종목코드] — KIS 실시간 시세 조회 (예: [TOOL:kis_price:005930])
[TOOL:backtest:종목코드:전략:기간] — 백테스트 실행 (예: [TOOL:backtest:005930:ensemble:1Y])
  전략: ensemble, momentum, mean_reversion, conservative, aggressive
  기간: 3M, 6M, 1Y, 2Y, 3Y, 5Y, MAX
[TOOL:signal:종목코드] — 최신 매매 시그널 조회 (예: [TOOL:signal:005930])
[TOOL:news:종목코드] — 관련 뉴스 조회 (예: [TOOL:news:005930])
[TOOL:ohlcv_monthly:종목코드:기간] — 월별 종가/수익률 데이터 조회 (예: [TOOL:ohlcv_monthly:005930:1Y])
  기간: 3M, 6M, 1Y, 2Y, 3Y, 5Y, MAX
[TOOL:ohlcv_daily:종목코드:기간] — 일별 OHLCV 데이터 조회 (예: [TOOL:ohlcv_daily:005930:1M])

도구를 호출하면 시스템이 결과를 제공합니다. 결과를 받은 후 사용자에게 분석해서 답변하세요.
도구 호출 태그는 최종 답변에 포함하지 마세요 — 시스템이 자동 처리합니다.

규칙:
- 한국어로 답변 (영어 질문에는 영어로)
- 숫자는 구체적으로
- 아래 "현재 시스템 상태"에 포함된 뉴스, 시장 이벤트, 웹 검색 결과를 적극 활용하여 답변
- 출처가 있으면 명시 (예: "뉴스에 따르면...", "웹 검색 결과...")
- DB 기준 데이터는 날짜를 명시하고, 실시간 아님을 안내
- 불확실한 정보는 "확인 필요"라고 답변
- 투자 권유가 아닌 정보 제공임을 인지
- 마크다운 포맷 사용 가능

현재 시스템 상태:
{context}"""


# --- Models ---

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    image: str | None = None  # base64-encoded image (data:image/png;base64,...)


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    timestamp: str


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    model: str
    context_summary: str


# --- Context builder ---

async def _get_realtime_price(redis: aioredis.Redis, code: str) -> dict | None:
    """Get real-time price from Redis market state cache (updated every 60s by poller)."""
    try:
        data = await redis.hgetall(f"market:state:{code}")
        if data and data.get(b"price") or data.get("price"):
            # Redis returns bytes or str depending on decode_responses
            def _v(key):
                val = data.get(key.encode()) or data.get(key)
                return float(val) if val else 0.0
            return {
                "price": _v("price"),
                "change_pct": _v("change_pct"),
                "change": _v("change"),
                "volume": int(_v("volume")),
                "updated_at": (data.get(b"updated_at") or data.get("updated_at", b"")).decode() if isinstance(data.get(b"updated_at", ""), bytes) else str(data.get("updated_at", "")),
            }
    except Exception:
        pass
    return None


async def build_context(question: str, pool: asyncpg.Pool, redis: aioredis.Redis) -> str:
    parts = []

    # 1. Portfolio (DB snapshot + live positions)
    try:
        async with pool.acquire() as conn:
            snap = await conn.fetchrow(
                "SELECT total_value, cash, daily_pnl, positions_count "
                "FROM portfolio_snapshots ORDER BY time DESC LIMIT 1"
            )
            positions = await conn.fetch(
                "SELECT p.stock_code, s.stock_name, p.quantity, p.avg_price "
                "FROM portfolio_positions p "
                "LEFT JOIN stocks s ON p.stock_code = s.stock_code "
                "WHERE p.quantity > 0"
            )
        if snap:
            parts.append(
                f"포트폴리오: 총 {float(snap['total_value']):,.0f}원, "
                f"현금 {float(snap['cash']):,.0f}원, "
                f"일간 {float(snap['daily_pnl'] or 0):+,.0f}원, "
                f"{snap['positions_count']}종목"
            )
        if positions:
            parts.append("보유 종목:")
            for pos in positions:
                rt = await _get_realtime_price(redis, pos["stock_code"])
                cur_price = rt["price"] if rt else 0
                avg = float(pos["avg_price"])
                pnl_pct = round((cur_price / avg - 1) * 100, 2) if avg > 0 and cur_price > 0 else 0
                parts.append(
                    f"  {pos['stock_name'] or pos['stock_code']}({pos['stock_code']}) "
                    f"{pos['quantity']}주, 평단 {avg:,.0f}원, "
                    f"현재 {cur_price:,.0f}원 ({pnl_pct:+.1f}%)"
                )
        elif snap and snap["positions_count"] == 0:
            parts.append("보유 종목: 없음")
    except Exception:
        pass

    # 2. System state
    try:
        ks = await redis.get("trading:kill_switch")
        mode = await redis.get("trading:mode")
        mode_str = (mode.decode() if isinstance(mode, bytes) else mode) if mode else "paper"
        ks_str = "활성" if ks in ("active", b"active") else "비활성"
        parts.append(f"시스템: {mode_str} 모드, 킬스위치 {ks_str}")
    except Exception:
        pass

    # 3. Extract ALL stock codes from question and provide real-time data
    import re
    codes = re.findall(r'\b(\d{6})\b', question)
    # Also try to match stock names
    try:
        name_matches = re.findall(r'[가-힣]{2,10}', question)
        if name_matches:
            async with pool.acquire() as conn:
                for nm in name_matches[:3]:
                    row = await conn.fetchrow(
                        "SELECT stock_code, stock_name FROM stocks WHERE stock_name LIKE $1 LIMIT 1",
                        f"%{nm}%",
                    )
                    if row and row["stock_code"] not in codes:
                        codes.append(row["stock_code"])
    except Exception:
        pass

    for code in dict.fromkeys(codes):  # dedupe, preserve order
        try:
            async with pool.acquire() as conn:
                name = await conn.fetchrow("SELECT stock_name FROM stocks WHERE stock_code = $1", code)
                sig = await conn.fetchrow(
                    "SELECT signal, strength FROM strategy_signals "
                    "WHERE stock_code = $1 ORDER BY time DESC LIMIT 1", code
                )
            rt = await _get_realtime_price(redis, code)
            label = f"{name['stock_name']}({code})" if name else code
            if rt and rt["price"] > 0:
                parts.append(
                    f"{label}: 실시간 {rt['price']:,.0f}원 ({rt['change_pct']:+.2f}%), "
                    f"거래량 {rt['volume']:,}"
                )
            else:
                # Fallback 1: KIS API live quote
                kis_ok = False
                try:
                    from app.services.kis_api import KISClient
                    kis = KISClient()
                    kis_price = await kis.get_current_price(code)
                    await kis.close()
                    if kis_price and kis_price.price > 0:
                        parts.append(
                            f"{label}: {kis_price.price:,.0f}원 (KIS 실시간 조회)"
                        )
                        kis_ok = True
                except Exception:
                    pass
                # Fallback 2: DB OHLCV (with staleness warning)
                if not kis_ok:
                    async with pool.acquire() as conn:
                        recent = await conn.fetch(
                            "SELECT close, volume, time FROM ohlcv WHERE stock_code = $1 AND interval = '1d' "
                            "ORDER BY time DESC LIMIT 2", code
                        )
                    if recent:
                        cur = float(recent[0]['close'])
                        prev = float(recent[1]['close']) if len(recent) > 1 else cur
                        chg = round((cur / prev - 1) * 100, 2) if prev > 0 else 0
                        vol = int(recent[0]['volume']) if recent[0]['volume'] else 0
                        dt = str(recent[0]['time'])[:10]
                        parts.append(f"{label}: {cur:,.0f}원 ({chg:+.1f}%), 거래량 {vol:,} ⚠ DB 기준 {dt}, 실시간 아님")
            if sig:
                parts.append(f"  시그널: {sig['signal']} (강도 {float(sig['strength']):.2f})")
        except Exception:
            pass

    # 4. Market overview (top movers from Redis)
    try:
        async with pool.acquire() as conn:
            top_stocks = await conn.fetch(
                "SELECT s.stock_code, s.stock_name FROM stocks s "
                "JOIN universe u ON s.stock_code = u.stock_code "
                "WHERE u.is_active = TRUE LIMIT 5"
            )
        market_lines = []
        for s in top_stocks:
            rt = await _get_realtime_price(redis, s["stock_code"])
            if rt and rt["price"] > 0:
                market_lines.append(f"{s['stock_name']} {rt['price']:,.0f}원({rt['change_pct']:+.1f}%)")
            else:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT close FROM ohlcv WHERE stock_code = $1 AND interval = '1d' ORDER BY time DESC LIMIT 1",
                        s["stock_code"],
                    )
                if row:
                    market_lines.append(f"{s['stock_name']} {float(row['close']):,.0f}원")
        if market_lines:
            parts.append(f"주요 종목: {', '.join(market_lines)}")
    except Exception:
        pass

    # 5. RAG — 관련 뉴스 검색 (DB)
    try:
        news_results = await _rag_search_news(pool, question, codes)
        if news_results:
            parts.append("관련 뉴스:")
            for n in news_results:
                parts.append(f"  [{n['date']}] {n['title']}")
                if n.get("summary"):
                    parts.append(f"    {n['summary']}")
    except Exception:
        pass

    # 6. RAG — 시장 이벤트 검색 (DB)
    try:
        events = await _rag_search_events(pool, question)
        if events:
            parts.append("관련 시장 이벤트:")
            for ev in events:
                parts.append(f"  [{ev['date']}] {ev['label']} ({ev['category']}, 중요도 {ev['importance']})")
                if ev.get("description"):
                    parts.append(f"    {ev['description'][:100]}")
    except Exception:
        pass

    # 7. RAG — 웹 검색 (실시간)
    try:
        web_results = await _rag_web_search(question)
        if web_results:
            parts.append("웹 검색 결과:")
            for w in web_results:
                parts.append(f"  • {w['title']}")
                if w.get("snippet"):
                    parts.append(f"    {w['snippet'][:120]}")
    except Exception:
        pass

    from app.utils.market_calendar import KST
    parts.append(f"현재시각: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    context = "\n".join(parts) if parts else "컨텍스트 없음"
    # Limit context to ~6000 chars to avoid token overflow
    if len(context) > 6000:
        context = context[:6000] + "\n... (컨텍스트 일부 생략)"
    return context


# --- RAG retrieval functions ---

async def _rag_search_news(pool: asyncpg.Pool, question: str, stock_codes: list[str]) -> list[dict]:
    """Search relevant news from DB using stock codes + keyword matching."""
    results = []
    async with pool.acquire() as conn:
        # 1. By stock codes (if any mentioned)
        if stock_codes:
            rows = await conn.fetch(
                "SELECT title, content, time, source FROM news "
                "WHERE stock_codes && $1::varchar[] "
                "ORDER BY time DESC LIMIT 5",
                stock_codes,
            )
            for r in rows:
                results.append({
                    "date": str(r["time"])[:10],
                    "title": r["title"][:80],
                    "summary": (r["content"] or "")[:100],
                })

        # 2. Keyword search in titles (extract Korean nouns from question)
        import re
        keywords = [w for w in re.findall(r'[가-힣]{2,}', question) if len(w) >= 2]
        if keywords and len(results) < 5:
            for kw in keywords[:3]:
                rows = await conn.fetch(
                    "SELECT title, content, time FROM news "
                    "WHERE title LIKE $1 "
                    "ORDER BY time DESC LIMIT 3",
                    f"%{kw}%",
                )
                seen = {r["title"] for r in results}
                for r in rows:
                    if r["title"][:80] not in seen:
                        results.append({
                            "date": str(r["time"])[:10],
                            "title": r["title"][:80],
                            "summary": (r["content"] or "")[:100],
                        })
                        seen.add(r["title"][:80])

        # 3. Recent general news (always include some)
        if len(results) < 3:
            rows = await conn.fetch(
                "SELECT title, time FROM news ORDER BY time DESC LIMIT 3"
            )
            seen = {r["title"] for r in results}
            for r in rows:
                if r["title"][:80] not in seen:
                    results.append({"date": str(r["time"])[:10], "title": r["title"][:80]})

    return results[:8]


async def _rag_search_events(pool: asyncpg.Pool, question: str) -> list[dict]:
    """Search relevant market events from DB."""
    async with pool.acquire() as conn:
        # Recent high-importance events
        rows = await conn.fetch(
            "SELECT date, label, category, description, importance "
            "FROM market_events "
            "WHERE importance >= 3 "
            "ORDER BY date DESC LIMIT 5"
        )

        # Also search by keyword
        import re
        keywords = re.findall(r'[가-힣a-zA-Z]{2,}', question)
        for kw in keywords[:2]:
            extra = await conn.fetch(
                "SELECT date, label, category, description, importance "
                "FROM market_events "
                "WHERE label LIKE $1 OR description LIKE $1 "
                "ORDER BY importance DESC, date DESC LIMIT 3",
                f"%{kw}%",
            )
            rows = list(rows) + list(extra)

    seen = set()
    results = []
    for r in rows:
        key = f"{r['date']}:{r['label']}"
        if key not in seen:
            seen.add(key)
            results.append({
                "date": str(r["date"]),
                "label": r["label"],
                "category": r["category"],
                "description": r["description"][:150] if r["description"] else "",
                "importance": r["importance"],
            })
    return results[:5]


async def _rag_web_search(question: str) -> list[dict]:
    """Search the web for real-time information related to the question.

    Uses Google Custom Search or DuckDuckGo as fallback.
    """
    # Extract search query: use Korean keywords + "주식" or "증시"
    import re
    keywords = re.findall(r'[가-힣a-zA-Z0-9]{2,}', question)
    if not keywords:
        return []
    query = " ".join(keywords[:5]) + " 주식 증시"

    results = []
    try:
        # DuckDuckGo HTML search (no API key needed)
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query, "kl": "kr-kr"},
                headers={"User-Agent": "Mozilla/5.0 (compatible; AlphaTrade/1.0)"},
            )
            resp.raise_for_status()
            # Parse results from HTML
            from html.parser import HTMLParser

            class DDGParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.results: list[dict] = []
                    self._in_result = False
                    self._in_snippet = False
                    self._current: dict = {}

                def handle_starttag(self, tag, attrs):
                    d = dict(attrs)
                    if tag == "a" and "result__a" in d.get("class", ""):
                        self._in_result = True
                        self._current = {"title": "", "url": d.get("href", ""), "snippet": ""}
                    if tag == "a" and "result__snippet" in d.get("class", ""):
                        self._in_snippet = True

                def handle_endtag(self, tag):
                    if tag == "a" and self._in_result:
                        self._in_result = False
                    if tag == "a" and self._in_snippet:
                        self._in_snippet = False
                        if self._current:
                            self.results.append(self._current)
                            self._current = {}

                def handle_data(self, data):
                    if self._in_result and self._current:
                        self._current["title"] += data.strip()
                    if self._in_snippet and self._current:
                        self._current["snippet"] += data.strip()

            parser = DDGParser()
            parser.feed(resp.text)
            results = parser.results[:5]
    except Exception as exc:
        logger.debug("Web search failed: %s", exc)

    return results


# --- Chat history (Redis-backed, per session) ---

async def get_history(redis: aioredis.Redis, session_id: str, limit: int = 20) -> list[dict]:
    import json
    key = f"llm:chat:{session_id}"
    raw = await redis.lrange(key, 0, limit - 1)
    return [json.loads(m) for m in reversed(raw)]


async def _execute_tools(
    tool_calls: list[tuple[str, str]],
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
) -> list[tuple[str, str]]:
    """Execute tool calls and return (tool_name, result_text) pairs."""
    results = []
    for tool_name, args_str in tool_calls:
        args = args_str.split(":")
        try:
            if tool_name == "kis_price":
                result = await _tool_kis_price(args[0], redis, pool)
            elif tool_name == "backtest":
                result = await _tool_backtest(args, pool)
            elif tool_name == "signal":
                result = await _tool_signal(args[0], pool)
            elif tool_name == "news":
                result = await _tool_news(args[0], pool)
            elif tool_name == "ohlcv_monthly":
                result = await _tool_ohlcv_monthly(args, pool)
            elif tool_name == "ohlcv_daily":
                result = await _tool_ohlcv_daily(args, pool)
            else:
                result = f"알 수 없는 도구: {tool_name}"
        except Exception as e:
            result = f"도구 실행 실패: {e}"
        results.append((tool_name, result))
    return results


async def _tool_kis_price(code: str, redis: aioredis.Redis, pool: asyncpg.Pool) -> str:
    """KIS 실시간 시세 조회."""
    rt = await _get_realtime_price(redis, code)
    if rt and rt["price"] > 0:
        return (
            f"종목: {code}\n"
            f"현재가: {rt['price']:,.0f}원\n"
            f"등락률: {rt['change_pct']:+.2f}%\n"
            f"거래량: {rt['volume']:,}\n"
            f"출처: 실시간 (Redis 캐시)"
        )
    # KIS API fallback
    try:
        from app.services.kis_api import KISClient
        kis = KISClient()
        price_data = await kis.get_current_price(code)
        await kis.close()
        if price_data and price_data.price > 0:
            return (
                f"종목: {code}\n"
                f"현재가: {price_data.price:,.0f}원\n"
                f"시가: {price_data.open:,.0f}원\n"
                f"고가: {price_data.high:,.0f}원\n"
                f"저가: {price_data.low:,.0f}원\n"
                f"거래량: {price_data.volume:,}\n"
                f"출처: KIS API 실시간"
            )
    except Exception:
        pass
    # DB fallback
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT close, volume, time FROM ohlcv WHERE stock_code = $1 AND interval = '1d' ORDER BY time DESC LIMIT 1",
            code,
        )
    if row:
        return f"종목: {code}\n종가: {float(row['close']):,.0f}원\n거래량: {int(row['volume']):,}\n기준일: {str(row['time'])[:10]}\n⚠ DB 기준, 실시간 아님"
    return f"종목 {code}의 시세를 찾을 수 없습니다."


async def _tool_backtest(args: list[str], pool: asyncpg.Pool) -> str:
    """백테스트 실행."""
    code = args[0] if args else "005930"
    strategy = args[1] if len(args) > 1 else "ensemble"
    duration = args[2] if len(args) > 2 else "1Y"

    # Calculate start_date from duration
    from datetime import timedelta
    duration_map = {"3M": 90, "6M": 180, "1Y": 365, "2Y": 730, "3Y": 1095, "5Y": 1825, "MAX": 3650}
    days = duration_map.get(duration, 365)
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    from app.strategy.backtest import run_backtest
    result = await run_backtest(
        stock_code=code,
        strategy=strategy,
        initial_capital=10_000_000,
        start_date=start,
        benchmark="buy_and_hold",
        pool=pool,
    )

    warns = ""
    if result.statistical_warnings:
        warns = "\n⚠ " + " / ".join(result.statistical_warnings)

    return (
        f"백테스트 결과 ({code}, {strategy}, {duration})\n"
        f"기간: {result.period_bars}봉\n"
        f"총 수익률: {result.total_return:+.2f}%\n"
        f"벤치마크(B&H): {result.benchmark_return or 0:.2f}%\n"
        f"최대 낙폭(MDD): {result.max_drawdown:.2f}%\n"
        f"샤프 비율: {result.sharpe_ratio or 0:.4f}\n"
        f"승률: {result.win_rate:.1f}%\n"
        f"총 거래: {result.total_trades}건\n"
        f"연간 수익률: {result.annual_return or 0:.2f}%\n"
        f"초기자본: 1,000만원 → 최종: {result.final_capital:,.0f}원"
        f"{warns}"
    )


async def _tool_signal(code: str, pool: asyncpg.Pool) -> str:
    """최신 매매 시그널 조회."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT signal, strength, strategy_name, reasons, time "
            "FROM strategy_signals WHERE stock_code = $1 ORDER BY time DESC LIMIT 1",
            code,
        )
    if not row:
        return f"종목 {code}의 시그널이 없습니다."

    reasons_str = ""
    if row["reasons"]:
        import json
        try:
            reasons = json.loads(row["reasons"]) if isinstance(row["reasons"], str) else row["reasons"]
            if isinstance(reasons, dict):
                reasons_str = "\n  " + "\n  ".join(f"{k}: {v}" for k, v in reasons.items())
            elif isinstance(reasons, list):
                reasons_str = "\n  " + "\n  ".join(str(r) for r in reasons[:5])
        except Exception:
            pass

    return (
        f"종목: {code}\n"
        f"시그널: {row['signal']}\n"
        f"강도: {float(row['strength']):.4f}\n"
        f"전략: {row['strategy_name']}\n"
        f"시점: {str(row['time'])[:19]}"
        f"{reasons_str}"
    )


async def _tool_news(code: str, pool: asyncpg.Pool) -> str:
    """관련 뉴스 조회."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT title, time, source FROM news "
            "WHERE $1 = ANY(stock_codes) ORDER BY time DESC LIMIT 8",
            code,
        )
    if not rows:
        # Fallback: recent general news
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT title, time, source FROM news ORDER BY time DESC LIMIT 5")

    if not rows:
        return f"종목 {code} 관련 뉴스가 없습니다."

    lines = [f"종목 {code} 관련 뉴스 ({len(rows)}건):"]
    for r in rows:
        lines.append(f"  [{str(r['time'])[:10]}] {r['title'][:70]} ({r['source']})")
    return "\n".join(lines)


async def _tool_ohlcv_monthly(args: list[str], pool: asyncpg.Pool) -> str:
    """월별 종가 + Buy & Hold 수익률 테이블."""
    code = args[0] if args else "005930"
    duration = args[1] if len(args) > 1 else "1Y"
    duration_map = {"3M": 90, "6M": 180, "1Y": 365, "2Y": 730, "3Y": 1095, "5Y": 1825, "MAX": 3650}
    days = duration_map.get(duration, 365)

    from datetime import timedelta
    start_dt = datetime.now(timezone.utc) - timedelta(days=days)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DATE_TRUNC('month', time) as month,
                   (array_agg(close ORDER BY time DESC))[1] as month_close,
                   (array_agg(volume ORDER BY time DESC))[1] as month_volume
            FROM ohlcv
            WHERE stock_code = $1 AND interval = '1d'
              AND time >= $2
            GROUP BY DATE_TRUNC('month', time)
            ORDER BY month ASC
            """,
            code, start_dt,
        )
        name_row = await conn.fetchrow("SELECT stock_name FROM stocks WHERE stock_code = $1", code)

    if not rows:
        return f"종목 {code}의 월별 데이터가 없습니다."

    label = f"{name_row['stock_name']}({code})" if name_row else code
    lines = [f"{label} 월별 Buy & Hold 성과 ({duration})", ""]
    lines.append(f"{'월':10s} {'월말 종가':>12s} {'월간 수익률':>10s} {'누적 수익률':>10s}")
    lines.append("-" * 46)

    base_price = float(rows[0]["month_close"])
    prev_close = base_price
    for r in rows:
        month_str = r["month"].strftime("%Y-%m")
        close = float(r["month_close"])
        monthly_ret = round((close / prev_close - 1) * 100, 2) if prev_close > 0 else 0
        cumul_ret = round((close / base_price - 1) * 100, 2) if base_price > 0 else 0
        lines.append(f"{month_str:10s} {close:>12,.0f} {monthly_ret:>+9.2f}% {cumul_ret:>+9.2f}%")
        prev_close = close

    final = float(rows[-1]["month_close"])
    total_ret = round((final / base_price - 1) * 100, 2)
    lines.append("-" * 46)
    lines.append(f"{'합계':10s} {'':>12s} {'':>10s} {total_ret:>+9.2f}%")
    lines.append(f"\n시작가: {base_price:,.0f}원 → 최종가: {final:,.0f}원")

    return "\n".join(lines)


async def _tool_ohlcv_daily(args: list[str], pool: asyncpg.Pool) -> str:
    """일별 OHLCV 데이터 조회."""
    code = args[0] if args else "005930"
    duration = args[1] if len(args) > 1 else "1M"
    duration_map = {"1W": 7, "2W": 14, "1M": 30, "3M": 90, "6M": 180, "1Y": 365}
    days = duration_map.get(duration, 30)

    from datetime import timedelta
    start_dt = datetime.now(timezone.utc) - timedelta(days=days)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT time, open, high, low, close, volume FROM ohlcv "
            "WHERE stock_code = $1 AND interval = '1d' AND time >= $2 "
            "ORDER BY time ASC",
            code, start_dt,
        )
        name_row = await conn.fetchrow("SELECT stock_name FROM stocks WHERE stock_code = $1", code)

    if not rows:
        return f"종목 {code}의 일별 데이터가 없습니다."

    label = f"{name_row['stock_name']}({code})" if name_row else code
    lines = [f"{label} 일별 OHLCV ({duration}, {len(rows)}일)", ""]
    lines.append(f"{'날짜':12s} {'시가':>10s} {'고가':>10s} {'저가':>10s} {'종가':>10s} {'거래량':>12s}")
    lines.append("-" * 68)

    for r in rows[-30:]:  # limit to 30 rows for readability
        dt = str(r["time"])[:10]
        lines.append(
            f"{dt:12s} {float(r['open']):>10,.0f} {float(r['high']):>10,.0f} "
            f"{float(r['low']):>10,.0f} {float(r['close']):>10,.0f} {int(r['volume']):>12,}"
        )

    if len(rows) > 30:
        lines.append(f"  ... ({len(rows) - 30}일 추가 생략)")

    return "\n".join(lines)


async def _ensure_chat_table(pool: asyncpg.Pool):
    """Create chat_history table if not exists (for persistent conversation logs)."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id SERIAL,
                time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                model TEXT,
                has_image BOOLEAN DEFAULT FALSE
            )
        """)
        # Create index only if not exists
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_history(session_id, time DESC)
        """)


async def save_to_db(pool: asyncpg.Pool, session_id: str, role: str, content: str, model: str | None = None, has_image: bool = False):
    """Persist chat message to DB for permanent history."""
    try:
        await _ensure_chat_table(pool)
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO chat_history (session_id, role, content, model, has_image) VALUES ($1, $2, $3, $4, $5)",
                session_id, role, content[:5000], model, has_image,
            )
    except Exception as e:
        logger.debug("Chat DB save failed: %s", e)


async def append_history(redis: aioredis.Redis, session_id: str, role: str, content: str):
    import json
    key = f"llm:chat:{session_id}"
    msg = json.dumps({"role": role, "content": content, "ts": datetime.now(timezone.utc).isoformat()})
    await redis.rpush(key, msg)
    await redis.ltrim(key, -50, -1)  # keep last 50 messages
    await redis.expire(key, 86400 * 7)  # 7 day TTL


# --- Runtime settings helpers ---

async def get_runtime_setting(pool: asyncpg.Pool, key: str) -> str | None:
    """Get a runtime setting from DB, returns None if table/key doesn't exist."""
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM runtime_settings WHERE key = $1", key
            )
            return row["value"] if row else None
    except Exception:
        return None


async def get_api_key(pool: asyncpg.Pool, provider: str) -> str:
    """Get LLM API key: prefer runtime_settings DB, fallback to env."""
    db_key = await get_runtime_setting(pool, f"{provider}_api_key")
    if db_key:
        return db_key
    return getattr(settings, f"{provider}_api_key", "")


async def get_model(pool: asyncpg.Pool, provider: str) -> str:
    """Get model name from runtime settings or default."""
    db_model = await get_runtime_setting(pool, f"{provider}_model")
    if db_model:
        return db_model
    defaults = {"anthropic": "claude-opus-4-6", "openai": "gpt-5.4"}
    return defaults.get(provider, "")


# --- LLM Callers ---

async def call_claude(messages: list[dict], system: str, api_key: str, model: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 4000,
                "system": system,
                "messages": messages,
            },
            timeout=settings.http_timeout_llm,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]


_OPENAI_RESPONSES_MODELS = {"gpt-5.4", "gpt-5.4-pro", "gpt-5.4-mini", "gpt-5.4-nano"}


def _build_vision_content(text: str, image_data: str, provider: str):
    """Build multimodal content for vision-capable LLMs.

    image_data: "data:image/png;base64,iVBOR..." or raw base64 string.
    """
    # Extract media type and base64
    if image_data.startswith("data:"):
        # data:image/png;base64,iVBOR...
        header, b64 = image_data.split(",", 1)
        media_type = header.split(":")[1].split(";")[0]  # e.g. image/png
    else:
        b64 = image_data
        media_type = "image/png"

    if provider == "anthropic":
        return [
            {"type": "text", "text": text},
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
        ]
    else:
        # OpenAI vision format (works for both Chat Completions and Responses API)
        return [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
        ]


_OPENAI_FALLBACK_CHAIN = ["gpt-5.4", "gpt-4.1", "gpt-4o-mini"]


async def call_openai(messages: list[dict], system: str, api_key: str, model: str) -> str:
    import asyncio as _aio

    # Build fallback chain: requested model first, then fallbacks
    models_to_try = [model] + [m for m in _OPENAI_FALLBACK_CHAIN if m != model]

    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        last_error = None

        for attempt_model in models_to_try:
            for retry in range(2):  # 1 retry per model
                try:
                    if attempt_model in _OPENAI_RESPONSES_MODELS:
                        input_parts = [{"role": "developer", "content": system}]
                        input_parts.extend(messages)
                        resp = await client.post(
                            "https://api.openai.com/v1/responses",
                            headers=headers,
                            json={"model": attempt_model, "input": input_parts},
                            timeout=settings.http_timeout_llm,
                        )
                    else:
                        full_messages = [{"role": "system", "content": system}] + messages
                        resp = await client.post(
                            "https://api.openai.com/v1/chat/completions",
                            headers=headers,
                            json={"model": attempt_model, "max_tokens": 4000, "messages": full_messages},
                            timeout=settings.http_timeout_llm,
                        )

                    if resp.status_code == 429:
                        wait = int(resp.headers.get("retry-after", "3"))
                        logger.warning("OpenAI 429 on %s, waiting %ds (retry %d)", attempt_model, wait, retry)
                        await _aio.sleep(min(wait, 10))
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
                        await _aio.sleep(3)
                        continue
                    break  # non-429 error → try next model
                except Exception as e:
                    last_error = e
                    break

            # This model exhausted retries, try next
            logger.warning("OpenAI model %s failed, trying next fallback", attempt_model)

        # All models failed
        raise last_error or Exception("All OpenAI models failed")


# --- Endpoints ---

@router.post("/chat", response_model=ChatResponse)
async def api_chat(
    req: ChatRequest,
    pool: asyncpg.Pool = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Send a message to the AI trading assistant."""
    # Determine provider
    provider = await get_runtime_setting(pool, "llm_provider") or ""
    anthropic_key = await get_api_key(pool, "anthropic")
    openai_key = await get_api_key(pool, "openai")

    if not provider:
        provider = "anthropic" if anthropic_key else ("openai" if openai_key else "")
    if not provider or (provider == "anthropic" and not anthropic_key) or (provider == "openai" and not openai_key):
        return ChatResponse(
            reply="LLM API 키가 설정되지 않았습니다. 설정 페이지에서 API 키를 입력해주세요.",
            session_id=req.session_id,
            model="none",
            context_summary="API 키 미설정",
        )

    api_key = anthropic_key if provider == "anthropic" else openai_key
    model = await get_model(pool, provider)

    # Build context
    context = await build_context(req.message, pool, redis)
    system = SYSTEM_PROMPT.format(context=context)

    # Get history + append user message
    history = await get_history(redis, req.session_id)
    await append_history(redis, req.session_id, "user", req.message)
    await save_to_db(pool, req.session_id, "user", req.message, has_image=bool(req.image))

    # Build messages for API (include recent history)
    api_messages = []
    for h in history[-10:]:  # last 10 messages for context
        api_messages.append({"role": h["role"], "content": h["content"]})
    # Build user message (text + optional image)
    if req.image:
        user_content = _build_vision_content(req.message, req.image, provider)
    else:
        user_content = req.message
    api_messages.append({"role": "user", "content": user_content})

    try:
        if provider == "anthropic":
            reply = await call_claude(api_messages, system, api_key, model)
        else:
            reply = await call_openai(api_messages, system, api_key, model)

        # Tool execution: if LLM included [TOOL:...] calls, execute and re-prompt
        import re as _re
        tool_pattern = r'\[TOOL:([a-z_]+):([^\]]+)\]'
        tool_matches = _re.findall(tool_pattern, reply)
        if tool_matches:
            tool_results = await _execute_tools(tool_matches, pool, redis)
            # Strip tool tags from first reply, append results, re-prompt
            clean_reply = _re.sub(tool_pattern, '', reply).strip()
            tool_context = "\n".join(f"[도구 결과: {name}]\n{result}" for name, result in tool_results)
            followup_messages = api_messages + [
                {"role": "assistant", "content": clean_reply},
                {"role": "user", "content": f"아래는 도구 실행 결과입니다. 이 데이터를 분석하여 사용자에게 답변하세요.\n\n{tool_context}"},
            ]
            if provider == "anthropic":
                reply = await call_claude(followup_messages, system, api_key, model)
            else:
                reply = await call_openai(followup_messages, system, api_key, model)

    except Exception as e:
        logger.error("LLM call failed: %s", e)
        err_str = str(e)
        if "429" in err_str:
            reply = "API 호출 한도 초과 (429 Too Many Requests). 1분 후 다시 시도해주세요."
        elif "timeout" in err_str.lower():
            reply = "AI 응답 시간 초과. 잠시 후 다시 시도해주세요."
        else:
            reply = "AI 응답에 실패했습니다. 잠시 후 다시 시도해주세요."

    await append_history(redis, req.session_id, "assistant", reply)
    await save_to_db(pool, req.session_id, "assistant", reply, model=model)

    return ChatResponse(
        reply=reply,
        session_id=req.session_id,
        model=model,
        context_summary=context,
    )


@router.get("/history")
async def api_history(
    session_id: str = "default",
    redis: aioredis.Redis = Depends(get_redis),
):
    """Get chat history for a session."""
    history = await get_history(redis, session_id, limit=50)
    return {"session_id": session_id, "messages": history}


@router.delete("/history")
async def api_clear_history(
    session_id: str = "default",
    redis: aioredis.Redis = Depends(get_redis),
):
    """Clear chat history for a session."""
    key = f"llm:chat:{session_id}"
    await redis.delete(key)
    return {"ok": True}


@router.get("/history/all")
async def api_all_history(
    limit: int = 100,
    pool: asyncpg.Pool = Depends(get_db),
):
    """Get all chat history from DB (persistent, across sessions)."""
    try:
        await _ensure_chat_table(pool)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT time, session_id, role, content, model, has_image "
                "FROM chat_history ORDER BY time DESC LIMIT $1",
                limit,
            )
        return {
            "count": len(rows),
            "messages": [
                {
                    "time": r["time"].isoformat(),
                    "session_id": r["session_id"],
                    "role": r["role"],
                    "content": r["content"][:500],
                    "model": r["model"],
                    "has_image": r["has_image"],
                }
                for r in reversed(rows)
            ],
        }
    except Exception:
        return {"count": 0, "messages": []}
