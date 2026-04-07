Show all available AlphaTrade slash commands and how to use them.

Print the following help text:

```
╔══════════════════════════════════════════════════════════════╗
║               AlphaTrade Slash Commands                      ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  📈 Trading & Market                                         ║
║  ─────────────────────────────────────────────────────────── ║
║  /kis-price <종목코드>          KIS 실시간 시세 조회          ║
║    예: /kis-price 005930                                     ║
║                                                              ║
║  /signal <종목코드>             최신 매매 시그널 조회         ║
║    예: /signal 005930                                        ║
║                                                              ║
║  /market                        시장 종합 현황               ║
║    (지수, 등락 상위, 트레이딩 모드, 킬스위치)                ║
║                                                              ║
║  📊 Analysis                                                 ║
║  ─────────────────────────────────────────────────────────── ║
║  /backtest <종목> [전략] [기간]  백테스트 실행                ║
║    전략: ensemble, momentum, mean_reversion,                 ║
║          conservative, aggressive                            ║
║    기간: 3M, 6M, 1Y, 2Y, 3Y, 5Y, MAX                       ║
║    예: /backtest 005930 momentum 2Y                          ║
║                                                              ║
║  🔧 System                                                   ║
║  ─────────────────────────────────────────────────────────── ║
║  /deploy [서비스]               Docker 빌드 + 배포 + QA      ║
║    서비스: dashboard, core-engine, 또는 생략(=both)           ║
║    예: /deploy dashboard                                     ║
║                                                              ║
║  /qa                            Playwright QA 40항목 실행    ║
║                                                              ║
║  /at-help                       이 도움말 표시               ║
║                                                              ║
║  🤖 MCP Tools (외부 클라이언트용)                            ║
║  ─────────────────────────────────────────────────────────── ║
║  kis_price, backtest, signal, market_overview, news,         ║
║  portfolio — .mcp.json 으로 자동 등록                        ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

Do NOT execute any commands. Just print this help text.
