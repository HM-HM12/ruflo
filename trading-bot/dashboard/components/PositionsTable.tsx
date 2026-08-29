"use client";

import { Position } from "@/lib/api";

export default function PositionsTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return <div className="empty">No open positions.</div>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Stop</th><th>Target</th><th>Unrealized P/L</th>
        </tr>
      </thead>
      <tbody>
        {positions.map((p) => (
          <tr key={p.symbol}>
            <td>{p.symbol}</td>
            <td><span className={`pill ${p.side === "buy" ? "bullish" : "bearish"}`}>{p.side.toUpperCase()}</span></td>
            <td>{p.quantity.toFixed(4)}</td>
            <td>{p.entry_price.toFixed(2)}</td>
            <td>{p.stop_loss?.toFixed(2) ?? "—"}</td>
            <td>{p.take_profit?.toFixed(2) ?? "—"}</td>
            <td className={p.unrealized_pnl >= 0 ? "value positive" : "value negative"} style={{ fontSize: 13 }}>
              {p.unrealized_pnl >= 0 ? "+" : ""}{p.unrealized_pnl.toFixed(2)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
