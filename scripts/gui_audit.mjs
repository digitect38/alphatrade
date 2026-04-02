/**
 * AlphaTrade GUI Full Audit — PC + Mobile 전체 경우의 수
 *
 * Usage: node scripts/gui_audit.mjs [--pc-only] [--mobile-only]
 *
 * Tests:
 * - 12 pages × 2 viewports (PC + Mobile) = 24
 * - 4 analysis presets × 2 viewports = 8
 * - 4 asset ranges × 2 viewports = 8
 * - 2 asset chart modes (line + candle) × 2 viewports = 4
 * - Risk 4 tabs × 2 viewports = 8
 * - Landscape mode for key pages = 4
 *
 * Total: ~56 test cases
 */

import { chromium, devices } from "playwright";
import { mkdirSync } from "fs";
import { join } from "path";

const BASE = "http://localhost:3000";
const OUT = join(process.cwd(), "capture", "gui-audit-" + new Date().toISOString().slice(0, 10));
const args = process.argv.slice(2);
const PC_ONLY = args.includes("--pc-only");
const MOBILE_ONLY = args.includes("--mobile-only");

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
  { hash: "asset/005930", name: "asset-samsung", label: "종목상세(삼성)" },
  { hash: "asset/000660", name: "asset-skhynix", label: "종목상세(SK)" },
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

const RISK_TABS = [
  { label: "실시간 손익", idx: 0 },
  { label: "VaR", idx: 1 },
  { label: "스트레스", idx: 2 },
  { label: "실전 점검", idx: 3 },
];

async function checkPage(page) {
  return page.evaluate(() => {
    const body = document.body.innerText;
    const problems = [];
    if (/\bundefined\b/.test(body) && !body.includes("undefined}")) problems.push("undefined");
    if (/\bNaN\b/.test(body)) problems.push("NaN");
    if (body.includes("[object Object]")) problems.push("[object]");
    if (body.trim().length < 50) problems.push("empty");
    const cards = document.querySelectorAll(".card").length;
    if ((body.includes("로딩 중") || body.includes("Loading...")) && cards <= 1) problems.push("loading stuck");
    const charts = document.querySelectorAll(".recharts-wrapper").length;
    const lines = document.querySelectorAll(".recharts-line-curve").length;
    // Y-axis zero check (first axis only)
    const firstY = document.querySelector(".recharts-yAxis");
    const yTicks = firstY ? Array.from(firstY.querySelectorAll(".recharts-cartesian-axis-tick-value")).map(t => t.textContent) : [];
    if (yTicks.length && yTicks[0] === "0" && charts > 0) problems.push("Y=0");
    return { problems, charts, lines };
  });
}

async function runViewport(browser, vpName, vpConfig, allIssues, stats) {
  console.log(`\n${"=".repeat(50)}`);
  console.log(`  ${vpName}`);
  console.log(`${"=".repeat(50)}`);

  const ctx = await browser.newContext(vpConfig);
  const p = await ctx.newPage();

  // --- All pages ---
  console.log("\n📄 Pages:");
  for (const pg of PAGES) {
    process.stdout.write(`  ${pg.label.padEnd(22)}`);
    await p.goto(`${BASE}/#${pg.hash}`, { waitUntil: "networkidle", timeout: 15000 });
    await p.waitForTimeout(5000);
    await p.screenshot({ path: join(OUT, `${vpName}-${pg.name}.png`), fullPage: true });
    const r = await checkPage(p);
    stats.total++;
    if (r.problems.length) {
      stats.issues++;
      allIssues.push({ vp: vpName, page: pg.label, issues: r.problems });
      console.log(`❌ ${r.problems.join(", ")}`);
    } else {
      console.log(`✅ charts=${r.charts} lines=${r.lines}`);
    }
  }

  // --- Analysis presets ---
  console.log("\n📈 분석 차트 프리셋:");
  for (const preset of ANALYSIS_PRESETS) {
    process.stdout.write(`  분석 ${preset.label.padEnd(8)}`);
    await p.goto(`${BASE}/#analysis`, { waitUntil: "networkidle", timeout: 15000 });
    await p.waitForTimeout(2000);
    await p.locator("button.asset-range-chip").nth(preset.idx).click();
    await p.waitForTimeout(4000);
    await p.screenshot({ path: join(OUT, `${vpName}-analysis-${preset.label}.png`), fullPage: false });
    const r = await checkPage(p);
    stats.total++;
    if (r.problems.length) {
      stats.issues++;
      allIssues.push({ vp: vpName, page: `분석 ${preset.label}`, issues: r.problems });
      console.log(`❌ ${r.problems.join(", ")}`);
    } else {
      console.log(`✅ lines=${r.lines}`);
    }
  }

  // --- Asset detail ranges ---
  console.log("\n🏢 종목상세 기간:");
  for (const range of ASSET_RANGES) {
    process.stdout.write(`  ${range.label.padEnd(10)}`);
    await p.goto(`${BASE}/#asset/005930`, { waitUntil: "networkidle", timeout: 15000 });
    await p.waitForTimeout(2000);
    await p.locator(".asset-range-chip").nth(range.idx).click();
    await p.waitForTimeout(4000);
    await p.screenshot({ path: join(OUT, `${vpName}-asset-${range.label}.png`), fullPage: false });
    const r = await checkPage(p);
    stats.total++;
    if (r.problems.length) {
      stats.issues++;
      allIssues.push({ vp: vpName, page: `종목상세 ${range.label}`, issues: r.problems });
      console.log(`❌ ${r.problems.join(", ")}`);
    } else {
      console.log(`✅`);
    }
  }

  // --- Asset chart modes (line vs candle) ---
  console.log("\n🕯️ 차트 모드:");
  for (const mode of ["라인", "캔들"]) {
    process.stdout.write(`  ${mode.padEnd(10)}`);
    await p.goto(`${BASE}/#asset/005930`, { waitUntil: "networkidle", timeout: 15000 });
    await p.waitForTimeout(2000);
    await p.locator(".asset-range-chip").nth(5).click(); // 1개월
    await p.waitForTimeout(2000);
    const modeIdx = mode === "라인" ? 0 : 1;
    await p.locator(".asset-toggle-chip").nth(modeIdx).click();
    await p.waitForTimeout(2000);
    await p.screenshot({ path: join(OUT, `${vpName}-chartmode-${mode}.png`), fullPage: false });
    const r = await checkPage(p);
    stats.total++;
    if (r.problems.length) {
      stats.issues++;
      allIssues.push({ vp: vpName, page: `차트모드 ${mode}`, issues: r.problems });
      console.log(`❌ ${r.problems.join(", ")}`);
    } else {
      console.log(`✅`);
    }
  }

  // --- Risk tabs ---
  console.log("\n🛡️ 리스크 탭:");
  for (const tab of RISK_TABS) {
    process.stdout.write(`  ${tab.label.padEnd(12)}`);
    await p.goto(`${BASE}/#risk`, { waitUntil: "networkidle", timeout: 15000 });
    await p.waitForTimeout(2000);
    await p.locator("button.asset-range-chip").nth(tab.idx).click();
    await p.waitForTimeout(3000);
    await p.screenshot({ path: join(OUT, `${vpName}-risk-${tab.idx}.png`), fullPage: false });
    const r = await checkPage(p);
    stats.total++;
    if (r.problems.length) {
      stats.issues++;
      allIssues.push({ vp: vpName, page: `리스크 ${tab.label}`, issues: r.problems });
      console.log(`❌ ${r.problems.join(", ")}`);
    } else {
      console.log(`✅`);
    }
  }

  await ctx.close();
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const allIssues = [];
  const stats = { total: 0, issues: 0 };

  console.log("╔══════════════════════════════════════════╗");
  console.log("║   AlphaTrade GUI Full Audit — PC+Mobile  ║");
  console.log("╚══════════════════════════════════════════╝");
  console.log(`Output: ${OUT}\n`);

  if (!MOBILE_ONLY) {
    await runViewport(browser, "PC", { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 }, allIssues, stats);
  }

  if (!PC_ONLY) {
    await runViewport(browser, "Mobile", { ...devices["iPhone 14"] }, allIssues, stats);

    // Landscape
    console.log("\n📱 Mobile Landscape:");
    const lCtx = await browser.newContext({ viewport: { width: 844, height: 390 }, deviceScaleFactor: 2, isMobile: true });
    const lp = await lCtx.newPage();
    for (const pg of [PAGES[0], PAGES[4], PAGES[9]]) { // command, analysis, asset
      process.stdout.write(`  ${pg.label.padEnd(22)}`);
      await lp.goto(`${BASE}/#${pg.hash}`, { waitUntil: "networkidle", timeout: 15000 });
      await lp.waitForTimeout(4000);
      await lp.screenshot({ path: join(OUT, `landscape-${pg.name}.png`), fullPage: false });
      const r = await checkPage(lp);
      stats.total++;
      if (r.problems.length) {
        stats.issues++;
        allIssues.push({ vp: "Landscape", page: pg.label, issues: r.problems });
        console.log(`❌ ${r.problems.join(", ")}`);
      } else {
        console.log(`✅`);
      }
    }
    await lCtx.close();
  }

  await browser.close();

  // Summary
  console.log("\n╔══════════════════════════════════════════╗");
  console.log("║              AUDIT SUMMARY               ║");
  console.log("╚══════════════════════════════════════════╝");
  console.log(`  Total tests:  ${stats.total}`);
  console.log(`  Passed:       ${stats.total - stats.issues}`);
  console.log(`  Issues:       ${stats.issues}`);
  console.log(`  Screenshots:  ${OUT}`);

  if (allIssues.length) {
    console.log("\n🔴 Issues:");
    for (const i of allIssues) {
      console.log(`  [${i.vp}] ${i.page}: ${i.issues.join(", ")}`);
    }
  } else {
    console.log("\n🟢 All tests passed!");
  }
}

main().catch(console.error);
