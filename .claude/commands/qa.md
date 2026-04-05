Run the full QA test suite using Playwright against the running dashboard at localhost:3000.

Execute: `cd dashboard && node scripts/qa-full.mjs`

This tests:
- All 11 pages load without crashes
- Asset Detail: stock switch via sidebar and hash navigation
- Chart rendering: canvas, RSI/MACD panes, range buttons
- Analysis: stock switch preserves page
- Backtest: stock switch re-runs backtest
- Recent stocks sidebar widget

After the test completes:
1. Report the PASS/FAIL summary
2. For any FAIL results, investigate the root cause
3. If the failure is a real bug (not timing/rate-limit), fix the code, rebuild Docker, and re-run the test
4. Take screenshots of failures and save to artifacts/qa/
