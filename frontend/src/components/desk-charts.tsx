// Shared by the call desk's KPIs and Insights pages (pages/operations-kpis.tsx, operations-insights.tsx): the
// filters, stat tiles and two small charts drawn with plain divs (no chart library).
import type * as React from "react";
import { DateRangeFilter } from "@/components/date-range-filter";
import { Card, CardDescription, CardPanel } from "@/components/ui/card";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipPopup, TooltipTrigger } from "@/components/ui/tooltip";
import { isoDay, numberFmt, parseDate } from "@/lib/format";
import { href, navigate, type Route } from "@/lib/router";
import type { OpConfig } from "@/lib/types";
import { cn } from "@/lib/utils";

const DAY = 86_400_000;
const dayFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
const weekdayFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", weekday: "short" });

export function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${Math.round(value * 100)}%`;
}

export function score(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : value.toFixed(1);
}

/** 3h 05m, 12m, 40s. */
export function fmtHours(seconds: number | null | undefined): string {
  if (!seconds) return "–";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h) return `${h}h ${String(m).padStart(2, "0")}m`;
  return m ? `${m}m` : `${Math.round(seconds)}s`;
}

/** The page's date range and campaign, from the URL: the last 7 days and every campaign by default. */
export function useFilters(route: Route) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const since = route.query.get("since") ?? isoDay(new Date(today.getTime() - 6 * DAY));
  const until = route.query.get("until") ?? isoDay(new Date(today.getTime() + DAY));
  const campaign = route.query.get("campaign") ?? "";
  const set = (patch: Record<string, string>) => {
    const next = { campaign, since, tab: route.query.get("tab") ?? "", until, ...patch };
    navigate(href("operations", null, next), { replace: true });
  };
  const query = new URLSearchParams({ since, until, ...(campaign ? { campaign_id: campaign } : {}) }).toString();
  return { campaign, query, set, since, until };
}

export function FilterBar({ config, filters }: { config: OpConfig | undefined; filters: ReturnType<typeof useFilters> }) {
  const items = [
    { label: "All campaigns", value: "" },
    ...(config?.campaigns ?? []).map((c) => ({ label: c.active ? c.name : `${c.name} (archived)`, value: String(c.id) })),
  ];
  return (
    <div className="flex flex-wrap items-center gap-2">
      <DateRangeFilter onChange={(since, until) => filters.set({ since, until })} since={filters.since} until={filters.until} />
      {items.length > 2 && (
        <Select items={items} onValueChange={(v) => filters.set({ campaign: String(v ?? "") })} value={filters.campaign}>
          <SelectTrigger className="w-auto">
            <SelectValue />
          </SelectTrigger>
          <SelectPopup>
            {items.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectPopup>
        </Select>
      )}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <Card>
      <CardPanel className="flex flex-col gap-1 p-4">
        <span className="text-muted-foreground text-xs">{label}</span>
        <span className="font-heading font-semibold text-2xl tabular-nums">{value}</span>
        {hint && <CardDescription className="text-xs">{hint}</CardDescription>}
      </CardPanel>
    </Card>
  );
}

// Nested counts (wins are reached contacts, which are calls) drawn as one hue, light to dark, on a shared baseline.
const SERIES = [
  { className: "bg-chart-1/25", key: "calls", label: "Calls" },
  { className: "bg-chart-1/60", key: "reached", label: "Reached" },
  { className: "bg-chart-1", key: "success", label: "Wins" },
] as const;

export function DailyBars({ days }: { days: { day: string; calls: number; reached: number; success: number }[] }) {
  const max = Math.max(1, ...days.map((d) => d.calls));
  const every = Math.ceil(days.length / 10); // at most ~10 day labels
  return (
    <figure className="flex flex-col gap-3">
      <figcaption className="flex flex-wrap gap-4 text-muted-foreground text-xs">
        {SERIES.map((s) => (
          <span className="flex items-center gap-1.5" key={s.key}>
            <span aria-hidden="true" className={cn("size-2.5 rounded-sm", s.className)} />
            {s.label}
          </span>
        ))}
      </figcaption>
      <div className="flex h-44 items-end gap-0.5 border-b">
        {days.map((d) => (
          <Tooltip key={d.day}>
            <TooltipTrigger
              render={<div aria-label={`${d.day}: ${d.calls} calls, ${d.reached} reached, ${d.success} wins`} className="relative h-full min-w-1 flex-1" role="img" />}
            >
              {SERIES.map((s) => (
                <span
                  className={cn("absolute inset-x-[15%] bottom-0 rounded-t-[4px]", s.className)}
                  key={s.key}
                  style={{ height: `${(d[s.key] / max) * 100}%` }}
                />
              ))}
            </TooltipTrigger>
            <TooltipPopup>
              <div className="flex flex-col gap-0.5 text-xs">
                <span className="font-medium">{weekdayFmt.format(parseDate(d.day) ?? new Date())}</span>
                {SERIES.map((s) => (
                  <span className="flex justify-between gap-4" key={s.key}>
                    {s.label}
                    <span className="tabular-nums">{numberFmt.format(d[s.key])}</span>
                  </span>
                ))}
              </div>
            </TooltipPopup>
          </Tooltip>
        ))}
      </div>
      <div className="flex gap-0.5 text-muted-foreground text-xs">
        {days.map((d, i) => (
          <span className="min-w-1 flex-1 truncate text-center" key={d.day}>
            {i % every === 0 ? dayFmt.format(parseDate(d.day) ?? new Date()) : ""}
          </span>
        ))}
      </div>
    </figure>
  );
}

/** One bar per group, its height the rate (0-1), labelled with the rate and how many calls it's out of. */
export function RateBars({ bars }: { bars: { label: string; rate: number | null; n: number; detail: string }[] }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex h-40 items-end gap-3 border-b">
        {bars.map((b) => (
          <Tooltip key={b.label}>
            <TooltipTrigger render={<div aria-label={`${b.label}: ${pct(b.rate)}, ${b.detail}`} className="flex h-full flex-1 flex-col justify-end gap-1" role="img" />}>
              <span className="text-center font-medium text-sm tabular-nums">{b.n ? pct(b.rate) : ""}</span>
              <span className="mx-auto w-3/5 rounded-t-[4px] bg-chart-1" style={{ height: `${(b.rate ?? 0) * 100}%`, minHeight: b.n ? 2 : 0 }} />
            </TooltipTrigger>
            <TooltipPopup className="text-xs">{b.detail}</TooltipPopup>
          </Tooltip>
        ))}
      </div>
      <div className="flex gap-3 text-muted-foreground text-xs">
        {bars.map((b) => (
          <span className="flex flex-1 flex-col items-center" key={b.label}>
            <span className="font-medium text-foreground">{b.label}</span>
            <span>{b.n ? `${numberFmt.format(b.n)} calls` : "no calls"}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

/** A signed difference as a bar from a centre line, out to ±`range`. */
export function GapBar({ gap, range = 5 }: { gap: number | null; range?: number }) {
  if (gap === null) return <span className="text-muted-foreground">–</span>;
  const width = Math.min(Math.abs(gap) / range, 1) * 50;
  return (
    <span className="flex items-center gap-2">
      <span aria-hidden="true" className="relative h-2 w-24 rounded-full bg-muted">
        <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
        <span
          className={cn("absolute inset-y-0 rounded-full", gap >= 0 ? "bg-chart-2" : "bg-muted-foreground/50")}
          style={gap >= 0 ? { left: "50%", width: `${width}%` } : { right: "50%", width: `${width}%` }}
        />
      </span>
      <span className="tabular-nums">{gap > 0 ? `+${gap.toFixed(1)}` : gap.toFixed(1)}</span>
    </span>
  );
}
