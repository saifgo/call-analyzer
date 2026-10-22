// Shared by the call desk, the team board and the wallboard (pages/operations*.tsx, pages/wallboard.tsx).
import * as React from "react";
import { parseDate, shortName } from "@/lib/format";
import type { OpAgentState, OpCall, OpGoalMetric, OpOutcome, OpPause, OpProgress } from "@/lib/types";
import { labels, t } from "@/lib/i18n";

type Variant = "success" | "info" | "warning" | "error" | "secondary";

/** Badge colour of each CRM opportunity stage. */
export const STAGE_VARIANT: Record<string, Variant> = {
  ACCEPTED: "success",
  ACCOUNT_MADE: "success",
  ACTIVE: "success",
  ATTEMPTED: "warning",
  IN_TALK: "info",
  INSTALLING: "success",
  REJECTED: "error",
  WAITING_REPLY: "info",
};

export function outcomeVariant(o: OpOutcome | undefined): Variant {
  if (!o) return "secondary";
  if (o.stage === "ACCOUNT_MADE" || o.stage === "ACCEPTED") return "success";
  if (o.stage === "REJECTED") return "error";
  return o.reached ? "info" : "warning";
}

/** The current time, ticking every `everyMs` while `active`. */
export function useNow(active = true, everyMs = 1000): number {
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => setNow(Date.now()), everyMs);
    return () => window.clearInterval(t);
  }, [active, everyMs]);
  return now;
}

const STATE_LABELS = labels<OpAgentState>({
  offline: "ops.state.offline",
  on_call: "ops.state.onCall",
  paused: "ops.state.paused",
  ready: "ops.state.ready",
  serving: "ops.state.serving",
  wrap_up: "ops.state.wrapUp",
});
const STATE_VARIANTS: Record<OpAgentState, Variant | "outline"> = {
  offline: "outline",
  on_call: "success",
  paused: "secondary",
  ready: "info",
  serving: "info",
  wrap_up: "warning",
};
export const STATE = Object.fromEntries(
  (Object.keys(STATE_VARIANTS) as OpAgentState[]).map((s) => [
    s,
    { get label() { return STATE_LABELS[s]; }, variant: STATE_VARIANTS[s] },
  ]),
) as Record<OpAgentState, { label: string; variant: Variant | "outline" }>;

/** Seconds since `value` at `now`. */
export function secondsFrom(value: string | null | undefined, now: number): number | null {
  const t = parseDate(value)?.getTime();
  return t ? Math.max(0, Math.floor((now - t) / 1000)) : null;
}

export function contactName(op: OpCall | null): string {
  const name = shortName(op?.lead?.contact?.name ?? op?.lead?.name ?? t("ops.contact"));
  return op?.test ? t("ops.contactTest", { name }) : name;
}

// --- Daily targets and pauses (see call_analyzer/floor.py) ---

export const METRIC_LABELS = labels<OpGoalMetric>({
  calls: "ops.metric.calls",
  desk_minutes: "ops.metric.deskMinutes",
  reached: "ops.metric.reached",
  wins: "ops.metric.wins",
});

function fmtMinutes(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h ? `${h}h${String(m).padStart(2, "0")}` : t("common.minutesShort", { count: m });
}

export function fmtGoalValue(metric: OpGoalMetric, value: number): string {
  return metric === "desk_minutes" ? fmtMinutes(value) : String(Math.round(value));
}

/** done: target reached; ahead: at or past where the workday says it should be; behind: not yet. */
export function goalStatus(p: OpProgress): "done" | "ahead" | "behind" {
  if (p.value >= p.target) return "done";
  return p.value >= Math.floor(p.expected) ? "ahead" : "behind";
}


/** Seconds into the pause at `now` (the server's count plus the time since it was read). */
export function pauseSeconds(pause: OpPause, now: number): number {
  const start = parseDate(pause.started_at)?.getTime();
  return start ? Math.max(0, Math.floor((now - start) / 1000)) : pause.seconds;
}

export function pauseOver(pause: OpPause, now: number): boolean {
  return pause.limit_minutes > 0 && pauseSeconds(pause, now) > pause.limit_minutes * 60;
}
