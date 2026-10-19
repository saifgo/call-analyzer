// Daily targets and pauses, shared by the desk bar, the team board and the wallboard (see call_analyzer/floor.py).
import { CoffeeIcon } from "lucide-react";
import type * as React from "react";
import { Badge } from "@/components/ui/badge";
import { fmtDuration } from "@/lib/format";
import { fmtGoalValue, goalStatus, METRIC_LABELS, pauseOver, pauseSeconds } from "@/lib/operations";
import type { OpPause, OpProgress } from "@/lib/types";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";

function statusText(p: OpProgress): string {
  const status = goalStatus(p);
  if (status === "done") return t("goals.reached");
  if (status === "ahead") return p.expected > 0 ? t("goals.onPace") : t("goals.dayNotStarted");
  return t("goals.behind", { gap: fmtGoalValue(p.metric, Math.ceil(p.expected - p.value)) });
}

const BAR = { ahead: "bg-primary", behind: "bg-warning", done: "bg-success" } as const;

/** One target: the value against it, with a mark where the workday's pace says it should be by now. */
export function GoalBar({ progress, size = "default" }: { progress: OpProgress; size?: "default" | "lg" }) {
  const p = progress;
  const status = goalStatus(p);
  const filled = Math.min(100, (p.value / p.target) * 100);
  const expected = Math.min(100, (p.expected / p.target) * 100);
  const lg = size === "lg";
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className={cn("flex items-baseline justify-between gap-2", lg ? "text-base" : "text-xs")}>
        <span className="text-muted-foreground">{METRIC_LABELS[p.metric]}</span>
        <span className={cn("font-semibold tabular-nums", lg && "text-2xl")}>
          {fmtGoalValue(p.metric, p.value)}
          <span className="font-normal text-muted-foreground"> / {fmtGoalValue(p.metric, p.target)}</span>
        </span>
      </div>
      <div
        aria-label={t("goals.ariaProgress", {
          metric: METRIC_LABELS[p.metric],
          target: fmtGoalValue(p.metric, p.target),
          value: fmtGoalValue(p.metric, p.value),
        })}
        aria-valuemax={p.target}
        aria-valuemin={0}
        aria-valuenow={p.value}
        className={cn("relative w-full overflow-hidden rounded-full bg-input", lg ? "h-3" : "h-1.5")}
        role="progressbar"
      >
        <div className={cn("h-full rounded-full transition-all duration-500", BAR[status])} style={{ width: `${filled}%` }} />
        {status !== "done" && expected > 0 && (
          <div aria-hidden="true" className="absolute inset-y-0 w-0.5 bg-foreground/60" style={{ insetInlineStart: `calc(${expected}% - 1px)` }} />
        )}
      </div>
      <span
        className={cn(
          lg ? "text-sm" : "text-[11px]",
          status === "behind" ? "text-warning-foreground" : status === "done" ? "text-success-foreground" : "text-muted-foreground",
        )}
      >
        {statusText(p)}
      </span>
    </div>
  );
}

export function GoalBars({ progress, className, size }: { progress: OpProgress[]; className?: string; size?: "default" | "lg" }) {
  if (!progress.length) return null;
  return (
    <div className={cn("grid gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-4", className)}>
      {progress.map((p) => (
        <GoalBar key={p.metric} progress={p} size={size} />
      ))}
    </div>
  );
}

/** "Lunch 12:04 / 60:00", red once it runs over its limit. */
export function PauseBadge({ pause, now, className }: { pause: OpPause; now: number; className?: string }): React.ReactElement {
  const seconds = pauseSeconds(pause, now);
  const over = pauseOver(pause, now);
  return (
    <Badge className={cn("tabular-nums", className)} variant={over ? "error" : "secondary"}>
      <CoffeeIcon aria-hidden="true" />
      {pause.label} {fmtDuration(seconds)}
      {pause.limit_minutes > 0 && <span className="opacity-70">/ {fmtDuration(pause.limit_minutes * 60)}</span>}
      {over && <span className="font-semibold">{t("goals.over")}</span>}
    </Badge>
  );
}
