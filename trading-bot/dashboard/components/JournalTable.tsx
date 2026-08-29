"use client";

import { JournalEntry } from "@/lib/api";

export default function JournalTable({ entries }: { entries: JournalEntry[] }) {
  if (entries.length === 0) {
    return <div className="empty">No AI decisions recorded yet.</div>;
  }
  return (
    <table>
      <thead>
        <tr>
          <th>Time</th><th>Symbol</th><th>Decision</th><th>Confidence</th><th>Regime</th><th>Status</th><th>Reasoning</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e, i) => (
          <tr key={i}>
            <td>{new Date(e.timestamp).toLocaleString()}</td>
            <td>{e.symbol}</td>
            <td><span className={`pill ${e.decision}`}>{e.decision.replace("_", " ")}</span></td>
            <td>{e.confidence.toFixed(1)}</td>
            <td>{e.market_regime}</td>
            <td>
              {e.was_executed ? (
                <span className="pill bullish">EXECUTED</span>
              ) : (
                <span className="pill neutral" title={e.rejection_detail}>{e.rejection_reason ?? "rejected"}</span>
              )}
            </td>
            <td style={{ maxWidth: 320, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={e.reasoning}>
              {e.reasoning}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
