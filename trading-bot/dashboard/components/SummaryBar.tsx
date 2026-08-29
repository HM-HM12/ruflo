"use client";

import { DashboardSummary } from "@/lib/api";

function fmtCurrency(n: number): string {
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

export default function SummaryBar({ summary }: { summary: DashboardSummary }) {
  const totalReturnPct = summary.starting_equity
    ? ((summary.equity - summary.starting_equity) / summary.starting_equity) * 100
    : 0;

  const cards = [
    { label: "Equity", value: fmtCurrency(summary.equity), cls: "" },
    { label: "Total Return", value: `${totalReturnPct >= 0 ? "+" : ""}${totalReturnPct.toFixed(2)}%`, cls: totalReturnPct >= 0 ? "positive" : "negative" },
    { label: "Daily P/L", value: fmtCurrency(summary.daily_pnl), cls: summary.daily_pnl >= 0 ? "positive" : "negative" },
    { label: "Open Positions", value: String(summary.open_positions_count), cls: "" },
    { label: "Trades Today", value: String(summary.trades_today_count), cls: "" },
    { label: "Win Rate", value: `${summary.win_rate_pct.toFixed(1)}%`, cls: "" },
    { label: "Max Drawdown", value: `${summary.max_drawdown_pct.toFixed(2)}%`, cls: "negative" },
    { label: "Consecutive Losses", value: String(summary.consecutive_losses), cls: summary.consecutive_losses > 0 ? "negative" : "" },
  ];

  return (
    <div className="summary-grid">
      {cards.map((c) => (
        <div className="card" key={c.label}>
          <div className="label">{c.label}</div>
          <div className={`value ${c.cls}`}>{c.value}</div>
        </div>
      ))}
    </div>
  );
}
