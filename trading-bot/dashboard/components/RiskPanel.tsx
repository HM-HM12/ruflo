"use client";

import { RiskExposure } from "@/lib/api";

export default function RiskPanel({ risk }: { risk: RiskExposure }) {
  const symbols = Object.entries(risk.exposure_by_symbol);
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12, fontSize: 13 }}>
        <div>Trades today: <b>{risk.trades_today_count} / {risk.max_trades_per_day}</b></div>
        <div>Open positions: <b>{risk.open_positions_count} / {risk.max_simultaneous_positions}</b></div>
        <div>Max risk/trade: <b>{risk.max_risk_per_trade_pct}%</b></div>
        <div>Max daily loss: <b>{risk.max_daily_loss_pct}%</b></div>
        <div>Consecutive losses: <b>{risk.consecutive_losses} / {risk.consecutive_loss_circuit_breaker}</b></div>
        <div>Max exposure/asset: <b>{risk.max_exposure_per_asset_pct}%</b></div>
      </div>
      {risk.circuit_breaker_cooldown_until && (
        <div className="alert-banner">Circuit breaker active until {new Date(risk.circuit_breaker_cooldown_until).toLocaleTimeString()}</div>
      )}
      <h2 style={{ marginTop: 16 }}>Exposure by symbol</h2>
      {symbols.length === 0 ? (
        <div className="empty">No exposure.</div>
      ) : (
        <table>
          <thead><tr><th>Symbol</th><th>Exposure ($)</th></tr></thead>
          <tbody>
            {symbols.map(([sym, val]) => (
              <tr key={sym}><td>{sym}</td><td>{val.toLocaleString()}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
