"use client";

import { NewsItem } from "@/lib/api";

export default function NewsFeed({ items }: { items: NewsItem[] }) {
  if (items.length === 0) {
    return <div className="empty">No recent news.</div>;
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, maxHeight: 420, overflowY: "auto" }}>
      {items.map((n) => (
        <div key={n.id} style={{ borderBottom: "1px solid var(--border)", paddingBottom: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
            <span className={`pill ${n.sentiment}`}>{n.sentiment}</span>
            <span style={{ color: "var(--muted)", fontSize: 11 }}>
              {n.symbol ?? "market"} · {n.category} · impact {n.impact_estimate.toFixed(2)}
            </span>
          </div>
          <div style={{ fontSize: 13 }}>{n.headline}</div>
          <div style={{ color: "var(--muted)", fontSize: 11, marginTop: 2 }}>
            {n.source} · {new Date(n.published_at).toLocaleString()}
          </div>
        </div>
      ))}
    </div>
  );
}
