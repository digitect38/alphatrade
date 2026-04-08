"""LLM Chat — Context building and RAG retrieval."""

import logging
import re
from datetime import datetime, timezone

import asyncpg
import httpx
import redis.asyncio as aioredis

from app.utils.redis_cache import get_realtime_price

logger = logging.getLogger(__name__)


async def build_context(question: str, pool: asyncpg.Pool, redis: aioredis.Redis) -> str:
    """Build rich context for LLM from portfolio, market, news, events, and web."""
    parts: list[str] = []

    # 1. Portfolio
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
                rt = await get_realtime_price(redis, pos["stock_code"])
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

    # 3. Stock codes from question
    codes = re.findall(r'\b(\d{6})\b', question)
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

    for code in dict.fromkeys(codes):
        try:
            async with pool.acquire() as conn:
                name = await conn.fetchrow("SELECT stock_name FROM stocks WHERE stock_code = $1", code)
                sig = await conn.fetchrow(
                    "SELECT signal, strength FROM strategy_signals "
                    "WHERE stock_code = $1 ORDER BY time DESC LIMIT 1", code
                )
            rt = await get_realtime_price(redis, code)
            label = f"{name['stock_name']}({code})" if name else code
            if rt and rt["price"] > 0:
                parts.append(f"{label}: 실시간 {rt['price']:,.0f}원 ({rt['change_pct']:+.2f}%), 거래량 {rt['volume']:,}")
            else:
                kis_ok = False
                try:
                    from app.services.kis_api import KISClient
                    kis = KISClient()
                    kis_price = await kis.get_current_price(code)
                    await kis.close()
                    if kis_price and kis_price.price > 0:
                        parts.append(f"{label}: {kis_price.price:,.0f}원 (KIS 실시간 조회)")
                        kis_ok = True
                except Exception:
                    pass
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

    # 4. Market overview
    try:
        async with pool.acquire() as conn:
            top_stocks = await conn.fetch(
                "SELECT s.stock_code, s.stock_name FROM stocks s "
                "JOIN universe u ON s.stock_code = u.stock_code "
                "WHERE u.is_active = TRUE LIMIT 5"
            )
        market_lines = []
        for s in top_stocks:
            rt = await get_realtime_price(redis, s["stock_code"])
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

    # 5. RAG — news
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

    # 6. RAG — events
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

    # 7. RAG — web
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
    if len(context) > 6000:
        context = context[:6000] + "\n... (컨텍스트 일부 생략)"
    return context


# --- RAG helpers ---

async def _rag_search_news(pool: asyncpg.Pool, question: str, stock_codes: list[str]) -> list[dict]:
    results: list[dict] = []
    async with pool.acquire() as conn:
        if stock_codes:
            rows = await conn.fetch(
                "SELECT title, content, time, source FROM news "
                "WHERE stock_codes && $1::varchar[] ORDER BY time DESC LIMIT 5",
                stock_codes,
            )
            for r in rows:
                results.append({"date": str(r["time"])[:10], "title": r["title"][:80], "summary": (r["content"] or "")[:100]})

        keywords = [w for w in re.findall(r'[가-힣]{2,}', question) if len(w) >= 2]
        if keywords and len(results) < 5:
            for kw in keywords[:3]:
                rows = await conn.fetch(
                    "SELECT title, content, time FROM news WHERE title LIKE $1 ORDER BY time DESC LIMIT 3",
                    f"%{kw}%",
                )
                seen = {r["title"] for r in results}
                for r in rows:
                    if r["title"][:80] not in seen:
                        results.append({"date": str(r["time"])[:10], "title": r["title"][:80], "summary": (r["content"] or "")[:100]})
                        seen.add(r["title"][:80])

        if len(results) < 3:
            rows = await conn.fetch("SELECT title, time FROM news ORDER BY time DESC LIMIT 3")
            seen = {r["title"] for r in results}
            for r in rows:
                if r["title"][:80] not in seen:
                    results.append({"date": str(r["time"])[:10], "title": r["title"][:80]})
    return results[:8]


async def _rag_search_events(pool: asyncpg.Pool, question: str) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT date, label, category, description, importance "
            "FROM market_events WHERE importance >= 3 ORDER BY date DESC LIMIT 5"
        )
        keywords = re.findall(r'[가-힣a-zA-Z]{2,}', question)
        for kw in keywords[:2]:
            extra = await conn.fetch(
                "SELECT date, label, category, description, importance "
                "FROM market_events WHERE label LIKE $1 OR description LIKE $1 "
                "ORDER BY importance DESC, date DESC LIMIT 3",
                f"%{kw}%",
            )
            rows = list(rows) + list(extra)
    seen: set[str] = set()
    results: list[dict] = []
    for r in rows:
        key = f"{r['date']}:{r['label']}"
        if key not in seen:
            seen.add(key)
            results.append({
                "date": str(r["date"]), "label": r["label"], "category": r["category"],
                "description": r["description"][:150] if r["description"] else "", "importance": r["importance"],
            })
    return results[:5]


async def _rag_web_search(question: str) -> list[dict]:
    keywords = re.findall(r'[가-힣a-zA-Z0-9]{2,}', question)
    if not keywords:
        return []
    query = " ".join(keywords[:5]) + " 주식 증시"
    results: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query, "kl": "kr-kr"},
                headers={"User-Agent": "Mozilla/5.0 (compatible; AlphaTrade/1.0)"},
            )
            resp.raise_for_status()
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
