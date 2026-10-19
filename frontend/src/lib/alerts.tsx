// The call desk's real-time alerts (call_analyzer/alerts.py), polled for admins on every page: a toast for each new
// one, a desktop notification too while the app is in the background, and the list for the team board.
import * as React from "react";
import { toastManager } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { href, navigate } from "@/lib/router";
import { t } from "@/lib/i18n";

export type DeskAlertKind = "idle" | "long_call" | "no_answer_streak" | "contact_rate_drop" | "callback_overdue" | "missed_call";

export type DeskAlert = {
  /** The same while its cause lasts. */
  id: string;
  kind: DeskAlertKind;
  level: "warning" | "critical";
  title: string;
  detail: string;
  /** When the cause started (the idle time, the call, the streak, the window, the callback's due time). */
  since: string;
  agent: string | null;
  agent_name: string | null;
  op_id: number | null;
};

type AlertsContextValue = { alerts: DeskAlert[] | null; reload: () => Promise<void> };

const AlertsContext = React.createContext<AlertsContextValue | null>(null);

export function useAlerts(): AlertsContextValue {
  const ctx = React.useContext(AlertsContext);
  if (!ctx) throw new Error("useAlerts must be used within AlertsProvider");
  return ctx;
}

const POLL_MS = 15_000;
const TEAM_BOARD = href("operations", null, { tab: "team" });

function announce(alert: DeskAlert): void {
  toastManager.add({
    actionProps: { children: t("alerts.teamBoard"), onClick: () => navigate(TEAM_BOARD) },
    description: alert.detail,
    title: alert.title,
    type: alert.level === "critical" ? "error" : "warning",
  });
  if (document.visibilityState === "hidden" && "Notification" in window && Notification.permission === "granted") {
    const note = new Notification(alert.title, { body: alert.detail, tag: alert.id });
    note.onclick = () => {
      window.focus();
      navigate(TEAM_BOARD);
    };
  }
}

/** `enabled={false}` for agent (sales) accounts: the alerts are about the whole team. */
export function AlertsProvider({
  children,
  enabled = true,
}: {
  children: React.ReactNode;
  enabled?: boolean;
}): React.ReactElement {
  const [alerts, setAlerts] = React.useState<DeskAlert[] | null>(null);
  const timer = React.useRef<number | undefined>(undefined);
  // The alerts already shown; null until the first poll, whose alerts aren't announced (they aren't news).
  const seen = React.useRef<Set<string> | null>(null);

  const reload = React.useCallback(async () => {
    window.clearTimeout(timer.current);
    try {
      const { alerts: found } = await api<{ alerts: DeskAlert[] }>("/api/operations/alerts");
      if (seen.current) {
        for (const alert of found) if (!seen.current.has(alert.id)) announce(alert);
      }
      seen.current = new Set(found.map((a) => a.id));
      setAlerts(found);
    } catch {
      // keep the last state; the next poll retries
    }
    timer.current = window.setTimeout(reload, POLL_MS);
  }, []);

  React.useEffect(() => {
    if (!enabled) return;
    reload();
    return () => window.clearTimeout(timer.current);
  }, [reload, enabled]);

  const value = React.useMemo(() => ({ alerts, reload }), [alerts, reload]);
  return <AlertsContext.Provider value={value}>{children}</AlertsContext.Provider>;
}
