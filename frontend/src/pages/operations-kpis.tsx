import { CircleAlertIcon } from "lucide-react";
import type * as React from "react";
import { DailyBars, FilterBar, fmtHours, pct, score, Stat, useFilters } from "@/components/desk-charts";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardDescription, CardFrame, CardFrameDescription, CardFrameHeader, CardFrameTitle, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipPopup, TooltipTrigger } from "@/components/ui/tooltip";
import { useApi } from "@/lib/api";
import { useOpConfig } from "@/lib/campaign-text";
import { fmtDateTime, fmtDuration, fmtTime, isoDay, numberFmt, parseDate } from "@/lib/format";
import { t, type TKey } from "@/lib/i18n";
import { useMe } from "@/lib/me";
import type { Route } from "@/lib/router";
import type { OpIdlePrompt, OpInboundStats, OpKpiRow, OpKpis } from "@/lib/types";

const DAY = 86_400_000;

/** Every day of the range, with zeros for days without calls (up to ~3 months). */
function fillDays(k: OpKpis): OpKpis["days"] {
  const start = parseDate(k.since);
  const end = parseDate(k.until);
  if (!start || !end || end.getTime() - start.getTime() > 92 * DAY) return k.days;
  const byDay = new Map(k.days.map((d) => [d.day, d]));
  const days = [];
  for (let ts = start.getTime(); ts < end.getTime(); ts += DAY) {
    const day = isoDay(new Date(ts));
    days.push(byDay.get(day) ?? { calls: 0, day, reached: 0, success: 0 });
  }
  return days;
}

function Ratio({ part, rate }: { part: number; rate: number | null }) {
  return (
    <span className="flex flex-col items-end">
      <span className="tabular-nums">{numberFmt.format(part)}</span>
      <span className="text-muted-foreground text-xs tabular-nums">{pct(rate)}</span>
    </span>
  );
}

/** Incoming calls: how many were answered, and how fast the missed ones were called back. */
function InboundFigures({ stats, byAgent }: { stats: OpInboundStats; byAgent: boolean }) {
  const team = stats.team;
  const minutes = (m: number | null) => (m === null ? "–" : t("inbound.minutes", { value: m }));
  return (
    <CardFrame>
      <CardFrameHeader>
        <CardFrameTitle>{t("inbound.kpisTitle")}</CardFrameTitle>
        <CardFrameDescription>{t("inbound.kpisHint")}</CardFrameDescription>
      </CardFrameHeader>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            hint={t("inbound.answeredHint", { answered: team.answered, calls: team.calls })}
            label={t("inbound.answerRate")}
            value={pct(team.answer_rate)}
          />
          <Stat
            hint={t("inbound.missedHintKpi", { dismissed: team.dismissed, waiting: team.waiting })}
            label={t("inbound.missedTitle")}
            value={numberFmt.format(team.missed)}
          />
          <Stat
            hint={t("inbound.calledBackHint", { back: team.called_back, through: team.got_through })}
            label={t("inbound.calledBackRate")}
            value={pct(team.callback_rate)}
          />
          <Stat
            hint={t("inbound.speedHint", { median: minutes(team.median_callback_minutes), within: team.called_back_15min })}
            label={t("inbound.speed")}
            value={minutes(team.avg_callback_minutes)}
          />
      </div>
      {byAgent && stats.agents.length > 0 && (
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>{t("shell.agent")}</TableHead>
              <TableHead className="text-end">{t("inbound.rangThem")}</TableHead>
              <TableHead className="text-end">{t("inbound.answered")}</TableHead>
              <TableHead className="text-end">{t("inbound.missedTitle")}</TableHead>
              <TableHead className="text-end">{t("inbound.calledBack")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {stats.agents.map((a) => (
              <TableRow key={a.username}>
                <TableCell className="font-medium">{a.name}</TableCell>
                <TableCell className="text-end tabular-nums">{numberFmt.format(a.rang)}</TableCell>
                <TableCell className="text-end tabular-nums">
                  {numberFmt.format(a.answered)} <span className="text-muted-foreground text-xs">{pct(a.answer_rate)}</span>
                </TableCell>
                <TableCell className="text-end tabular-nums">{numberFmt.format(a.missed)}</TableCell>
                <TableCell className="text-end tabular-nums">{numberFmt.format(a.called_back)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </CardFrame>
  );
}

function AgentTable({ rows, team }: { rows: OpKpiRow[]; team: OpKpiRow }) {
  const all = [...rows, team];
  return (
    <CardFrame>
      <CardFrameHeader>
        <CardFrameTitle>{t("kpis.byAgent")}</CardFrameTitle>
      </CardFrameHeader>
      <Table variant="card">
        <TableHeader>
          <TableRow>
            <TableHead>{t("shell.agent")}</TableHead>
            <TableHead className="text-end">{t("ops.metric.calls")}</TableHead>
            <TableHead className="text-end">{t("ops.metric.reached")}</TableHead>
            <TableHead className="text-end">{t("ops.metric.wins")}</TableHead>
            <TableHead className="text-end">{t("kpis.callsPerHour")}</TableHead>
            <TableHead className="text-end">{t("kpis.winsPerHour")}</TableHead>
            <TableHead className="text-end">{t("ops.metric.deskMinutes")}</TableHead>
            <TableHead className="text-end">{t("ops.state.paused")}</TableHead>
            <TableHead className="text-end">{t("kpis.idle")}</TableHead>
            <TableHead className="text-end">{t("kpis.talking")}</TableHead>
            <TableHead className="text-end">{t("kpis.avgCall")}</TableHead>
            <TableHead className="text-end">{t("kpis.avgWrap")}</TableHead>
            <TableHead className="text-end">{t("kpis.callbacks")}</TableHead>
            <TableHead className="text-end">{t("kpis.givenBack")}</TableHead>
            <TableHead className="text-end">{t("kpis.aiScore")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 && (
            <TableRow>
              <TableCell className="text-muted-foreground" colSpan={15}>
                {t("kpis.noCalls")}
              </TableCell>
            </TableRow>
          )}
          {rows.length > 0 &&
            all.map((a) => (
              <TableRow className={a.username === null ? "bg-muted/40 font-medium" : undefined} key={a.username ?? "team"}>
                <TableCell className="font-medium">{a.name}</TableCell>
                <TableCell className="text-end tabular-nums">{numberFmt.format(a.calls)}</TableCell>
                <TableCell className="text-end">
                  <Ratio part={a.reached} rate={a.contact_rate} />
                </TableCell>
                <TableCell className="text-end">
                  <Ratio part={a.success} rate={a.conversion_rate} />
                </TableCell>
                <TableCell className="text-end tabular-nums">{a.calls_per_hour ?? "–"}</TableCell>
                <TableCell className="text-end tabular-nums">{a.success_per_hour ?? "–"}</TableCell>
                <TableCell className="text-end tabular-nums">{fmtHours(a.desk_seconds)}</TableCell>
                <TableCell className="text-end tabular-nums">
                  <Tooltip>
                    <TooltipTrigger render={<span />}>
                      {a.pause_seconds ? fmtHours(a.pause_seconds) : "–"}
                      {a.pauses_over > 0 && <span className="ms-1 text-destructive-foreground text-xs">{t("kpis.pausesOver", { count: a.pauses_over })}</span>}
                    </TooltipTrigger>
                    {Object.keys(a.pause_reasons).length > 0 && (
                      <TooltipPopup>
                        {Object.entries(a.pause_reasons)
                          .sort((x, y) => y[1] - x[1])
                          .map(([label, seconds]) => `${label} ${fmtHours(seconds)}`)
                          .join(" · ")}
                      </TooltipPopup>
                    )}
                  </Tooltip>
                </TableCell>
                <TableCell className="text-end tabular-nums">
                  {fmtHours(a.idle_seconds)}
                  {a.idle_prompts > 0 && <span className="ms-1 text-warning-foreground text-xs">({a.idle_prompts}×)</span>}
                </TableCell>
                <TableCell className="text-end tabular-nums">{pct(a.talk_share)}</TableCell>
                <TableCell className="text-end tabular-nums">{a.avg_talk_seconds === null ? "–" : fmtDuration(a.avg_talk_seconds)}</TableCell>
                <TableCell className="text-end tabular-nums">{a.avg_wrap_seconds === null ? "–" : fmtDuration(a.avg_wrap_seconds)}</TableCell>
                <TableCell className="text-end tabular-nums">{a.callbacks_booked}</TableCell>
                <TableCell className="text-end tabular-nums">{a.given_back}</TableCell>
                <TableCell className="text-end tabular-nums">
                  {score(a.avg_score)}
                  {a.scored > 0 && <span className="ms-1 text-muted-foreground text-xs">({a.scored})</span>}
                </TableCell>
              </TableRow>
            ))}
        </TableBody>
      </Table>
    </CardFrame>
  );
}

const IDLE_ENDS: Record<NonNullable<OpIdlePrompt["outcome"]>, { label: TKey; variant: "success" | "secondary" | "warning" }> = {
  called: { label: "kpis.idleEnd.called", variant: "success" },
  paused: { label: "kpis.idleEnd.paused", variant: "secondary" },
  left: { label: "kpis.idleEnd.left", variant: "warning" },
};

/** Each time an agent taking calls stayed idle long enough to be prompted to call (see call_analyzer/idle.py). */
function IdlePrompts({ prompts }: { prompts: OpIdlePrompt[] }) {
  return (
    <CardFrame>
      <CardFrameHeader>
        <CardFrameTitle>{t("kpis.idlePrompts")}</CardFrameTitle>
        <CardFrameDescription>{t("kpis.idlePromptsHint")}</CardFrameDescription>
      </CardFrameHeader>
      <Table variant="card">
        <TableHeader>
          <TableRow>
            <TableHead>{t("shell.agent")}</TableHead>
            <TableHead>{t("kpis.idleSince")}</TableHead>
            <TableHead>{t("kpis.prompted")}</TableHead>
            <TableHead className="text-end">{t("kpis.idleFor")}</TableHead>
            <TableHead>{t("kpis.doing")}</TableHead>
            <TableHead>{t("kpis.then")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {prompts.length === 0 && (
            <TableRow>
              <TableCell className="text-muted-foreground" colSpan={6}>
                {t("kpis.noPrompts")}
              </TableCell>
            </TableRow>
          )}
          {prompts.map((p) => {
            const end = p.outcome ? IDLE_ENDS[p.outcome] : null;
            return (
              <TableRow key={p.id}>
                <TableCell className="font-medium">{p.name ?? p.username}</TableCell>
                <TableCell className="tabular-nums">{fmtDateTime(p.idle_since)}</TableCell>
                <TableCell className="tabular-nums">
                  {fmtTime(p.prompted_at)}
                  {p.prompts > 1 && <span className="ms-1 text-muted-foreground text-xs">{t("kpis.times", { count: p.prompts })}</span>}
                </TableCell>
                <TableCell className="text-end tabular-nums">{fmtHours(p.idle_seconds)}</TableCell>
                <TableCell className="text-muted-foreground">{p.doing ?? "–"}</TableCell>
                <TableCell>
                  {end ? (
                    <Badge variant={end.variant}>{t(end.label, { time: fmtTime(p.ended_at) })}</Badge>
                  ) : (
                    <Badge variant="warning">{t("kpis.stillIdle")}</Badge>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </CardFrame>
  );
}

/** The desk KPIs: the team's (admins) or the agent's own, over a date range. */
export function OperationsKpis({ route }: { route: Route }): React.ReactElement {
  const { isAdmin } = useMe();
  const filters = useFilters(route);
  const { data: config } = useOpConfig();
  const { data, error } = useApi<OpKpis>(`/api/operations/kpis?${filters.query}`);

  if (error && !data) {
    return (
      <Alert variant="error">
        <CircleAlertIcon aria-hidden="true" />
        <AlertTitle>{t("kpis.loadFailed")}</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  const team = data?.team;
  return (
    <>
      <FilterBar config={config} filters={filters} />
      {!data || !team ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton className="h-24 rounded-2xl" key={i} />
          ))}
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              hint={t("kpis.reachedHint", { rate: pct(team.contact_rate), reached: team.reached })}
              label={t("wall.callsClosed")}
              value={numberFmt.format(team.calls)}
            />
            <Stat hint={t("kpis.conversionHint", { rate: pct(team.conversion_rate) })} label={t("ops.metric.wins")} value={numberFmt.format(team.success)} />
            <Stat
              hint={
                team.desk_seconds
                  ? t("kpis.deskHint", { desk: fmtHours(team.desk_seconds), perHour: team.success_per_hour ?? "–" })
                  : t("kpis.noDeskTime")
              }
              label={t("kpis.callsPerDeskHour")}
              value={team.calls_per_hour ?? "–"}
            />
            <Stat
              hint={t("kpis.talkHint", {
                share: pct(team.talk_share),
                wrap: team.avg_wrap_seconds === null ? "–" : fmtDuration(team.avg_wrap_seconds),
              })}
              label={t("kpis.averageCall")}
              value={team.avg_talk_seconds === null ? "–" : fmtDuration(team.avg_talk_seconds)}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat hint={t("kpis.bookedForLater")} label={t("kpis.callbacksBooked")} value={numberFmt.format(team.callbacks_booked)} />
            <Stat hint={t("kpis.givenBackHint")} label={t("kpis.givenBack")} value={numberFmt.format(team.given_back)} />
            <Stat
              hint={t("kpis.linkedHint", { calls: team.calls, linked: team.linked })}
              label={t("kpis.recordingsFound")}
              value={pct(team.calls ? team.linked / team.calls : null)}
            />
            <Stat hint={t("kpis.scoredHint", { count: team.scored })} label={t("kpis.averageAiScore")} value={score(team.avg_score)} />
          </div>
          <Card>
            <CardHeader>
              <CardTitle>{t("kpis.dayByDay")}</CardTitle>
              <CardDescription>{t("kpis.dayByDayHint")}</CardDescription>
            </CardHeader>
            <CardPanel>
              <DailyBars days={fillDays(data)} />
            </CardPanel>
          </Card>
          {isAdmin && <AgentTable rows={data.agents} team={team} />}
          {data.inbound && <InboundFigures byAgent={isAdmin} stats={data.inbound} />}
          {isAdmin && <IdlePrompts prompts={data.idle_prompts} />}
        </>
      )}
    </>
  );
}
