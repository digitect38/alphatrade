#!/usr/bin/env node
/**
 * AlphaTrade MCP Server
 *
 * Exposes trading system tools via the Model Context Protocol (MCP).
 * Communicates over stdio with JSON-RPC 2.0.
 *
 * Tools:
 *   kis_price       — Real-time stock price from KIS
 *   backtest        — Run backtest with production ensemble engine
 *   signal          — Latest trading signal for a stock
 *   market_overview — Market indexes + top movers
 *   news            — Recent news for a stock
 *   portfolio       — Current portfolio status
 */

import { createInterface } from "readline";

const API_BASE = process.env.ALPHATRADE_API || "http://localhost:8000";

// --- Helpers ---

async function apiGet(path) {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) throw new Error(`API ${resp.status}: ${path}`);
  return resp.json();
}

async function apiPost(path, body) {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`API ${resp.status}: ${path}`);
  return resp.json();
}

function jsonRpc(id, result) {
  return JSON.stringify({ jsonrpc: "2.0", id, result });
}

function jsonRpcError(id, code, message) {
  return JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } });
}

// --- Tool Definitions ---

const TOOLS = [
  {
    name: "kis_price",
    description: "Get real-time stock price from KIS API. Returns current price, change %, volume.",
    inputSchema: {
      type: "object",
      properties: {
        stock_code: { type: "string", description: "6-digit stock code (e.g., 005930)" },
      },
      required: ["stock_code"],
    },
  },
  {
    name: "backtest",
    description: "Run backtest with production ensemble signal engine. Returns return %, MDD, Sharpe, trades.",
    inputSchema: {
      type: "object",
      properties: {
        stock_code: { type: "string", description: "6-digit stock code" },
        strategy: { type: "string", enum: ["ensemble", "momentum", "mean_reversion", "conservative", "aggressive"], default: "ensemble" },
        duration: { type: "string", enum: ["3M", "6M", "1Y", "2Y", "3Y", "5Y", "MAX"], default: "1Y" },
      },
      required: ["stock_code"],
    },
  },
  {
    name: "signal",
    description: "Get latest trading signal (BUY/SELL/HOLD) with strength and component breakdown.",
    inputSchema: {
      type: "object",
      properties: {
        stock_code: { type: "string", description: "6-digit stock code" },
      },
      required: ["stock_code"],
    },
  },
  {
    name: "market_overview",
    description: "Get market overview: KOSPI, KOSDAQ, NASDAQ, DOW, BTC, USD/KRW indexes + top movers.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "news",
    description: "Get recent news articles related to a stock.",
    inputSchema: {
      type: "object",
      properties: {
        stock_code: { type: "string", description: "6-digit stock code" },
      },
      required: ["stock_code"],
    },
  },
  {
    name: "portfolio",
    description: "Get current portfolio status: total value, cash, positions, daily P&L.",
    inputSchema: { type: "object", properties: {} },
  },
];

// --- Tool Handlers ---

async function handleTool(name, args) {
  switch (name) {
    case "kis_price": {
      const code = args.stock_code;
      const data = await apiGet(`/asset/${code}/overview`);
      return `${data.stock_name} (${code})\nPrice: ${data.current_price?.toLocaleString()}원\nChange: ${data.change_pct}%\nVolume: ${data.volume?.toLocaleString()}\nMarket: ${data.market}\nSector: ${data.sector}`;
    }

    case "backtest": {
      const code = args.stock_code;
      const strategy = args.strategy || "ensemble";
      const dur = args.duration || "1Y";
      const daysMap = { "3M": 90, "6M": 180, "1Y": 365, "2Y": 730, "3Y": 1095, "5Y": 1825, "MAX": 3650 };
      const days = daysMap[dur] || 365;
      const start = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
      const result = await apiPost("/strategy/backtest", {
        stock_code: code, strategy, initial_capital: 10000000,
        start_date: start, benchmark: "buy_and_hold", max_drawdown_stop: 0.08,
      });
      let text = `Backtest: ${code} / ${strategy} / ${dur}\n`;
      text += `Period: ${result.period_bars} bars\n`;
      text += `Return: ${result.total_return}%\n`;
      text += `Benchmark: ${result.benchmark_return}%\n`;
      text += `MDD: ${result.max_drawdown}%\n`;
      text += `Sharpe: ${result.sharpe_ratio}\n`;
      text += `Win Rate: ${result.win_rate}%\n`;
      text += `Trades: ${result.total_trades}\n`;
      text += `Final Capital: ${result.final_capital?.toLocaleString()}원`;
      if (result.statistical_warnings?.length) {
        text += `\n⚠ ${result.statistical_warnings.join(" / ")}`;
      }
      return text;
    }

    case "signal": {
      const data = await apiPost("/strategy/signal", { stock_code: args.stock_code, interval: "1d" });
      let text = `Signal: ${data.signal} (strength: ${data.strength})\n`;
      text += `Ensemble Score: ${data.ensemble_score}\n`;
      if (data.components?.length) {
        text += "Components:\n";
        for (const c of data.components) {
          text += `  ${c.name}: ${c.score} (weight: ${c.weight})\n`;
        }
      }
      if (data.reasons?.length) {
        text += `Reasons: ${data.reasons.join(", ")}`;
      }
      return text;
    }

    case "market_overview": {
      const [indexes, movers, mode] = await Promise.all([
        apiGet("/index/realtime"),
        apiGet("/market/movers?limit=10"),
        apiGet("/trading/mode"),
      ]);
      let text = `Mode: ${mode.mode} | KIS: ${mode.kis_base_url}\n\nIndexes:\n`;
      for (const idx of indexes.indexes || []) {
        text += `  ${idx.name}: ${idx.price?.toLocaleString()} (${idx.change_pct > 0 ? "+" : ""}${idx.change_pct}%)\n`;
      }
      text += `\nTop Movers:\n`;
      for (const m of (movers.movers || []).slice(0, 10)) {
        text += `  ${m.stock_name} (${m.stock_code}): ${Number(m.change_pct) > 0 ? "+" : ""}${m.change_pct}%\n`;
      }
      return text;
    }

    case "news": {
      const data = await apiGet(`/market/news/${args.stock_code}?limit=8`);
      if (!data?.length) return `No news found for ${args.stock_code}`;
      let text = `News for ${args.stock_code} (${data.length} articles):\n`;
      for (const n of data) {
        text += `  [${n.time?.slice(0, 10)}] ${n.title}\n`;
      }
      return text;
    }

    case "portfolio": {
      const [snap, positions] = await Promise.all([
        apiGet("/portfolio/snapshot").catch(() => null),
        apiGet("/portfolio/positions").catch(() => []),
      ]);
      let text = "";
      if (snap?.total_value != null) {
        text += `Total: ${snap.total_value?.toLocaleString()}원\nCash: ${snap.cash?.toLocaleString()}원\nDaily P&L: ${snap.daily_pnl?.toLocaleString()}원\nPositions: ${snap.positions_count}`;
      } else {
        text += "Portfolio snapshot not available";
      }
      if (Array.isArray(positions) && positions.length) {
        text += "\n\nHoldings:\n";
        for (const p of positions) {
          text += `  ${p.stock_code}: ${p.quantity} shares @ ${p.avg_price?.toLocaleString()}원\n`;
        }
      }
      return text;
    }

    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

// --- MCP Protocol Handler ---

const rl = createInterface({ input: process.stdin });

rl.on("line", async (line) => {
  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    return;
  }

  const { id, method, params } = msg;

  try {
    if (method === "initialize") {
      process.stdout.write(jsonRpc(id, {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "alphatrade-mcp", version: "1.0.0" },
      }) + "\n");
    } else if (method === "notifications/initialized") {
      // no response needed
    } else if (method === "tools/list") {
      process.stdout.write(jsonRpc(id, { tools: TOOLS }) + "\n");
    } else if (method === "tools/call") {
      const { name, arguments: args } = params;
      const result = await handleTool(name, args || {});
      process.stdout.write(jsonRpc(id, {
        content: [{ type: "text", text: result }],
      }) + "\n");
    } else {
      process.stdout.write(jsonRpcError(id, -32601, `Method not found: ${method}`) + "\n");
    }
  } catch (err) {
    process.stdout.write(jsonRpcError(id, -32000, err.message) + "\n");
  }
});
