/**
 * AlphaTrade GUI Screenshot Test — all pages
 *
 * Usage: npx playwright test scripts/gui_test.mjs
 *    or: node scripts/gui_test.mjs
 */

import { chromium } from "playwright";
import { mkdirSync, existsSync } from "fs";
import { join } from "path";

const BASE = "http://localhost:3000";
const OUT = join(process.cwd(), "capture", "gui-test-v1.4");

const PAGES = [
  { hash: "command", name: "01-command-center", wait: 3000 },
  { hash: "dashboard", name: "02-dashboard", wait: 2000 },
  { hash: "market", name: "03-market", wait: 2000 },
  { hash: "trend", name: "04-trend", wait: 2000 },
  { hash: "analysis", name: "05-analysis", wait: 4000 },
  { hash: "backtest", name: "06-backtest", wait: 3000 },
  { hash: "risk", name: "07-risk-pnl", wait: 2000 },
  { hash: "execution", name: "08-execution", wait: 2000 },
  { hash: "orders", name: "09-orders", wait: 2000 },
];

// Risk sub-tabs
const RISK_TABS = [
  { label: "VaR/CVaR", name: "07b-risk-var" },
  { label: "스트레스 테스트", name: "07c-risk-stress" },
  { label: "실전 점검", name: "07d-risk-prelaunch" },
];

async function main() {
  if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();

  const issues = [];

  console.log("=== AlphaTrade GUI Test v1.4 ===\n");

  for (const p of PAGES) {
    process.stdout.write(`  ${p.name}... `);
    try {
      await page.goto(`${BASE}/#${p.hash}`, { waitUntil: "networkidle", timeout: 15000 });
      await page.waitForTimeout(p.wait);

      // Check for visible errors
      const errorText = await page.evaluate(() => {
        const body = document.body.innerText;
        if (body.includes("Internal Server Error")) return "500 Internal Server Error";
        if (body.includes("Cannot read properties")) return "JS Error in page";
        if (body.includes("undefined")) {
          // Check if it's a data issue vs real error
          const cards = document.querySelectorAll(".card");
          for (const c of cards) {
            if (c.textContent?.includes("undefined")) return `"undefined" text found`;
          }
        }
        return null;
      });

      if (errorText) {
        issues.push({ page: p.name, issue: errorText });
        console.log(`WARN: ${errorText}`);
      } else {
        console.log("OK");
      }

      await page.screenshot({ path: join(OUT, `${p.name}.png`), fullPage: true });
    } catch (e) {
      issues.push({ page: p.name, issue: `Navigation error: ${e.message}` });
      console.log(`FAIL: ${e.message}`);
    }
  }

  // Risk sub-tabs
  await page.goto(`${BASE}/#risk`, { waitUntil: "networkidle", timeout: 15000 });
  await page.waitForTimeout(1500);

  for (const tab of RISK_TABS) {
    process.stdout.write(`  ${tab.name}... `);
    try {
      const btn = page.locator(`button.asset-range-chip:has-text("${tab.label}")`);
      if (await btn.count() > 0) {
        await btn.click();
        await page.waitForTimeout(2000);
        await page.screenshot({ path: join(OUT, `${tab.name}.png`), fullPage: true });
        console.log("OK");
      } else {
        // Try English label
        const enBtn = page.locator(`button.asset-range-chip`).nth(RISK_TABS.indexOf(tab) + 1);
        if (await enBtn.count() > 0) {
          await enBtn.click();
          await page.waitForTimeout(2000);
          await page.screenshot({ path: join(OUT, `${tab.name}.png`), fullPage: true });
          console.log("OK (en)");
        } else {
          issues.push({ page: tab.name, issue: "Tab button not found" });
          console.log("WARN: tab not found");
        }
      }
    } catch (e) {
      issues.push({ page: tab.name, issue: e.message });
      console.log(`FAIL: ${e.message}`);
    }
  }

  // Mobile viewport test
  process.stdout.write("  mobile-command... ");
  try {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${BASE}/#command`, { waitUntil: "networkidle", timeout: 15000 });
    await page.waitForTimeout(2000);
    await page.screenshot({ path: join(OUT, "10-mobile-command.png"), fullPage: true });
    console.log("OK");
  } catch (e) {
    issues.push({ page: "mobile", issue: e.message });
    console.log(`FAIL: ${e.message}`);
  }

  process.stdout.write("  mobile-risk... ");
  try {
    await page.goto(`${BASE}/#risk`, { waitUntil: "networkidle", timeout: 15000 });
    await page.waitForTimeout(2000);
    await page.screenshot({ path: join(OUT, "11-mobile-risk.png"), fullPage: true });
    console.log("OK");
  } catch (e) {
    issues.push({ page: "mobile-risk", issue: e.message });
    console.log(`FAIL: ${e.message}`);
  }

  await browser.close();

  console.log(`\n=== Results ===`);
  console.log(`Screenshots: ${OUT}`);
  console.log(`Total pages: ${PAGES.length + RISK_TABS.length + 2}`);
  console.log(`Issues: ${issues.length}`);
  if (issues.length > 0) {
    console.log("\nIssues found:");
    for (const i of issues) {
      console.log(`  [${i.page}] ${i.issue}`);
    }
  } else {
    console.log("\nAll pages rendered without errors.");
  }
}

main().catch(console.error);
