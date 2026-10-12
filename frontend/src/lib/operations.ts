// Shared by the call desk and the team board (pages/operations*.tsx).
import * as React from "react";
import type { OpOutcome } from "@/lib/types";

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
