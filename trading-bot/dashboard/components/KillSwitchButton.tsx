"use client";

import { useState } from "react";
import { api } from "@/lib/api";

export default function KillSwitchButton({ active, onChanged }: { active: boolean; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);

  async function handleClick() {
    setBusy(true);
    try {
      if (active) {
        await api.resumeKillSwitch();
      } else {
        const reason = window.prompt("Reason for emergency stop?", "manual dashboard stop");
        if (reason === null) {
          setBusy(false);
          return;
        }
        await api.engageKillSwitch(reason);
      }
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <button className={`kill-switch-btn ${active ? "resume" : ""}`} onClick={handleClick} disabled={busy}>
      {active ? "Resume Trading" : "Emergency Stop"}
    </button>
  );
}
