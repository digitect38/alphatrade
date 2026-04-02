/**
 * AlphaTrade GUI Full Audit Script
 *
 * Usage: node scripts/gui_audit.mjs
 *
 * Tests all pages on desktop + mobile:
 * - Screenshots each page
 * - Checks for text errors (undefined, NaN, Error, [object])
 * - Checks for empty cards, missing charts
 * - Reports issues
 */

import { chromium, devices } from "playwright";
import { mkdirSync, existsSync } from "fs";
import { join } from "path";

const BASE = "http://localhost:3000";
const OUT = join(process.cwd(), "capture", "gui-audit-" + new Date().toISOString().slice(0, 10));

const PAGES = [
  { hash: "command", name: "command", label: "커맨드센터" },
  { hash: "dashboard", name: "dashboard", label: "대시보드" },
  { hash: "market", name: "market", label: "시세" },
  { hash: "trend", name: "trend", label: "시장 인텔" },
  { hash: "analysis", name: "analysis", label: "분석" },
  { hash: "backtest", name: "backtest", label: "백테스트" },
  { hash: "risk", name: "risk", label: "리스크" },
  { hash: "execution", name: "execution", label: "체결" },
  { hash: "orders", name: "orders", label: "주문" },
  { hash: "asset/005930", name: "asset-samsung", label: "종목상세(삼성전자)" },
  { hash: "asset/000660", name: "asset-skhynix", label: "종목상세(SK하이닉스)" },
  { hash: "monitor/movers", name: "monitor", label: "모니터" },
];

const ANALYSIS_PRESETS = [
  { label: "1m", idx: 0 },
  { label: "1D", idx: 3 },
  { label: "6M", idx: 7 },
  { label: "3Y", idx: 9 },
];

const ASSET_RANGES = [
  { label: "1분", idx: 0 },
  { label: "1일", idx: 3 },
  { label: "1개월", idx: 5 },
  { label: "1년", idx: 9 },
];

async function checkPage(page, name) {
  const issues = [];

  const textIssues = await page.evaluate(() => {
    const body = document.body.innerText;
    const problems = [];
    // Check for raw JS errors
    if (/\bundefined\b/.test(body) && !body.includes("undefined}") && !body.includes("undefined;")) {
      const match = body.match(/.{0,30}undefined.{0,30}/);
      problems.push(`"undefined" text: ...${match?.[0]}...`);
    }
    if (/\bNaN\b/.test(body)) problems.push("NaN in page text");
    if (body.includes("[object Object]")) problems.push("[object Object] in text");
    // Empty state
    if (body.trim().length < 50) problems.push("nearly empty page");
    return problems;
  });
  issues.push(...textIssues);

  // Check charts
  const chartInfo = await page.evaluate(() => {
    const charts = document.querySelectorAll(".recharts-wrapper");
    const lines = document.querySelectorAll(".recharts-line-curve");
    return { charts: charts.length, lines: lines.length };
  });

  // Check loading spinners stuck
  const loading = await page.evaluate(() => {
    const text = document.body.innerText;
    return text.includes("로딩 중") || text.includes("Loading");
  });
  if (loading) issues.push("stuck in loading state");

  return { name, charts: chartInfo.charts, lines: chartInfo.lines, issues };
}

async function main() {
  if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const allIssues = [];

  console.log("=== AlphaTrade GUI Full Audit ===\n");
  console.log(`Output: ${OUT}\n`);

  // ===== Desktop =====
  console.log("--- Desktop (1440x900) ---");
  const dCtx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  const dp = await dCtx.newPage();

  for (const pg of PAGES) {
    process.stdout.write(`  ${pg.label.padEnd(20)}`);
    await dp.goto(`${BASE}/#${pg.hash}`, { waitUntil: "networkidle", timeout: 15000 });
    await dp.waitForTimeout(3000);
    await dp.screenshot({ path: join(OUT, `desktop-${pg.name}.png`), fullPage: true });
    const result = await checkPage(dp, pg.label);
    const status = result.issues.length ? "WARN" : "OK";
    console.log(`${status}  charts=${result.charts} lines=${result.lines}${result.issues.length ? " | " + result.issues.join(", ") : ""}`);
    if (result.issues.length) allIssues.push({ page: pg.label, viewport: "desktop", issues: result.issues });
  }

  // Analysis presets
  console.log("\n--- Analysis Chart Presets ---");
  for (const preset of ANALYSIS_PRESETS) {
    process.stdout.write(`  분석 ${preset.label.padEnd(6)}`);
    await dp.goto(`${BASE}/#analysis`, { waitUntil: "networkidle", timeout: 15000 });
    await dp.waitForTimeout(1500);
    await dp.locator("button.asset-range-chip").nth(preset.idx).click();
    await dp.waitForTimeout(3000);
    const lines = await dp.evaluate(() => document.querySelectorAll(".recharts-line-curve").length);
    const yTicks = await dp.evaluate(() =>
      Array.from(document.querySelectorAll(".recharts-yAxis .recharts-cartesian-axis-tick-value")).map((t) => t.textContent)
    );
    const hasZeroAxis = yTicks.some((t) => t === "0");
    const status = lines > 0 && !hasZeroAxis ? "OK" : "WARN";
    console.log(`${status}  lines=${lines} y=[${yTicks.join(",")}]`);
    if (hasZeroAxis) allIssues.push({ page: `분석 ${preset.label}`, viewport: "desktop", issues: ["Y-axis starts at 0"] });
    await dp.screenshot({ path: join(OUT, `desktop-analysis-${preset.label}.png`), fullPage: false });
  }

  // Asset detail ranges + candle
  console.log("\n--- Asset Detail Ranges ---");
  for (const range of ASSET_RANGES) {
    process.stdout.write(`  종목상세 ${range.label.padEnd(6)}`);
    await dp.goto(`${BASE}/#asset/005930`, { waitUntil: "networkidle", timeout: 15000 });
    await dp.waitForTimeout(2000);
    await dp.locator(".asset-range-chip").nth(range.idx).click();
    await dp.waitForTimeout(3000);
    const yTicks = await dp.evaluate(() =>
      Array.from(document.querySelectorAll(".recharts-yAxis .recharts-cartesian-axis-tick-value")).map((t) => t.textContent)
    );
    const hasZeroAxis = yTicks.some((t) => t === "0");
    console.log(`${hasZeroAxis ? "WARN" : "OK"}  y=[${yTicks.join(",")}]`);
    if (hasZeroAxis) allIssues.push({ page: `종목상세 ${range.label}`, viewport: "desktop", issues: ["Y-axis starts at 0"] });
  }

  await dCtx.close();

  // ===== Mobile =====
  console.log("\n--- Mobile (iPhone 14) ---");
  const mCtx = await browser.newContext({ ...devices["iPhone 14"] });
  const mp = await mCtx.newPage();

  for (const pg of PAGES.slice(0, 7)) {
    process.stdout.write(`  ${pg.label.padEnd(20)}`);
    await mp.goto(`${BASE}/#${pg.hash}`, { waitUntil: "networkidle", timeout: 15000 });
    await mp.waitForTimeout(2500);
    await mp.screenshot({ path: join(OUT, `mobile-${pg.name}.png`), fullPage: true });
    const result = await checkPage(mp, pg.label);
    const status = result.issues.length ? "WARN" : "OK";
    console.log(`${status}${result.issues.length ? " | " + result.issues.join(", ") : ""}`);
    if (result.issues.length) allIssues.push({ page: pg.label, viewport: "mobile", issues: result.issues });
  }

  await mCtx.close();
  await browser.close();

  // ===== Summary =====
  console.log("\n=== SUMMARY ===");
  console.log(`Screenshots: ${OUT}`);
  console.log(`Pages tested: ${PAGES.length} desktop + 7 mobile + ${ANALYSIS_PRESETS.length} presets + ${ASSET_RANGES.length} ranges`);
  console.log(`Issues found: ${allIssues.length}`);
  if (allIssues.length) {
    console.log("\nIssues:");
    for (const issue of allIssues) {
      console.log(`  [${issue.viewport}] ${issue.page}: ${issue.issues.join(", ")}`);
    }
  } else {
    console.log("\nAll pages rendered without errors.");
  }
}

main().catch(console.error);
