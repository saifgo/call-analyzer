import { CircleAlertIcon, InfoIcon } from "lucide-react";
import type * as React from "react";
import { FilterBar, GapBar, pct, RateBars, score, Stat, useFilters } from "@/components/desk-charts";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardDescription, CardFrame, CardFrameDescription, CardFrameHeader, CardFrameTitle, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/lib/api";
import { campaignText, useOpConfig } from "@/lib/campaign-text";
import { Bidi } from "@/lib/bidi";
import { fmtDateTime, fmtDuration, humanize, numberFmt } from "@/lib/format";
import { t } from "@/lib/i18n";
import { outcomeVariant } from "@/lib/operations";
import { href, type Route } from "@/lib/router";
import type { OpInsights } from "@/lib/types";

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
  const { data: config } = useOpConfig();
  const { data, error } = useApi<OpInsights>(`/api/operations/insights?${filters.query}`);
  const outcomes = Object.fromEntries((config?.outcomes ?? []).map((o) => [o.value, o]));

  if (error && !data) {
    return (
      <Alert variant="error">
        <CircleAlertIcon aria-hidden="true" />
        <AlertTitle>{t("insights.loadFailed")}</AlertTitle>
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
          <AlertTitle>{t("insights.fewLinked", { linked: data.linked, total: data.total })}</AlertTitle>
          <AlertDescription>{t("insights.fewLinkedHint")}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat
          hint={t("insights.deskCallsHint", { linked: data.linked, rated: data.rated })}
          label={t("insights.deskCalls")}
          value={numberFmt.format(data.total)}
        />
        <Stat hint={t("insights.overRatedWins", { count: data.won_rated })} label={t("insights.scoreOfWins")} value={score(o.won)} />
        <Stat
          hint={o.gap === null ? t("insights.needsRated") : t("insights.pointsForWins", { gap: `${o.gap > 0 ? "+" : ""}${o.gap.toFixed(1)}` })}
          label={t("insights.scoreOfOthers")}
          value={score(o.other)}
        />
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t("insights.winRateByScore")}</CardTitle>
            <CardDescription>{t("insights.winRateByScoreHint")}</CardDescription>
          </CardHeader>
          <CardPanel>
            <RateBars
              bars={data.bands.map((b) => ({
                detail: t("insights.bandDetail", { band: b.band, calls: b.calls, wins: b.success }),
                label: b.band,
                n: b.calls,
                rate: b.success_rate,
              }))}
            />
          </CardPanel>
        </Card>
        <CardFrame>
          <CardFrameHeader>
            <CardFrameTitle>{t("insights.winsDoBetter")}</CardFrameTitle>
            <CardFrameDescription>{t("insights.winsDoBetterHint")}</CardFrameDescription>
          </CardFrameHeader>
          <Table variant="card">
            <TableHeader>
              <TableRow>
                <TableHead>{t("insights.criterion")}</TableHead>
                <TableHead className="text-end">{t("ops.metric.wins")}</TableHead>
                <TableHead className="text-end">{t("insights.others")}</TableHead>
                <TableHead>{t("insights.gap")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.drivers.length === 0 && <Empty colSpan={4}>{t("insights.noRated")}</Empty>}
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
          <CardFrameTitle>{t("insights.byOutcome")}</CardFrameTitle>
          <CardFrameDescription>{t("insights.byOutcomeHint")}</CardFrameDescription>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>{t("insights.outcome")}</TableHead>
              <TableHead className="text-end">{t("ops.metric.calls")}</TableHead>
              <TableHead className="text-end">{t("insights.rated")}</TableHead>
              <TableHead className="text-end">{t("kpis.aiScore")}</TableHead>
              <TableHead className="text-end">{t("jobs.step.voice")}</TableHead>
              <TableHead className="text-end">{t("kpis.avgCall")}</TableHead>
              <TableHead>{t("insights.aiSaid")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.outcomes.length === 0 && <Empty colSpan={7}>{t("kpis.noCalls")}</Empty>}
            {data.outcomes.map((row) => (
              <TableRow key={row.outcome}>
                <TableCell>
                  <Badge variant={outcomeVariant(outcomes[row.outcome])}>{outcomes[row.outcome]?.label ?? campaignText(row.label)}</Badge>
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
          <CardFrameTitle>{t("kpis.byAgent")}</CardFrameTitle>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>{t("shell.agent")}</TableHead>
              <TableHead className="text-end">{t("ops.metric.calls")}</TableHead>
              <TableHead className="text-end">{t("insights.winsReached")}</TableHead>
              <TableHead className="text-end">{t("kpis.aiScore")}</TableHead>
              <TableHead className="text-end">{t("insights.onWins")}</TableHead>
              <TableHead className="text-end">{t("insights.onOthers")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.agents.length === 0 && <Empty colSpan={6}>{t("kpis.noCalls")}</Empty>}
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
          <CardFrameTitle>{t("insights.ratedCalls")}</CardFrameTitle>
          <CardFrameDescription>{t("insights.ratedCallsHint")}</CardFrameDescription>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>{t("insights.closed")}</TableHead>
              <TableHead>{t("shell.agent")}</TableHead>
              <TableHead>{t("ops.contact")}</TableHead>
              <TableHead>{t("insights.outcome")}</TableHead>
              <TableHead className="text-end">{t("kpis.aiScore")}</TableHead>
              <TableHead className="min-w-64">{t("insights.summary")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.calls.length === 0 && <Empty colSpan={6}>{t("insights.noRated")}</Empty>}
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
                  <Badge variant={outcomeVariant(outcomes[c.outcome])}>{outcomes[c.outcome]?.label ?? campaignText(c.outcome_label)}</Badge>
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
