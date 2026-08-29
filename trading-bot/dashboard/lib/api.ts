const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`);
  return res.json();
}

export interface DashboardSummary {
  mode: "paper" | "live";
  equity: number;
  starting_equity: number;
  cash: number;
  daily_pnl: number;
  open_positions_count: number;
  trades_today_count: number;
  win_rate_pct: number;
  max_drawdown_pct: number;
  total_closed_trades: number;
  kill_switch_active: boolean;
  daily_loss_kill_switch_active: boolean;
  circuit_breaker_tripped: boolean;
  consecutive_losses: number;
}

export interface Position {
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  stop_loss: number | null;
  take_profit: number | null;
  trailing_stop_price: number | null;
  unrealized_pnl: number;
  opened_at: string;
}

export interface JournalEntry {
  timestamp: string;
  symbol: string;
  decision: string;
  confidence: number;
  score_breakdown: Record<string, number>;
  was_executed: boolean;
  rejection_reason: string | null;
  rejection_detail: string;
  reasoning: string;
  market_regime: string;
}

export interface NewsItem {
  id: string;
  symbol: string | null;
  headline: string;
  source: string;
  published_at: string;
  category: string;
  sentiment: string;
  sentiment_score: number;
  confidence: number;
  impact_estimate: number;
  url: string;
}

export interface RiskExposure {
  equity: number;
  exposure_by_symbol: Record<string, number>;
  max_exposure_per_asset_pct: number;
  max_risk_per_trade_pct: number;
  max_daily_loss_pct: number;
  max_trades_per_day: number;
  trades_today_count: number;
  max_simultaneous_positions: number;
  open_positions_count: number;
  consecutive_loss_circuit_breaker: number;
  consecutive_losses: number;
  circuit_breaker_cooldown_until: string | null;
  symbol_cooldowns: Record<string, string>;
}

export const api = {
  summary: () => get<DashboardSummary>("/api/dashboard/summary"),
  positions: () => get<Position[]>("/api/positions/open"),
  journal: (limit = 100) => get<JournalEntry[]>(`/api/trades/journal?limit=${limit}`),
  recentTrades: (limit = 50) => get("/api/trades/recent?limit=" + limit),
  news: (limit = 50) => get<NewsItem[]>(`/api/news/recent?limit=${limit}`),
  risk: () => get<RiskExposure>("/api/risk/exposure"),
  engageKillSwitch: (reason: string) => post("/api/kill-switch/engage", { reason }),
  resumeKillSwitch: () => post("/api/kill-switch/resume"),
  killSwitchStatus: () => get("/api/kill-switch/status"),
};
