/**
 * Major political/economic events for chart annotation.
 *
 * Each event has: date, label, category, description, url (news link).
 * Categories: "policy" | "geopolitics" | "economy" | "market" | "disaster"
 */

export interface MarketEvent {
  date: string;
  label: string;
  category: "policy" | "geopolitics" | "economy" | "market" | "disaster";
  description: string;
  url: string;
  importance?: number;  // 1-5, higher = more important
}

export const MARKET_EVENTS: MarketEvent[] = [
  // === Historical ===
  { date: "1950-06-25", label: "한국전쟁", category: "geopolitics", description: "6.25 한국전쟁 발발",
    url: "https://search.naver.com/search.naver?query=6.25+한국전쟁" },
  { date: "1979-10-26", label: "10.26 사태", category: "geopolitics", description: "박정희 대통령 시해 사건",
    url: "https://search.naver.com/search.naver?query=10.26+사태" },
  { date: "1987-06-29", label: "6.29 선언", category: "geopolitics", description: "노태우 6.29 민주화 선언",
    url: "https://search.naver.com/search.naver?query=6.29+민주화+선언" },
  { date: "1997-11-21", label: "IMF 구제금융", category: "economy", description: "한국 IMF 구제금융 신청 — 환율 2,000원, KOSPI 300",
    url: "https://search.naver.com/search.naver?query=IMF+구제금융+1997" },
  { date: "1998-08-17", label: "러시아 모라토리엄", category: "economy", description: "러시아 국채 디폴트 — 글로벌 금융 위기",
    url: "https://search.naver.com/search.naver?query=러시아+모라토리엄+1998" },
  { date: "2000-03-10", label: "닷컴 버블 붕괴", category: "market", description: "나스닥 5,048 정점 후 폭락 — IT 버블 붕괴",
    url: "https://search.naver.com/search.naver?query=닷컴+버블+붕괴+2000" },
  { date: "2001-09-11", label: "9.11 테러", category: "disaster", description: "미국 9.11 테러 — 글로벌 증시 폭락",
    url: "https://search.naver.com/search.naver?query=9.11+테러" },
  { date: "2003-03-20", label: "이라크 전쟁", category: "geopolitics", description: "미국 이라크 침공 — 유가 급등",
    url: "https://search.naver.com/search.naver?query=이라크+전쟁+2003" },
  { date: "2008-09-15", label: "리먼 파산", category: "economy", description: "리먼브라더스 파산 — 글로벌 금융위기",
    url: "https://search.naver.com/search.naver?query=리먼브라더스+파산" },
  { date: "2008-10-24", label: "KOSPI 938", category: "market", description: "KOSPI 938 저점 — 글로벌 금융위기 바닥",
    url: "https://search.naver.com/search.naver?query=KOSPI+2008+금융위기" },
  { date: "2010-11-23", label: "연평도 포격", category: "geopolitics", description: "북한 연평도 포격 — KOSPI 급락",
    url: "https://search.naver.com/search.naver?query=연평도+포격" },
  { date: "2011-08-05", label: "美 신용등급 강등", category: "economy", description: "S&P 미국 신용등급 AAA→AA+ 강등",
    url: "https://search.naver.com/search.naver?query=미국+신용등급+강등+2011" },
  { date: "2013-06-19", label: "Fed 테이퍼 탠트럼", category: "policy", description: "버냉키 양적완화 축소 시사 — 신흥국 급락",
    url: "https://search.naver.com/search.naver?query=테이퍼+탠트럼+2013" },
  { date: "2015-08-24", label: "차이나 쇼크", category: "market", description: "중국 위안화 평가절하 — 글로벌 블랙먼데이",
    url: "https://search.naver.com/search.naver?query=차이나+쇼크+2015" },
  { date: "2016-06-23", label: "브렉시트", category: "geopolitics", description: "영국 EU 탈퇴 국민투표 가결",
    url: "https://search.naver.com/search.naver?query=브렉시트+2016" },
  { date: "2016-11-08", label: "트럼프 1기 당선", category: "geopolitics", description: "트럼프 첫 대통령 당선 — 트럼프 랠리",
    url: "https://search.naver.com/search.naver?query=트럼프+당선+2016" },
  { date: "2017-09-03", label: "북한 6차 핵실험", category: "geopolitics", description: "북한 수소폭탄 핵실험 — 코리아 디스카운트",
    url: "https://search.naver.com/search.naver?query=북한+6차+핵실험" },
  { date: "2018-02-05", label: "변동성 쇼크", category: "market", description: "VIX 급등 — 글로벌 증시 급락 (Volmageddon)",
    url: "https://search.naver.com/search.naver?query=볼마겟돈+2018" },
  { date: "2018-10-03", label: "美中 무역전쟁", category: "geopolitics", description: "미중 무역전쟁 본격화 — 관세 25% 부과",
    url: "https://search.naver.com/search.naver?query=미중+무역전쟁+2018" },
  { date: "2019-08-02", label: "日 수출규제", category: "geopolitics", description: "일본 한국 화이트리스트 제외 — 반도체 소재 규제",
    url: "https://search.naver.com/search.naver?query=일본+수출규제+2019" },

  // === 2020 ===
  { date: "2020-01-30", label: "WHO 팬데믹", category: "disaster", description: "WHO COVID-19 국제 공중보건 비상사태 선언",
    url: "https://n.news.naver.com/article/001/0011378073" },
  { date: "2020-03-12", label: "서킷브레이커", category: "market", description: "KOSPI 서킷브레이커 발동 (-8%)",
    url: "https://n.news.naver.com/article/001/0011427898" },
  { date: "2020-03-16", label: "Fed 제로금리", category: "policy", description: "미국 Fed 긴급 금리인하 0~0.25%",
    url: "https://n.news.naver.com/article/001/0011432122" },
  { date: "2020-03-23", label: "코로나 저점", category: "market", description: "KOSPI 1,457 저점 — 글로벌 패닉 바닥",
    url: "https://n.news.naver.com/article/015/0004315892" },
  { date: "2020-06-16", label: "Fed 무제한 QE", category: "policy", description: "미국 Fed 회사채 매입 시작",
    url: "https://n.news.naver.com/article/001/0011668108" },

  // === 2021 ===
  { date: "2021-01-25", label: "공매도 금지", category: "policy", description: "한국 공매도 전면 금지 연장",
    url: "https://n.news.naver.com/article/009/0004726379" },
  { date: "2021-03-25", label: "수에즈 봉쇄", category: "geopolitics", description: "에버기븐호 수에즈운하 좌초 — 글로벌 공급망 차질",
    url: "https://n.news.naver.com/article/001/0012261553" },
  { date: "2021-06-16", label: "Fed 테이퍼링", category: "policy", description: "FOMC 금리 인상 시기 앞당김 시사",
    url: "https://n.news.naver.com/article/001/0012436780" },
  { date: "2021-09-20", label: "헝다 위기", category: "economy", description: "중국 헝다그룹 디폴트 우려 — 아시아 증시 급락",
    url: "https://n.news.naver.com/article/015/0004603625" },
  { date: "2021-11-26", label: "오미크론", category: "disaster", description: "오미크론 변이 발견 — 글로벌 증시 급락",
    url: "https://n.news.naver.com/article/001/0012826924" },

  // === 2022 ===
  { date: "2022-02-24", label: "러-우 전쟁", category: "geopolitics", description: "러시아 우크라이나 침공 개시",
    url: "https://n.news.naver.com/article/001/0012965780" },
  { date: "2022-03-17", label: "Fed 인상 시작", category: "policy", description: "미국 Fed 금리인상 시작 (0.25%p)",
    url: "https://n.news.naver.com/article/001/0013025420" },
  { date: "2022-06-15", label: "자이언트스텝", category: "policy", description: "Fed 75bp 자이언트스텝 금리인상",
    url: "https://n.news.naver.com/article/001/0013218614" },
  { date: "2022-09-28", label: "환율 1440", category: "economy", description: "원/달러 환율 1,440원 돌파 — 13년 만의 최고",
    url: "https://n.news.naver.com/article/015/0004755938" },
  { date: "2022-10-12", label: "KOSPI 저점", category: "market", description: "KOSPI 연저점 2,155 — 약세장 바닥",
    url: "https://n.news.naver.com/article/009/0005034729" },
  { date: "2022-11-11", label: "FTX 파산", category: "economy", description: "FTX 거래소 파산 — 크립토 시장 충격",
    url: "https://n.news.naver.com/article/001/0013498660" },
  { date: "2022-12-14", label: "Fed 50bp", category: "policy", description: "Fed 50bp로 인상폭 축소 — 피벗 기대",
    url: "https://n.news.naver.com/article/001/0013564025" },

  // === 2023 ===
  { date: "2023-03-10", label: "SVB 파산", category: "economy", description: "실리콘밸리은행 파산 — 은행 위기",
    url: "https://n.news.naver.com/article/001/0013766340" },
  { date: "2023-05-03", label: "Fed 5.25%", category: "policy", description: "Fed 금리 5.00~5.25% 도달",
    url: "https://n.news.naver.com/article/001/0013896260" },
  { date: "2023-07-27", label: "BOJ 완화 수정", category: "policy", description: "일본은행 YCC 정책 유연화",
    url: "https://n.news.naver.com/article/001/0014081210" },
  { date: "2023-10-07", label: "이스라엘-하마스", category: "geopolitics", description: "이스라엘-하마스 전쟁 발발",
    url: "https://n.news.naver.com/article/001/0014243730" },
  { date: "2023-12-13", label: "Fed 피벗", category: "policy", description: "Fed 2024년 금리인하 3회 시사 — 피벗 선언",
    url: "https://n.news.naver.com/article/001/0014381620" },

  // === 2024 ===
  { date: "2024-01-02", label: "일본 지진", category: "disaster", description: "일본 노토반도 대지진 M7.6",
    url: "https://n.news.naver.com/article/001/0014411237" },
  { date: "2024-03-20", label: "BOJ 마이너스 종료", category: "policy", description: "일본 17년만에 마이너스 금리 탈출",
    url: "https://n.news.naver.com/article/001/0014569870" },
  { date: "2024-04-19", label: "이란-이스라엘", category: "geopolitics", description: "이란-이스라엘 상호 공격 — 중동 확전 우려",
    url: "https://n.news.naver.com/article/001/0014619830" },
  { date: "2024-06-12", label: "Fed 1회 인하", category: "policy", description: "FOMC 2024 인하 전망 3→1회로 축소",
    url: "https://n.news.naver.com/article/001/0014721520" },
  { date: "2024-08-05", label: "엔캐리 청산", category: "market", description: "일본 금리인상→엔캐리 청산 — 글로벌 급락",
    url: "https://n.news.naver.com/article/015/0004998612" },
  { date: "2024-09-18", label: "Fed 인하 시작", category: "policy", description: "Fed 4년만에 금리인하 시작 (-50bp)",
    url: "https://n.news.naver.com/article/001/0014878320" },
  { date: "2024-11-05", label: "트럼프 당선", category: "geopolitics", description: "트럼프 2기 대통령 당선",
    url: "https://n.news.naver.com/article/001/0014961520" },
  { date: "2024-12-03", label: "한국 계엄령", category: "geopolitics", description: "윤석열 대통령 비상계엄 선포 — KOSPI 급락",
    url: "https://n.news.naver.com/article/001/0015021270" },

  // === 2025 ===
  { date: "2025-01-20", label: "트럼프 취임", category: "geopolitics", description: "트럼프 2기 취임 — 관세 정책 본격화",
    url: "https://n.news.naver.com/article/001/0015098420" },
  { date: "2025-02-01", label: "미중 관세전쟁", category: "geopolitics", description: "미국 대중국 관세 10% 추가 부과",
    url: "https://n.news.naver.com/article/001/0015125680" },
  { date: "2025-03-04", label: "탄핵 인용", category: "geopolitics", description: "헌법재판소 윤석열 대통령 탄핵 인용",
    url: "https://n.news.naver.com/article/001/0015186230" },
  { date: "2025-04-02", label: "상호관세 발효", category: "policy", description: "트럼프 상호관세(Reciprocal Tariff) 전면 발효",
    url: "https://search.naver.com/search.naver?query=트럼프+상호관세+2025" },
  { date: "2025-06-03", label: "한국 대선", category: "geopolitics", description: "한국 조기 대통령 선거",
    url: "https://search.naver.com/search.naver?query=2025+한국+대선" },

  // === 2026 ===
  { date: "2026-01-15", label: "Fed 동결", category: "policy", description: "Fed 금리 동결 4.00% 유지",
    url: "https://search.naver.com/search.naver?query=Fed+금리+2026" },
  { date: "2026-03-15", label: "반도체 규제", category: "geopolitics", description: "미국 대중국 반도체 수출 규제 3차 확대",
    url: "https://search.naver.com/search.naver?query=미중+반도체+규제+2026" },
];

const CATEGORY_COLORS: Record<string, string> = {
  policy: "#7c3aed",
  geopolitics: "#dc2626",
  economy: "#d97706",
  market: "#2563eb",
  disaster: "#64748b",
};

export function getEventColor(category: string): string {
  return CATEGORY_COLORS[category] || "#888";
}

/**
 * Filter events that fall within a date range.
 */
export function filterEvents(startDate: string, endDate: string): MarketEvent[] {
  return MARKET_EVENTS.filter((e) => e.date >= startDate && e.date <= endDate);
}
