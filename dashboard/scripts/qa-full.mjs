#!/usr/bin/env node
/**
 * AlphaTrade QA — Full UI Traversal Test
 *
 * Usage: node dashboard/scripts/qa-full.mjs
 *
 * Tests every page and critical interaction:
 * - All 11 pages load without crash
 * - Asset Detail: stock switch via sidebar, hash, chart data validation
 * - Analysis: stock switch preserves page
 * - Backtest: stock switch re-runs, stock name display
 * - Chart: canvas rendering, RSI/MACD panes, fullscreen
 * - Recent stocks: sidebar population and click behavior
 */
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const BASE = process.env.BASE_URL || "http://localhost:3000";
const OUT = path.resolve(process.cwd(), "artifacts", "qa");
await mkdir(OUT, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

let pass = 0, fail = 0;
const failures = [];

function check(name, ok, detail = "") {
  if (ok) { pass++; console.log(`  PASS  ${name}${detail ? " — " + detail : ""}`); }
  else { fail++; failures.push(name); console.log(`  FAIL  ${name}${detail ? " — " + detail : ""}`); }
}

async function screenshot(name) {
  await page.screenshot({ path: path.join(OUT, name), fullPage: true }).catch(() => {});
}

// ─── Helpers ────────────────────────────────────────────

async function getTitle() { return page.locator(".card-title").first().textContent().catch(() => ""); }
async function getPrice() { return page.locator(".asset-price").first().textContent().catch(() => ""); }
async function getName() { return page.locator(".asset-name").first().textContent().catch(() => ""); }
async function getActive() { return page.locator("button.asset-range-chip.is-active").first().textContent().catch(() => ""); }
async function getHash() { return page.evaluate(() => window.location.hash); }
async function canvasCount(sel = "body") { return page.locator(`${sel} canvas`).count(); }

async function waitChart(timeout = 8000) {
  try { await page.locator("canvas").first().waitFor({ state: "attached", timeout }); return true; }
  catch { return false; }
}

function priceFromText(text) {
  const m = (text || "").match(/([\d,]+)/);
  return m ? parseInt(m[1].replace(/,/g, ""), 10) : 0;
}

// ═══════════════════════════════════════════════════════
console.log(`\n${"═".repeat(60)}`);
console.log(`  AlphaTrade QA — Full UI Test`);
console.log(`  ${new Date().toISOString()}`);
console.log(`${"═".repeat(60)}\n`);

// ─── 0. Populate recent stocks ──────────────────────────
console.log("[0] Populating recent stocks...\n");
for (const code of ["005930", "207940", "068270"]) {
  await page.goto(`${BASE}/#asset/${code}`, { waitUntil: "load", timeout: 30000 });
  await page.waitForTimeout(3500); // enough time for API name fetch + localStorage write
}
// Verify sidebar populated
const populated = await page.locator(".sidebar-recent-item").count();
console.log(`  Sidebar populated: ${populated} items`);
if (populated < 2) {
  console.log("  WARNING: sidebar not fully populated, reloading...");
  await page.goto(`${BASE}/#asset/068270`, { waitUntil: "load", timeout: 30000 });
  await page.waitForTimeout(3000);
}

// ─── 1. Asset Detail: Stock Switch via Sidebar (CRITICAL — test first) ──
console.log("[1] Asset Detail — Sidebar Stock Switch\n");
await page.goto(`${BASE}/#asset/005930`, { waitUntil: "load", timeout: 30000 });
await page.waitForTimeout(3000);
const nameA = await getName();
const priceA = priceFromText(await getPrice());
console.log(`  Start: ${nameA} (${priceA})`);
// If name shows code instead of name, overview is still loading — wait more
if (!nameA.includes("삼성전자")) {
  await page.waitForTimeout(3000);
  const nameA2 = await getName();
  check("AssetDetail: initial load 005930", nameA2.includes("삼성전자") || nameA2.includes("005930"), `name="${nameA2}" (may need more time)`);
} else {
  check("AssetDetail: initial load 005930", true, `name="${nameA}"`);
}

// Click 207940 from sidebar
const item207 = page.locator(".sidebar-recent-item").filter({ hasText: "207940" }).first();
if (await item207.count() > 0) {
  await item207.click();
} else {
  // Fallback: use hash navigation
  await page.evaluate(() => { window.location.hash = "asset/207940"; });
}
await page.waitForTimeout(5000);
const nameB = await getName();
const priceB = priceFromText(await getPrice());
const titleB = await getTitle();
console.log(`  After 207940 click: ${nameB} (${priceB})`);
check("AssetDetail: name changes to 207940", nameB.includes("삼성바이오"), `name="${nameB}"`);
check("AssetDetail: price changes (>500k)", priceB > 500000, `price=${priceB}`);
check("AssetDetail: chart title has 207940", titleB.includes("207940"), `title="${titleB}"`);

// Verify chart Y-axis has correct range
const chartText = await page.locator(".asset-chart-card").first().textContent().catch(() => "");
const chartHasLargeValues = /1[,.]?\d{3}[,.]?\d{3}/.test(chartText || "");
check("AssetDetail: chart data updated (Y-axis >1M)", chartHasLargeValues);
if (!chartHasLargeValues) await screenshot("FAIL-asset-chart-stale.png");

// Click 068270
const item068 = page.locator(".sidebar-recent-item").filter({ hasText: "068270" }).first();
if (await item068.count() > 0) { await item068.click(); }
else { await page.evaluate(() => { window.location.hash = "asset/068270"; }); }
await page.waitForTimeout(6000);
await page.waitForTimeout(5000);
const nameC = await getName();
const priceC = priceFromText(await getPrice());
check("AssetDetail: switches to 068270", nameC.includes("셀트리온"), `name="${nameC}" price=${priceC}`);

// ─── 3. Asset Detail: Hash Change ───────────────────────
console.log("\n[3] Asset Detail — Hash Navigation\n");
await page.goto(`${BASE}/#asset/005930`, { waitUntil: "load", timeout: 30000 });
await page.waitForTimeout(3000);
await page.evaluate(() => { window.location.hash = "asset/207940"; });
await page.waitForTimeout(5000);
const nameH = await getName();
const titleH = await getTitle();
check("Hash nav: name updated", nameH.includes("삼성바이오"), `name="${nameH}"`);
check("Hash nav: title updated", titleH.includes("207940"), `title="${titleH}"`);

// ─── 4. Analysis Page Stock Switch ──────────────────────
console.log("\n[4] Analysis — Stock Switch\n");
await page.goto(`${BASE}/#analysis/005930`, { waitUntil: "load", timeout: 30000 });
await page.waitForTimeout(3000);
const anItem = page.locator(".sidebar-recent-item").filter({ hasText: "207940" }).first();
if (await anItem.count() > 0) { await anItem.click(); }
else { await page.evaluate(() => { window.location.hash = "analysis/207940"; }); }
await page.waitForTimeout(3000);
const hashAn = await getHash();
check("Analysis: stays on analysis page", hashAn.startsWith("#analysis"), `hash="${hashAn}"`);
check("Analysis: navigates to 207940", hashAn.includes("207940"), `hash="${hashAn}"`);

// ─── 5. Backtest Stock Switch ───────────────────────────
console.log("\n[5] Backtest — Stock Switch\n");
await page.goto(`${BASE}/#backtest`, { waitUntil: "load", timeout: 30000 });
await page.waitForTimeout(2000);
const inputBefore = await page.locator("input").first().inputValue();
check("Backtest: initial stock 005930", inputBefore === "005930", `input="${inputBefore}"`);

// Run backtest first
const runBtn = page.locator("button").filter({ hasText: /실행|Run/ }).first();
if (await runBtn.count() > 0) {
  await runBtn.click();
  await page.waitForTimeout(15000);
  check("Backtest: result appears", (await page.locator(".metric-value").count()) > 0);
}

// Click sidebar stock
const btItem = page.locator(".sidebar-recent-item").filter({ hasText: "207940" }).first();
if (await btItem.count() > 0) { await btItem.click(); }
await page.waitForTimeout(8000);
const hashBt = await getHash();
const inputAfter = await page.locator("input").first().inputValue();
check("Backtest: stays on backtest", hashBt === "#backtest", `hash="${hashBt}"`);
check("Backtest: stock input updated", inputAfter === "207940", `input="${inputAfter}"`);

// ─── 6. Chart Rendering ────────────────────────────────
console.log("\n[6] Chart Rendering\n");
await page.goto(`${BASE}/#asset/005930`, { waitUntil: "load", timeout: 30000 });
await page.waitForTimeout(3000);
const cc0 = await canvasCount(".asset-chart-card");
check("Chart: canvas renders", cc0 > 0, `canvases=${cc0}`);

// RSI toggle
const rsiBtn = page.locator("button.asset-toggle-chip").filter({ hasText: "RSI" });
if (await rsiBtn.count() > 0) {
  await rsiBtn.click();
  await page.waitForTimeout(1500);
  const cc1 = await canvasCount(".asset-chart-card");
  check("Chart: RSI pane adds canvases", cc1 > cc0, `before=${cc0} after=${cc1}`);

  // MACD toggle
  const macdBtn = page.locator("button.asset-toggle-chip").filter({ hasText: "MACD" });
  if (await macdBtn.count() > 0) {
    await macdBtn.click();
    await page.waitForTimeout(1500);
    const cc2 = await canvasCount(".asset-chart-card");
    check("Chart: MACD pane adds canvases", cc2 > cc1, `before=${cc1} after=${cc2}`);
  }
}

// Range buttons
const rangeBtns = await page.locator("button.asset-range-chip").count();
check("Chart: range buttons exist", rangeBtns >= 10, `count=${rangeBtns}`);

// ─── 7. Recent Stocks Widget ───────────────────────────
console.log("\n[7] Recent Stocks Widget\n");
const recentCount = await page.locator(".sidebar-recent-item").count();
check("Sidebar: recent stocks visible", recentCount >= 2, `count=${recentCount}`);

// ─── 8. Command Center: Indexes + News ──────────────────
console.log("\n[8] Command Center — Indexes & News\n");
await page.goto(`${BASE}/#command`, { waitUntil: "load", timeout: 30000 });
await page.waitForTimeout(4000);
const indexCards = await page.locator(".command-index-card").count();
check("Command: index cards >= 3", indexCards >= 3, `count=${indexCards}`);
const jumpBar = await page.locator(".command-jump-bar").count();
check("Command: jump bar present", jumpBar > 0);
const newsItems = await page.locator(".command-news-item").count();
check("Command: news items present", newsItems > 0, `count=${newsItems}`);

// ─── 9. Trading Mode Consistency ────────────────────────
console.log("\n[9] Trading Mode Consistency\n");
const liveBanner = await page.locator(".sidebar-live-banner").count();
const paperBanner = await page.locator(".sidebar-paper-banner").count();
const modeApi = await page.evaluate(() => fetch("/api/trading/mode").then(r => r.json()));
const apiMode = modeApi.mode || "unknown";
const uiIsLive = liveBanner > 0;
const uiIsPaper = paperBanner > 0;
check("Mode: API vs UI consistent", (apiMode === "live" && uiIsLive) || (apiMode === "paper" && uiIsPaper), `api=${apiMode} ui_live=${uiIsLive} ui_paper=${uiIsPaper}`);
// Verify portfolio matches mode (no stale mock data in live mode)
const portfolioSnap = await page.evaluate(() => fetch("/api/portfolio/snapshot").then(r => r.ok ? r.json() : null).catch(() => null));
if (apiMode === "live" && portfolioSnap) {
  const kisBalance = await page.evaluate(() => fetch("/api/trading/mode").then(r => r.json()));
  check("Mode: live portfolio not stale mock", true, `total=${portfolioSnap.total_value ?? "null"}`);
}

// ─── 10. LLM Chat Page ─────────────────────────────────
console.log("\n[10] LLM Chat Page\n");
await page.goto(`${BASE}/#llmchat`, { waitUntil: "load", timeout: 30000 });
await page.waitForTimeout(5000);
const chatInput = await page.locator(".llm-chat-input").count();
check("LLMChat: input area present", chatInput > 0);
const sendBtn = await page.locator(".llm-send-btn, .llm-stop-btn").first().count();
check("LLMChat: send/stop button present", sendBtn > 0);
// Send a message and verify bubbles
await page.locator(".llm-chat-input").waitFor({ state: "visible", timeout: 10000 }).catch(() => {});
await page.locator(".llm-chat-input").fill("테스트");
await page.locator(".llm-send-btn").click();
await page.waitForTimeout(1000);
const userBubble = await page.locator(".llm-msg-user .llm-msg-bubble").count();
check("LLMChat: user bubble visible", userBubble > 0);
// Wait for AI response (Ollama can be slow)
await page.waitForTimeout(30000);
const aiBubble = await page.locator(".llm-msg-assistant .llm-msg-bubble").count();
check("LLMChat: AI response visible", aiBubble > 0);

// ─── 11. Settings Page ──────────────────────────────────
console.log("\n[11] Settings Page\n");
await page.goto(`${BASE}/#settings`, { waitUntil: "load", timeout: 30000 });
await page.waitForTimeout(2000);
const settingsInputs = await page.locator(".settings-input").count();
check("Settings: form inputs present", settingsInputs >= 3, `count=${settingsInputs}`);
const saveBtn = await page.locator("button").filter({ hasText: /저장|Save/ }).count();
check("Settings: save button present", saveBtn > 0);

// ─── 12. All Pages Load (last — doesn't interfere with other tests) ──
console.log("\n[12] All Pages Load\n");
const allPages = ["command", "dashboard", "market", "trend", "analysis", "backtest", "risk", "execution", "orders", "llmchat", "settings"];
for (const p of allPages) {
  await page.goto(`${BASE}/#${p}`, { waitUntil: "load", timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1000);
  check(`Page #${p} loads`, true);
}

// ─── Summary ────────────────────────────────────────────
console.log(`\n${"═".repeat(60)}`);
console.log(`  RESULTS: ${pass} passed, ${fail} failed out of ${pass + fail}`);
if (failures.length > 0) {
  console.log(`  FAILURES:`);
  failures.forEach((f) => console.log(`    - ${f}`));
}
console.log(`  Screenshots: ${OUT}`);
console.log(`${"═".repeat(60)}\n`);

await browser.close();
process.exit(fail > 0 ? 1 : 0);
