// The wallboard: the team board for a TV on the sales floor. Full screen, dark, readable from across the room, and
// refreshed every few seconds. Built from /api/operations/board, like the Team board tab.
import { CircleAlertIcon, ExpandIcon, PhoneCallIcon, TrophyIcon } from "lucide-react";
import * as React from "react";
import { GoalBar, GoalBars, PauseBadge } from "@/components/goal-progress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { api } from "@/lib/api";
import { Bidi } from "@/lib/bidi";
import { dateTimeFormat, fmtDuration, fmtTime, numberFmt, parseDate } from "@/lib/format";
import { t } from "@/lib/i18n";
import { contactName, pauseOver, secondsFrom, STATE, useNow } from "@/lib/operations";
import type { OpAgentState, OpBoard, OpConfig } from "@/lib/types";
import { campaignText } from "@/lib/campaign-text";
import { cn } from "@/lib/utils";

const REFRESH_MS = 10_000;
// An agent stuck in one state this long is flagged (waiting for a contact, closing a call, about to call).
const SLOW_SECONDS: Partial<Record<OpAgentState, number>> = { ready: 5 * 60, serving: 3 * 60, wrap_up: 3 * 60 };
const STRIPE: Record<OpAgentState, string> = {
  clocked_out: "bg-muted-foreground/30",
  offline: "bg-muted-foreground/30",
  on_call: "bg-success",
  paused: "bg-muted-foreground",
  ready: "bg-info",
  serving: "bg-info",
  wrap_up: "bg-warning",
};
// Who comes first on the wall: those working, then paused, then gone.
const ORDER: Record<OpAgentState, number> = { clocked_out: 5, offline: 6, on_call: 0, paused: 4, ready: 2, serving: 1, wrap_up: 1 };

const clockFmt = dateTimeFormat({ hour: "2-digit", minute: "2-digit", second: "2-digit" });
const dayFmt = dateTimeFormat({ day: "numeric", month: "long", weekday: "long" });

function Tile({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: React.ReactNode; tone?: "warning" | "error" }) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 rounded-2xl border bg-card p-5",
        tone === "warning" && "border-warning/60 bg-warning/8",
        tone === "error" && "border-destructive/60 bg-destructive/8",
      )}
    >
      <span className="text-base text-muted-foreground">{label}</span>
      <span className="font-heading font-semibold text-5xl tabular-nums">{value}</span>
      {hint && <span className="text-muted-foreground text-sm">{hint}</span>}
    </div>
  );
}

type Agent = OpBoard["agents"][number];

function AgentCard({ agent: a, now }: { agent: Agent; now: number }) {
  const paused = a.state === "paused" && a.pause;
  const over = paused && a.pause ? pauseOver(a.pause, now) : false;
  const seconds = secondsFrom(a.state_since, now);
  const slow = seconds !== null && (SLOW_SECONDS[a.state] ?? Infinity) < seconds;
  const calls = a.progress.find((p) => p.metric === "calls");
  return (
    <div
      className={cn(
        "relative flex flex-col gap-3 overflow-hidden rounded-2xl border bg-card p-4 ps-6",
        a.state === "offline" && "opacity-50",
        (over || slow) && "border-destructive/70 bg-destructive/8",
      )}
    >
      <span aria-hidden="true" className={cn("absolute inset-y-0 start-0 w-2", over ? "animate-pulse bg-destructive" : STRIPE[a.state])} />
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-semibold text-xl">{a.name}</div>
          {a.campaign && <div className="truncate text-muted-foreground text-sm">{campaignText(a.campaign)}</div>}
        </div>
        <div className="flex flex-col items-end">
          <span className="font-semibold text-3xl tabular-nums">{a.today.success}</span>
          <span className="text-muted-foreground text-xs">{t("wall.wins")}</span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {paused && a.pause ? (
          <PauseBadge className="text-sm" now={now} pause={a.pause} />
        ) : (
          <Badge className="text-sm" variant={STATE[a.state].variant}>
            {STATE[a.state].label}
          </Badge>
        )}
        {!paused && a.state !== "offline" && seconds !== null && (
          <span className={cn("text-lg tabular-nums", slow ? "font-semibold text-destructive-foreground" : "text-muted-foreground")}>
            {fmtDuration(seconds)}
          </span>
        )}
        {a.state === "offline" && a.last_seen && <span className="text-muted-foreground text-sm">{t("wall.since", { time: fmtTime(a.last_seen) })}</span>}
      </div>
      {a.current && a.state !== "paused" && (
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <PhoneCallIcon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
          <Bidi as="span" className="truncate" text={contactName(a.current)} />
        </div>
      )}
      {calls ? (
        <GoalBar progress={calls} />
      ) : (
        <div className="text-muted-foreground text-sm tabular-nums">
          {t("wall.closedReached", { done: a.today.done, reached: a.today.reached })}
        </div>
      )}
    </div>
  );
}

export function WallboardPage(): React.ReactElement {
  const [data, setData] = React.useState<OpBoard>();
  const [config, setConfig] = React.useState<OpConfig>();
  const [error, setError] = React.useState<string | null>(null);
  const [updated, setUpdated] = React.useState<number>(0);
  const now = useNow(true, 1000);

  // A TV wall reads best dark, whatever the browser's theme.
  React.useEffect(() => {
    const root = document.documentElement;
    const had = root.classList.contains("dark");
    root.classList.add("dark");
    document.title = `${t("wall.title")} · Call Analyzer`;
    return () => {
      root.classList.toggle("dark", had);
    };
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const board = await api<OpBoard>("/api/operations/board");
        if (cancelled) return;
        setData(board);
        setUpdated(Date.now());
        setError(null);
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      }
    };
    api<OpConfig>("/api/operations/config")
      .then((c) => !cancelled && setConfig(c))
      .catch(() => undefined);
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  if (!data) {
    return (
      <div className="flex min-h-svh items-center justify-center gap-3 bg-background text-foreground text-xl">
        {error ? (
          <>
            <CircleAlertIcon aria-hidden="true" className="text-destructive-foreground" />
            {error}
          </>
        ) : (
          <>
            <Spinner /> {t("wall.loading")}
          </>
        )}
      </div>
    );
  }

  const todayStart = new Date(now).setHours(0, 0, 0, 0);
  // Agents who came to the desk today, plus whoever is online.
  const agents = data.agents
    .filter((a) => a.online || (parseDate(a.last_seen)?.getTime() ?? 0) >= todayStart)
    .sort((a, b) => ORDER[a.state] - ORDER[b.state] || a.name.localeCompare(b.name));
  const count = (state: OpAgentState) => agents.filter((a) => a.state === state).length;
  const overPauses = agents.filter((a) => a.state === "paused" && a.pause && pauseOver(a.pause, now)).length;
  const totals = agents.reduce(
    (sum, a) => ({ done: sum.done + a.today.done, reached: sum.reached + a.today.reached, success: sum.success + a.today.success }),
    { done: 0, reached: 0, success: 0 },
  );
  const contactRate = totals.done ? Math.round((totals.reached / totals.done) * 100) : null;
  const leaders = [...agents]
    .filter((a) => a.today.done > 0)
    .sort((a, b) => b.today.success - a.today.success || b.today.reached - a.today.reached || b.today.done - a.today.done)
    .slice(0, 5);
  const outcomes = Object.fromEntries((config?.outcomes ?? []).map((o) => [o.value, o]));
  const wins = data.recent
    .filter((r) => !r.test && outcomes[r.outcome ?? ""]?.success && (parseDate(r.finished_at)?.getTime() ?? 0) >= todayStart)
    .slice(0, 6);
  const q = data.queue;
  const stale = updated > 0 && now - updated > REFRESH_MS * 3;

  return (
    <div className="flex min-h-svh flex-col gap-6 bg-background p-6 text-foreground lg:p-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-heading font-semibold text-4xl">{t("wall.salesFloor")}</h1>
          <p className="text-lg text-muted-foreground">
            {dayFmt().format(now)} ·{" "}
            {t("wall.workday", { end: data.workday.end, pct: Math.round(data.pace * 100), start: data.workday.start })}
          </p>
        </div>
        <div className="flex items-center gap-4">
          {(error || stale) && (
            <Badge className="text-sm" variant="error">
              <CircleAlertIcon aria-hidden="true" />
              {error ? t("wall.notUpdatingError", { error }) : t("wall.notUpdating")}
            </Badge>
          )}
          <span className="font-heading font-semibold text-5xl tabular-nums">{clockFmt().format(now)}</span>
          <Button
            aria-label={t("wall.fullScreen")}
            onClick={() => (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen())}
            size="icon"
            variant="ghost"
          >
            <ExpandIcon aria-hidden="true" />
          </Button>
        </div>
      </header>

      <section className="grid gap-4 sm:grid-cols-3 xl:grid-cols-6">
        <Tile hint={t("wall.aboutToCall", { count: count("serving") + count("wrap_up") })} label={t("ops.state.onCall")} value={count("on_call")} />
        <Tile
          hint={count("ready") ? t("ops.state.ready") : t("wall.nobodyWaiting")}
          label={t("wall.free")}
          tone={count("ready") > 0 && q.waiting === 0 ? "warning" : undefined}
          value={count("ready")}
        />
        <Tile hint={overPauses ? t("wall.overLimit", { count: overPauses }) : t("wall.noneOverLimit")} label={t("ops.state.paused")} tone={overPauses ? "error" : undefined} value={count("paused")} />
        <Tile
          hint={q.due_callbacks ? t("wall.callbacksDue", { count: q.due_callbacks }) : t("wall.callbacksScheduled", { count: q.scheduled })}
          label={t("wall.inQueue")}
          tone={q.waiting === 0 ? "warning" : undefined}
          value={q.waiting === null ? "–" : numberFmt.format(q.waiting)}
        />
        <Tile hint={contactRate === null ? t("wall.noCallClosed") : t("wall.pctReached", { pct: contactRate })} label={t("wall.callsClosed")} value={totals.done} />
        <Tile
          hint={totals.reached ? t("wall.pctOfReached", { pct: Math.round((totals.success / totals.reached) * 100) }) : undefined}
          label={t("ops.metric.wins")}
          value={totals.success}
        />
      </section>

      {data.team_progress.length > 0 && (
        <section className="rounded-2xl border bg-card p-5">
          <h2 className="mb-3 text-lg text-muted-foreground">{t("wall.teamTargets")}</h2>
          <GoalBars progress={data.team_progress} size="lg" />
        </section>
      )}

      <div className="grid flex-1 gap-6 xl:grid-cols-[1fr_22rem]">
        <section className="grid content-start gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {agents.length === 0 && <p className="text-muted-foreground text-xl">{t("wall.nobodyYet")}</p>}
          {agents.map((a) => (
            <AgentCard agent={a} key={a.username} now={now} />
          ))}
        </section>
        <aside className="flex flex-col gap-6">
          <section className="rounded-2xl border bg-card p-5">
            <h2 className="mb-3 flex items-center gap-2 text-lg text-muted-foreground">
              <TrophyIcon aria-hidden="true" className="size-5" />
              {t("wall.leaderboard")}
            </h2>
            {leaders.length === 0 ? (
              <p className="text-muted-foreground">{t("wall.noCallClosedToday")}</p>
            ) : (
              <ol className="flex flex-col gap-2">
                {leaders.map((a, i) => (
                  <li className="flex items-center gap-3 text-lg" key={a.username}>
                    <span
                      className={cn(
                        "flex size-8 shrink-0 items-center justify-center rounded-full font-semibold text-sm",
                        i === 0 ? "bg-warning text-warning-foreground" : "bg-muted",
                      )}
                    >
                      {i + 1}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{a.name}</span>
                    <span className="font-semibold tabular-nums">{a.today.success}</span>
                    <span className="w-20 text-end text-muted-foreground text-sm tabular-nums">{t("desk.nCalls", { count: a.today.done })}</span>
                  </li>
                ))}
              </ol>
            )}
          </section>
          <section className="rounded-2xl border bg-card p-5">
            <h2 className="mb-3 text-lg text-muted-foreground">{t("wall.latestWins")}</h2>
            {wins.length === 0 ? (
              <p className="text-muted-foreground">{t("wall.noWinToday")}</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {wins.map((w) => (
                  <li className="flex items-baseline gap-2" key={w.id}>
                    <span className="text-muted-foreground text-sm tabular-nums">{fmtTime(w.finished_at)}</span>
                    <span className="font-medium">{w.agent_name}</span>
                    <Bidi as="span" className="min-w-0 truncate text-muted-foreground" text={contactName(w)} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
