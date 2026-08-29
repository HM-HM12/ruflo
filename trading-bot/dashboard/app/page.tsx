"use client";

import { useCallback, useEffect, useState } from "react";
import { api, DashboardSummary, JournalEntry, NewsItem, Position, RiskExposure, WS_URL } from "@/lib/api";
import SummaryBar from "@/components/SummaryBar";
import PositionsTable from "@/components/PositionsTable";
import JournalTable from "@/components/JournalTable";
import NewsFeed from "@/components/NewsFeed";
import RiskPanel from "@/components/RiskPanel";
import KillSwitchButton from "@/components/KillSwitchButton";

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [risk, setRisk] = useState<RiskExposure | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [s, p, j, n, r] = await Promise.all([
        api.summary(), api.positions(), api.journal(50), api.news(30), api.risk(),
      ]);
      setSummary(s); setPositions(p); setJournal(j); setNews(n); setRisk(r);
      setError(null);
    } catch (e) {
      setError("Could not reach the trading bot API. Is the backend running?");
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 8000);

    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(WS_URL);
      ws.onmessage = () => refresh();
    } catch {
      // WebSocket is a nice-to-have; polling above covers correctness.
    }

    return () => {
      clearInterval(interval);
      ws?.close();
    };
  }, [refresh]);

  return (
    <div className="page">
      <div className="header">
        <div className="title">🤖 AI Trading Bot</div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {summary && <span className={`badge ${summary.mode}`}>{summary.mode} trading</span>}
          {summary && (
            <KillSwitchButton
              active={summary.kill_switch_active}
              onChanged={refresh}
            />
          )}
        </div>
      </div>

      {error && <div className="alert-banner">{error}</div>}
      {summary?.daily_loss_kill_switch_active && (
        <div className="alert-banner">Daily loss limit reached — no new trades will open today.</div>
      )}

      {summary && <SummaryBar summary={summary} />}

      <div className="grid-2">
        <div className="panel">
          <h2>Open Positions</h2>
          <PositionsTable positions={positions} />
        </div>
        <div className="panel">
          <h2>Risk Exposure</h2>
          {risk && <RiskPanel risk={risk} />}
        </div>
      </div>

      <div className="grid-2">
        <div className="panel">
          <h2>News Feed</h2>
          <NewsFeed items={news} />
        </div>
        <div className="panel">
          <h2>Trading Journal (incl. rejected setups)</h2>
          <div style={{ maxHeight: 420, overflowY: "auto" }}>
            <JournalTable entries={journal} />
          </div>
        </div>
      </div>
    </div>
  );
}
