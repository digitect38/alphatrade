import { useState } from "react";

export type Locale = "ko" | "en";

const STORAGE_KEY = "alphatrade_locale";

const translations: Record<string, Record<Locale, string>> = {
  // Sidebar
  "nav.command": { en: "Command Center", ko: "커맨드 센터" },
  "nav.dashboard": { en: "Dashboard", ko: "대시보드" },
  "nav.market": { en: "Market", ko: "시세" },
  "nav.trend": { en: "Market Intel", ko: "시장 인텔" },
  "nav.analysis": { en: "Analysis", ko: "분석" },
  "nav.backtest": { en: "Backtest", ko: "백테스트" },
  "nav.execution": { en: "Execution", ko: "체결" },
  "nav.orders": { en: "Orders", ko: "주문" },

  // Page titles
  "title.command": { en: "Command Center", ko: "커맨드 센터" },
  "title.dashboard": { en: "Dashboard", ko: "대시보드" },
  "title.market": { en: "Market", ko: "시세 현황" },
  "title.trend": { en: "Market Intel", ko: "시장 인텔" },
  "title.analysis": { en: "Technical Analysis", ko: "기술적 분석" },
  "title.backtest": { en: "Backtest", ko: "백테스트" },
  "title.execution": { en: "Execution", ko: "체결 관리" },
  "title.orders": { en: "Orders", ko: "주문 관리" },

  // Dashboard
  "dash.totalValue": { en: "Total Value", ko: "총 평가금액" },
  "dash.cash": { en: "Cash", ko: "현금" },
  "dash.unrealizedPnl": { en: "Unrealized P&L", ko: "미실현 손익" },
  "dash.return": { en: "Return", ko: "수익률" },
  "dash.positions": { en: "Positions", ko: "보유 종목" },
  "dash.systemStatus": { en: "System Status", ko: "시스템 상태" },
  "dash.strategySignals": { en: "Strategy Signals", ko: "전략 시그널" },

  // Table headers
  "th.code": { en: "Code", ko: "종목코드" },
  "th.name": { en: "Name", ko: "종목명" },
  "th.sector": { en: "Sector", ko: "섹터" },
  "th.price": { en: "Price", ko: "현재가" },
  "th.change": { en: "Change", ko: "변동" },
  "th.changePct": { en: "Change %", ko: "변동률" },
  "th.volume": { en: "Volume", ko: "거래량" },
  "th.news": { en: "News", ko: "뉴스" },
  "th.qty": { en: "Qty", ko: "수량" },
  "th.avgPrice": { en: "Avg Price", ko: "평균가" },
  "th.current": { en: "Current", ko: "현재가" },
  "th.pnl": { en: "P&L", ko: "손익" },
  "th.weight": { en: "Weight", ko: "비중" },
  "th.signal": { en: "Signal", ko: "시그널" },
  "th.score": { en: "Score", ko: "점수" },
  "th.strength": { en: "Strength", ko: "강도" },
  "th.topReason": { en: "Top Reason", ko: "주요 근거" },
  "th.time": { en: "Time", ko: "시간" },
  "th.side": { en: "Side", ko: "매매" },
  "th.status": { en: "Status", ko: "상태" },
  "th.date": { en: "Date", ko: "날짜" },
  "th.action": { en: "Action", ko: "매매" },

  // Market page
  "market.refresh": { en: "Refresh", ko: "시세 조회" },
  "market.loading": { en: "Loading...", ko: "조회 중..." },
  "market.autoRefresh": { en: "Auto refresh (1min)", ko: "자동 갱신 (1분)" },
  "market.morningScan": { en: "Morning Scan", ko: "장초반 스캔" },
  "market.relatedNews": { en: "Related News", ko: "관련 뉴스" },
  "market.noNews": { en: "No related news.", ko: "관련 뉴스가 없습니다." },

  // Trend page
  "trend.sectorFilter": { en: "Sector Filter", ko: "섹터 필터" },
  "trend.all": { en: "All", ko: "전체" },
  "trend.reset": { en: "Reset", ko: "초기화" },
  "trend.cumulativeReturn": { en: "Cumulative Return by Sector (%)", ko: "섹터별 누적 수익률 (%)" },
  "trend.sectorRanking": { en: "Sector Ranking (Avg Daily Change)", ko: "섹터 순위 (일간 평균 변동률)" },
  "trend.stockCount": { en: "Stocks", ko: "종목수" },
  "trend.avgChange": { en: "Avg Change", ko: "평균 변동률" },
  "trend.cumReturn": { en: "Cum. Return", ko: "누적 수익률" },
  "trend.detail": { en: "Detail", ko: "상세" },
  "trend.stocks": { en: "Stocks", ko: "종목" },
  "trend.collapse": { en: "Collapse", ko: "접기" },

  // Analysis page
  "analysis.analyze": { en: "Analyze", ko: "분석" },
  "analysis.analyzing": { en: "Analyzing...", ko: "분석 중..." },
  "analysis.currentPrice": { en: "Current Price", ko: "현재가" },
  "analysis.priceChart": { en: "Price Chart", ko: "가격 차트" },
  "analysis.scores": { en: "Scores", ko: "점수" },
  "analysis.trend": { en: "Trend", ko: "추세" },
  "analysis.momentum": { en: "Momentum", ko: "모멘텀" },
  "analysis.overall": { en: "Overall", ko: "종합" },
  "analysis.signals": { en: "Signals", ko: "시그널" },
  "analysis.keyIndicators": { en: "Key Indicators", ko: "주요 지표" },

  // Backtest page
  "bt.run": { en: "Run Backtest", ko: "백테스트 실행" },
  "bt.running": { en: "Running...", ko: "실행 중..." },
  "bt.totalReturn": { en: "Total Return", ko: "총 수익률" },
  "bt.mdd": { en: "Max Drawdown (MDD)", ko: "최대 낙폭 (MDD)" },
  "bt.winRate": { en: "Win Rate", ko: "승률" },
  "bt.sharpe": { en: "Sharpe Ratio", ko: "샤프 비율" },
  "bt.initialCapital": { en: "Initial Capital", ko: "초기 자본" },
  "bt.finalCapital": { en: "Final Capital", ko: "최종 자본" },
  "bt.annualReturn": { en: "Annual Return", ko: "연환산 수익률" },
  "bt.totalTrades": { en: "Total Trades", ko: "총 거래" },
  "bt.equityCurve": { en: "Equity Curve", ko: "자산 곡선" },
  "bt.tradeHistory": { en: "Trade History", ko: "거래 내역" },
  "bt.ensemble": { en: "Ensemble (Default)", ko: "앙상블 (기본)" },
  "bt.momentum": { en: "Momentum", ko: "모멘텀" },
  "bt.meanReversion": { en: "Mean Reversion", ko: "평균회귀" },

  // Orders page
  "order.manual": { en: "Manual Order", ko: "수동 주문" },
  "order.history": { en: "Order History", ko: "주문 이력" },
  "order.buy": { en: "BUY Order", ko: "매수 주문" },
  "order.sell": { en: "SELL Order", ko: "매도 주문" },
  "order.noOrders": { en: "No orders yet", ko: "주문 내역이 없습니다" },

  // Dashboard — new keys
  "dash.portfolioComposition": { en: "Portfolio Composition", ko: "포트폴리오 구성" },
  "dash.invested": { en: "Invested", ko: "투자" },
  "dash.riskStatus": { en: "Risk Status", ko: "리스크 현황" },
  "dash.quickActions": { en: "Quick Actions", ko: "빠른 실행" },
  "dash.actionSignals": { en: "Action Signals", ko: "행동 시그널" },
  "dash.noPositions": { en: "No positions", ko: "보유 종목 없음" },
  "dash.dailyPnl": { en: "Daily P&L", ko: "일간 손익" },
  "dash.mdd": { en: "MDD", ko: "최대 낙폭" },
  "dash.positionDetail": { en: "Position Detail", ko: "보유 종목 상세" },

  // Quick actions
  "action.runCycle": { en: "Run Trading Cycle", ko: "매매 사이클 실행" },
  "action.morningScan": { en: "Morning Scan", ko: "장초반 스캔" },
  "action.saveSnapshot": { en: "Save Snapshot", ko: "스냅샷 저장" },
  "action.monitorPositions": { en: "Monitor Positions", ko: "포지션 감시" },

  // Risk
  "risk.dailyLossLimit": { en: "Daily Loss Limit", ko: "일간 손실 한도" },
  "risk.maxDrawdown": { en: "Max Drawdown", ko: "최대 낙폭" },
  "risk.cashRatio": { en: "Cash Ratio", ko: "현금 비율" },

  // Backtest extra
  "bt.stockCode": { en: "Stock Code", ko: "종목코드" },
  "bt.strategy": { en: "Strategy", ko: "전략" },
  "bt.capital": { en: "Capital", ko: "자본금" },
  "bt.recentTrades": { en: "Recent Trades", ko: "거래 내역" },

  // Orders extra
  "order.stockCode": { en: "Stock Code", ko: "종목코드" },
  "order.quantity": { en: "Quantity", ko: "수량" },
  "order.execute": { en: "Execute", ko: "주문 실행" },

  // Market extra
  "market.scanResult": { en: "Morning Scan Result", ko: "장초반 스캔 결과" },

  // Common
  "common.loading": { en: "Loading...", ko: "로딩 중..." },
  "common.save": { en: "Save", ko: "저장" },
  "common.close": { en: "Close", ko: "닫기" },
  "common.won": { en: "KRW", ko: "원" },
  "common.stocks": { en: "stocks", ko: "종목" },
  "common.placeholder.stockCode": { en: "Stock code (e.g. 005930)", ko: "종목코드 (예: 005930)" },
};

export function useLocale() {
  const [locale, setLocaleState] = useState<Locale>(() => {
    if (typeof window !== "undefined") {
      return (localStorage.getItem(STORAGE_KEY) as Locale) || "ko";
    }
    return "ko";
  });

  const setLocale = (l: Locale) => {
    setLocaleState(l);
    localStorage.setItem(STORAGE_KEY, l);
  };

  const t = (key: string): string => {
    return translations[key]?.[locale] ?? key;
  };

  return { locale, setLocale, t };
}
