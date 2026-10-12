import { CircleAlertIcon } from "lucide-react";
import type * as React from "react";
import { DailyBars, FilterBar, fmtHours, pct, score, Stat, useFilters } from "@/components/desk-charts";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardDescription, CardFrame, CardFrameHeader, CardFrameTitle, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/lib/api";
import { fmtDuration, isoDay, numberFmt, parseDate } from "@/lib/format";
import { useMe } from "@/lib/me";
import type { Route } from "@/lib/router";
import type { OpConfig, OpKpiRow, OpKpis } from "@/lib/types";

const DAY = 86_400_000;

/** Every day of the range, with zeros for days without calls (up to ~3 months). */
function fillDays(k: OpKpis): OpKpis["days"] {
  const start = parseDate(k.since);
  const end = parseDate(k.until);
  if (!start || !end || end.getTime() - start.getTime() > 92 * DAY) return k.days;
  const byDay = new Map(k.days.map((d) => [d.day, d]));
  const days = [];
  for (let t = start.getTime(); t < end.getTime(); t += DAY) {
    const day = isoDay(new Date(t));
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

function AgentTable({ rows, team }: { rows: OpKpiRow[]; team: OpKpiRow }) {
  const all = [...rows, team];
  return (
    <CardFrame>
      <CardFrameHeader>
        <CardFrameTitle>By agent</CardFrameTitle>
      </CardFrameHeader>
      <Table variant="card">
        <TableHeader>
          <TableRow>
            <TableHead>Agent</TableHead>
            <TableHead className="text-end">Calls</TableHead>
            <TableHead className="text-end">Reached</TableHead>
            <TableHead className="text-end">Wins</TableHead>
            <TableHead className="text-end">Calls / hour</TableHead>
            <TableHead className="text-end">Wins / hour</TableHead>
            <TableHead className="text-end">Desk time</TableHead>
            <TableHead className="text-end">Talking</TableHead>
            <TableHead className="text-end">Avg call</TableHead>
            <TableHead className="text-end">Avg wrap-up</TableHead>
            <TableHead className="text-end">Callbacks</TableHead>
            <TableHead className="text-end">Given back</TableHead>
            <TableHead className="text-end">AI score</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 && (
            <TableRow>
              <TableCell className="text-muted-foreground" colSpan={13}>
                No call closed from the desk in this period.
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

/** The desk KPIs: the team's (admins) or the agent's own, over a date range. */
export function OperationsKpis({ route }: { route: Route }): React.ReactElement {
  const { isAdmin } = useMe();
  const filters = useFilters(route);
  const { data: config } = useApi<OpConfig>("/api/operations/config");
  const { data, error } = useApi<OpKpis>(`/api/operations/kpis?${filters.query}`);

  if (error && !data) {
    return (
      <Alert variant="error">
        <CircleAlertIcon aria-hidden="true" />
        <AlertTitle>Couldn't load the KPIs</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  const t = data?.team;
  return (
    <>
      <FilterBar config={config} filters={filters} />
      {!data || !t ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton className="h-24 rounded-2xl" key={i} />
          ))}
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat hint={`${numberFmt.format(t.reached)} reached · ${pct(t.contact_rate)} contact rate`} label="Calls closed" value={numberFmt.format(t.calls)} />
            <Stat hint={`${pct(t.conversion_rate)} of the contacts reached`} label="Wins" value={numberFmt.format(t.success)} />
            <Stat
              hint={t.desk_seconds ? `${fmtHours(t.desk_seconds)} on the desk · ${t.success_per_hour ?? "–"} wins / hour` : "No desk time recorded"}
              label="Calls per desk hour"
              value={t.calls_per_hour ?? "–"}
            />
            <Stat
              hint={`${pct(t.talk_share)} of desk time · wrap-up ${t.avg_wrap_seconds === null ? "–" : fmtDuration(t.avg_wrap_seconds)}`}
              label="Average call"
              value={t.avg_talk_seconds === null ? "–" : fmtDuration(t.avg_talk_seconds)}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat hint="Booked for later" label="Callbacks booked" value={numberFmt.format(t.callbacks_booked)} />
            <Stat hint="Contacts released without calling" label="Given back" value={numberFmt.format(t.given_back)} />
            <Stat
              hint={`${numberFmt.format(t.linked)} of ${numberFmt.format(t.calls)} calls matched to their recording`}
              label="Recordings found"
              value={pct(t.calls ? t.linked / t.calls : null)}
            />
            <Stat hint={`Over ${numberFmt.format(t.scored)} rated recordings`} label="Average AI score" value={score(t.avg_score)} />
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Day by day</CardTitle>
              <CardDescription>Calls closed, contacts reached and wins. Hover a day for its figures.</CardDescription>
            </CardHeader>
            <CardPanel>
              <DailyBars days={fillDays(data)} />
            </CardPanel>
          </Card>
          {isAdmin && <AgentTable rows={data.agents} team={t} />}
        </>
      )}
    </>
  );
}
