import { CircleAlertIcon, InfoIcon } from "lucide-react";
import type * as React from "react";
import { FilterBar, GapBar, pct, RateBars, score, Stat, useFilters } from "@/components/desk-charts";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardDescription, CardFrame, CardFrameDescription, CardFrameHeader, CardFrameTitle, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/lib/api";
import { Bidi } from "@/lib/bidi";
import { fmtDateTime, fmtDuration, humanize, numberFmt } from "@/lib/format";
import { outcomeVariant } from "@/lib/operations";
import { href, type Route } from "@/lib/router";
import type { OpConfig, OpInsights } from "@/lib/types";

function Empty({ colSpan, children }: { colSpan: number; children: React.ReactNode }) {
  return (
    <TableRow>
      <TableCell className="text-muted-foreground" colSpan={colSpan}>
        {children}
      </TableCell>
    </TableRow>
  );
}

/** Outcomes agents pick on the desk against the AI's scores of the same recorded calls. */
export function OperationsInsights({ route }: { route: Route }): React.ReactElement {
  const filters = useFilters(route);
  const { data: config } = useApi<OpConfig>("/api/operations/config");
  const { data, error } = useApi<OpInsights>(`/api/operations/insights?${filters.query}`);
  const outcomes = Object.fromEntries((config?.outcomes ?? []).map((o) => [o.value, o]));

  if (error && !data) {
    return (
      <Alert variant="error">
        <CircleAlertIcon aria-hidden="true" />
        <AlertTitle>Couldn't load the insights</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  if (!data) {
    return (
      <>
        <FilterBar config={config} filters={filters} />
        <div className="grid gap-4 sm:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton className="h-24 rounded-2xl" key={i} />
          ))}
        </div>
        <Skeleton className="h-64 rounded-2xl" />
      </>
    );
  }

  const o = data.overall;
  return (
    <>
      <FilterBar config={config} filters={filters} />
      {data.total > 0 && data.linked < data.total / 2 && (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertTitle>
            Only {numberFmt.format(data.linked)} of {numberFmt.format(data.total)} desk calls are matched to a recording
          </AlertTitle>
          <AlertDescription>
            Calls are matched after each GoVoice sync, on the number, the agent's extension (their phone or the extensions on
            their account in Users) and the time. Unanswered calls usually have no recording. If GoVoice's clock differs from
            this server's, set RECORDING_CLOCK_OFFSET_MINUTES in Settings.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat
          hint={`${numberFmt.format(data.linked)} with a recording, ${numberFmt.format(data.rated)} rated by the AI`}
          label="Desk calls"
          value={numberFmt.format(data.total)}
        />
        <Stat hint={`Over ${numberFmt.format(data.won_rated)} rated wins`} label="AI score of wins" value={score(o.won)} />
        <Stat
          hint={o.gap === null ? "Needs rated wins and other reached calls" : `${o.gap > 0 ? "+" : ""}${o.gap.toFixed(1)} points for the wins`}
          label="AI score of the other reached calls"
          value={score(o.other)}
        />
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Win rate by AI score</CardTitle>
            <CardDescription>Of the reached contacts whose call the AI rated, how many ended in a win.</CardDescription>
          </CardHeader>
          <CardPanel>
            <RateBars
              bars={data.bands.map((b) => ({
                detail: `${numberFmt.format(b.success)} wins out of ${numberFmt.format(b.calls)} calls scored ${b.band}`,
                label: b.band,
                n: b.calls,
                rate: b.success_rate,
              }))}
            />
          </CardPanel>
        </Card>
        <CardFrame>
          <CardFrameHeader>
            <CardFrameTitle>What the wins do better</CardFrameTitle>
            <CardFrameDescription>Average score card on wins against the other reached calls, biggest gap first.</CardFrameDescription>
          </CardFrameHeader>
          <Table variant="card">
            <TableHeader>
              <TableRow>
                <TableHead>Criterion</TableHead>
                <TableHead className="text-end">Wins</TableHead>
                <TableHead className="text-end">Others</TableHead>
                <TableHead>Gap</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.drivers.length === 0 && <Empty colSpan={4}>No rated call in this period yet.</Empty>}
              {data.drivers.map((d) => (
                <TableRow key={d.criterion}>
                  <TableCell>{humanize(d.criterion)}</TableCell>
                  <TableCell className="text-end tabular-nums">{score(d.won)}</TableCell>
                  <TableCell className="text-end tabular-nums">{score(d.other)}</TableCell>
                  <TableCell>
                    <GapBar gap={d.gap} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardFrame>
      </div>

      <CardFrame>
        <CardFrameHeader>
          <CardFrameTitle>By outcome</CardFrameTitle>
          <CardFrameDescription>What the agent recorded, and what the AI made of the same calls.</CardFrameDescription>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>Outcome</TableHead>
              <TableHead className="text-end">Calls</TableHead>
              <TableHead className="text-end">Rated</TableHead>
              <TableHead className="text-end">AI score</TableHead>
              <TableHead className="text-end">Voice</TableHead>
              <TableHead className="text-end">Avg call</TableHead>
              <TableHead>The AI said</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.outcomes.length === 0 && <Empty colSpan={7}>No call closed from the desk in this period.</Empty>}
            {data.outcomes.map((row) => (
              <TableRow key={row.outcome}>
                <TableCell>
                  <Badge variant={outcomeVariant(outcomes[row.outcome])}>{row.label}</Badge>
                </TableCell>
                <TableCell className="text-end tabular-nums">{numberFmt.format(row.calls)}</TableCell>
                <TableCell className="text-end tabular-nums">{numberFmt.format(row.rated)}</TableCell>
                <TableCell className="text-end tabular-nums">{score(row.avg_score)}</TableCell>
                <TableCell className="text-end tabular-nums">{score(row.avg_voice)}</TableCell>
                <TableCell className="text-end tabular-nums">
                  {row.avg_talk_seconds === null ? "–" : fmtDuration(Math.round(row.avg_talk_seconds))}
                </TableCell>
                <TableCell className="whitespace-normal text-muted-foreground text-xs">
                  {Object.entries(row.ai_outcomes)
                    .sort((a, b) => b[1] - a[1])
                    .map(([ai, n]) => `${humanize(ai)} ${pct(n / row.rated)}`)
                    .join(" · ") || "–"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardFrame>

      <CardFrame>
        <CardFrameHeader>
          <CardFrameTitle>By agent</CardFrameTitle>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>Agent</TableHead>
              <TableHead className="text-end">Calls</TableHead>
              <TableHead className="text-end">Wins / reached</TableHead>
              <TableHead className="text-end">AI score</TableHead>
              <TableHead className="text-end">On wins</TableHead>
              <TableHead className="text-end">On the others</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.agents.length === 0 && <Empty colSpan={6}>No call closed from the desk in this period.</Empty>}
            {data.agents.map((a) => (
              <TableRow key={a.username}>
                <TableCell className="font-medium">{a.name}</TableCell>
                <TableCell className="text-end tabular-nums">{numberFmt.format(a.calls)}</TableCell>
                <TableCell className="text-end tabular-nums">
                  {numberFmt.format(a.success)} / {numberFmt.format(a.reached)}
                  <span className="ms-1 text-muted-foreground text-xs">{pct(a.conversion_rate)}</span>
                </TableCell>
                <TableCell className="text-end tabular-nums">
                  {score(a.avg_score)}
                  {a.rated > 0 && <span className="ms-1 text-muted-foreground text-xs">({a.rated})</span>}
                </TableCell>
                <TableCell className="text-end tabular-nums">{score(a.avg_score_won)}</TableCell>
                <TableCell className="text-end tabular-nums">{score(a.avg_score_other)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardFrame>

      <CardFrame>
        <CardFrameHeader>
          <CardFrameTitle>Rated calls</CardFrameTitle>
          <CardFrameDescription>Open one to listen and read the AI's feedback.</CardFrameDescription>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>Closed</TableHead>
              <TableHead>Agent</TableHead>
              <TableHead>Contact</TableHead>
              <TableHead>Outcome</TableHead>
              <TableHead className="text-end">AI score</TableHead>
              <TableHead className="min-w-64">Summary</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.calls.length === 0 && <Empty colSpan={6}>No rated call in this period yet.</Empty>}
            {data.calls.map((c) => (
              <TableRow className="align-top" key={c.op_id}>
                <TableCell className="whitespace-nowrap">
                  <a className="hover:underline" href={href("calls", c.call_id)}>
                    {fmtDateTime(c.finished_at)}
                  </a>
                </TableCell>
                <TableCell>{c.agent_name}</TableCell>
                <TableCell className="whitespace-normal">{c.contact && <Bidi as="span" text={c.contact} />}</TableCell>
                <TableCell>
                  <Badge variant={outcomeVariant(outcomes[c.outcome])}>{c.outcome_label}</Badge>
                </TableCell>
                <TableCell className="text-end font-medium tabular-nums">{c.score}</TableCell>
                <TableCell className="whitespace-normal text-sm">
                  {c.summary && <Bidi className="line-clamp-2" text={c.summary} />}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardFrame>
    </>
  );
}
