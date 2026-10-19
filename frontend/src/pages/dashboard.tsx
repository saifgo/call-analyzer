import {
  ArrowRightIcon,
  CircleAlertIcon,
  DownloadCloudIcon,
  PencilLineIcon,
  PhoneIcon,
  PlayIcon,
  RefreshCwIcon,
  XIcon,
} from "lucide-react";
import type * as React from "react";
import { OUTCOME_COLOR, ScoreBadge } from "@/components/call-badges";
import { DateRangeFilter } from "@/components/date-range-filter";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardFrame,
  CardFrameDescription,
  CardFrameHeader,
  CardFrameTitle,
  CardHeader,
  CardPanel,
  CardTitle,
} from "@/components/ui/card";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Meter, MeterIndicator, MeterLabel, MeterTrack } from "@/components/ui/meter";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/lib/api";
import { fmtDateTime, fmtRelative, humanize, numberFmt } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useJob, useOnJobFinished } from "@/lib/jobs";
import { useMe } from "@/lib/me";
import { href, navigate, type Route } from "@/lib/router";
import type { Stats } from "@/lib/types";
import { cn } from "@/lib/utils";

const pct = (n: number, total: number) => (total ? Math.round((n / total) * 100) : 0);

function Kpi({ label, value, hint }: { label: string; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="gap-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="font-semibold text-3xl tabular-nums tracking-tight">{value}</CardTitle>
      </CardHeader>
      {hint && <CardPanel className="text-muted-foreground text-sm">{hint}</CardPanel>}
    </Card>
  );
}

function CoverageMeter({ label, value, total, className }: { label: string; value: number; total: number; className?: string }) {
  return (
    <Meter max={Math.max(total, 1)} value={value}>
      <div className="flex items-center justify-between gap-2">
        <MeterLabel className="font-normal">{label}</MeterLabel>
        <span className="text-muted-foreground text-sm tabular-nums">
          {numberFmt.format(value)} <span className="text-muted-foreground/72">· {pct(value, total)}%</span>
        </span>
      </div>
      <MeterTrack className="rounded-full">
        <MeterIndicator className={cn("rounded-full", className)} />
      </MeterTrack>
    </Meter>
  );
}

function DashboardSkeleton() {
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton className="h-32 rounded-2xl" key={i} />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-64 rounded-2xl" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
      <Skeleton className="h-72 rounded-2xl" />
    </>
  );
}

export function DashboardPage({ route }: { route: Route }): React.ReactElement {
  // Date range kept in the URL like the calls filters; `until` is exclusive.
  const since = route.query.get("since") ?? "";
  const until = route.query.get("until") ?? "";
  const range = { since, until };
  const params = new URLSearchParams(Object.entries(range).filter(([, v]) => v));
  const { data: s, reload } = useApi<Stats>(`/api/stats${params.size ? `?${params}` : ""}`);
  const job = useJob();
  const { isAdmin } = useMe();
  useOnJobFinished(reload);
  const running = !!job.state?.running;

  const scoredCalls = s?.agents.reduce((n, a) => n + (a.avg_score !== null ? a.scored : 0), 0) ?? 0;
  const avgScore = s && scoredCalls
    ? s.agents.reduce((sum, a) => sum + (a.avg_score ?? 0) * (a.avg_score !== null ? a.scored : 0), 0) / scoredCalls
    : null;
  const wins = s?.agents.reduce((n, a) => n + (a.wins ?? 0), 0) ?? 0;
  const minutes = s?.agents.reduce((n, a) => n + (a.minutes ?? 0), 0) ?? 0;
  const outcomeTotal = s?.outcomes.reduce((n, o) => n + o.n, 0) ?? 0;

  const actions = (
    <>
      <Button disabled={running} onClick={() => job.start(["sync"])} variant="outline">
        <RefreshCwIcon aria-hidden="true" />
        {t("dashboard.sync")}
      </Button>
      <Button disabled={running} onClick={() => job.start(["download", "voice", "transcribe", "analyze"])} variant="outline">
        <DownloadCloudIcon aria-hidden="true" />
        {t("dashboard.processNew")}
      </Button>
      <Button disabled={running} onClick={() => job.start(["sync", "download", "transcribe", "analyze", "report"])}>
        <PlayIcon aria-hidden="true" className="rtl:-scale-x-100" />
        {t("dashboard.runAll")}
      </Button>
    </>
  );

  return (
    <>
      <PageHeader
        actions={isAdmin ? actions : undefined}
        description={
          s?.last_call
            ? t("dashboard.latestCall", { date: fmtDateTime(s.last_call), relative: fmtRelative(s.last_call) })
            : isAdmin
              ? t("dashboard.descriptionAdmin")
              : t("dashboard.descriptionAgent")
        }
        title={isAdmin ? t("nav.dashboard") : t("dashboard.myPerformance")}
      />

      <div className="flex flex-wrap items-center gap-2">
        <DateRangeFilter
          onChange={(since, until) => navigate(href("dashboard", null, { since, until }), { replace: true })}
          since={since}
          until={until}
        />
        {since && (
          <Button onClick={() => navigate(href("dashboard"), { replace: true })} variant="ghost">
            <XIcon aria-hidden="true" />
            {t("common.reset")}
          </Button>
        )}
      </div>

      {!s ? (
        <DashboardSkeleton />
      ) : s.total === 0 && since ? (
        <Card>
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <PhoneIcon />
              </EmptyMedia>
              <EmptyTitle>{t("dashboard.noCallsPeriod")}</EmptyTitle>
              <EmptyDescription>{t("dashboard.pickAnotherRange")}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        </Card>
      ) : s.total === 0 ? (
        <Card>
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <PhoneIcon />
              </EmptyMedia>
              <EmptyTitle>{t("dashboard.noCalls")}</EmptyTitle>
              <EmptyDescription>
                {isAdmin ? t("dashboard.emptyAdmin") : t("dashboard.emptyAgent")}
              </EmptyDescription>
            </EmptyHeader>
            {isAdmin && (
              <EmptyContent>
                <Button disabled={running} onClick={() => job.start(["sync"])}>
                  <RefreshCwIcon aria-hidden="true" />
                  {t("dashboard.sync")}
                </Button>
              </EmptyContent>
            )}
          </Empty>
        </Card>
      ) : (
        <>
          {isAdmin && (s.stale > 0 || s.errors > 0) && (
            <div className="grid gap-3 lg:grid-cols-2">
              {s.stale > 0 && (
                <Alert variant="warning">
                  <PencilLineIcon aria-hidden="true" />
                  <AlertTitle>{t("dashboard.staleTitle", { count: s.stale })}</AlertTitle>
                  <AlertDescription>{t("dashboard.staleHint")}</AlertDescription>
                  <AlertAction>
                    <Button render={<a href={href("calls", null, { ...range, status: "stale" })} />} size="sm" variant="outline">
                      {t("dashboard.review")}
                    </Button>
                  </AlertAction>
                </Alert>
              )}
              {s.errors > 0 && (
                <Alert variant="error">
                  <CircleAlertIcon aria-hidden="true" />
                  <AlertTitle>{t("dashboard.errorsTitle", { count: s.errors })}</AlertTitle>
                  <AlertDescription>{t("dashboard.errorsHint")}</AlertDescription>
                  <AlertAction>
                    <Button render={<a href={href("calls", null, { ...range, status: "error" })} />} size="sm" variant="outline">
                      {t("dashboard.viewErrors")}
                    </Button>
                  </AlertAction>
                </Alert>
              )}
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi hint={t("dashboard.minutesRecorded", { count: minutes })} label={t("dashboard.totalCalls")} value={numberFmt.format(s.total)} />
            <Kpi
              hint={t(isAdmin ? "dashboard.analyzedHintAll" : "dashboard.analyzedHintYour", { pct: pct(s.analyzed, s.total) })}
              label={t("calls.status.analyzed")}
              value={numberFmt.format(s.analyzed)}
            />
            <Kpi
              hint={avgScore === null ? t("dashboard.noSalesScore") : t("dashboard.acrossSales")}
              label={t("dashboard.avgSalesScore")}
              value={
                avgScore === null ? "–" : (
                  <>
                    {avgScore.toFixed(1)}
                    <span className="font-normal text-base text-muted-foreground">/10</span>
                  </>
                )
              }
            />
            <Kpi
              hint={t("dashboard.pctAnalyzed", { pct: pct(wins, s.analyzed) })}
              label={t("dashboard.salesNextSteps")}
              value={numberFmt.format(wins)}
            />
          </div>

          <div className={cn("grid gap-4", isAdmin && "lg:grid-cols-2")}>
            {isAdmin && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">{t("dashboard.coverage")}</CardTitle>
                  <CardDescription>{t("dashboard.coverageHint")}</CardDescription>
                </CardHeader>
                <CardPanel className="flex flex-col gap-5">
                  <CoverageMeter label={t("calls.status.downloaded")} total={s.total} value={s.downloaded} />
                  <CoverageMeter className="bg-info" label={t("calls.status.transcribed")} total={s.total} value={s.transcribed} />
                  <CoverageMeter className="bg-success" label={t("calls.status.analyzed")} total={s.total} value={s.analyzed} />
                </CardPanel>
              </Card>
            )}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t("dashboard.outcomes")}</CardTitle>
                <CardDescription>{t("dashboard.outcomesHint")}</CardDescription>
              </CardHeader>
              <CardPanel className="flex flex-col gap-5">
                {s.outcomes.length ? (
                  s.outcomes.map((o) => (
                    <CoverageMeter
                      className={OUTCOME_COLOR[o.outcome] ?? "bg-muted-foreground/64"}
                      key={o.outcome ?? "none"}
                      label={humanize(o.outcome ?? "unknown")}
                      total={outcomeTotal}
                      value={o.n}
                    />
                  ))
                ) : (
                  <p className="text-muted-foreground text-sm">{t("dashboard.noAnalyzed")}</p>
                )}
              </CardPanel>
            </Card>
          </div>

          <CardFrame>
            <CardFrameHeader>
              <CardFrameTitle>{isAdmin ? t("board.agents") : t("dashboard.yourExtensions")}</CardFrameTitle>
              <CardFrameDescription>{isAdmin ? t("dashboard.selectAgent") : t("dashboard.selectExtension")}</CardFrameDescription>
            </CardFrameHeader>
            <Table variant="card">
              <TableHeader>
                <TableRow>
                  <TableHead>{t("dashboard.extension")}</TableHead>
                  <TableHead className="text-end">{t("ops.metric.calls")}</TableHead>
                  <TableHead className="text-end">{t("dashboard.minutes")}</TableHead>
                  <TableHead className="text-end">{t("calls.status.analyzed")}</TableHead>
                  <TableHead className="text-end">{t("dashboard.salesScore")}</TableHead>
                  <TableHead className="text-end">{t("dashboard.salesSlashNext")}</TableHead>
                  <TableHead className="text-end">{t("dashboard.serviceCalls")}</TableHead>
                  <TableHead className="text-end">{t("dashboard.serviceScore")}</TableHead>
                  <TableHead className="w-10">
                    <span className="sr-only">{t("share.open")}</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {s.agents.map((a) => (
                  <TableRow
                    className="cursor-pointer"
                    key={a.agent}
                    onClick={() => navigate(href("calls", null, { ...range, agent: a.agent }))}
                  >
                    <TableCell>
                      <span className="font-medium tabular-nums">{a.agent}</span>
                      {a.name && (
                        <span className="ms-2 text-muted-foreground" dir="auto">
                          {a.name}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-end tabular-nums">{numberFmt.format(a.calls)}</TableCell>
                    <TableCell className="text-end tabular-nums">{numberFmt.format(a.minutes ?? 0)}</TableCell>
                    <TableCell className="text-end tabular-nums">{numberFmt.format(a.analyzed)}</TableCell>
                    <TableCell className="text-end">
                      <ScoreBadge score={a.avg_score} />
                    </TableCell>
                    <TableCell className="text-end tabular-nums">{a.wins ?? 0}</TableCell>
                    <TableCell className="text-end tabular-nums">{a.service_calls ?? 0}</TableCell>
                    <TableCell className="text-end">
                      <ScoreBadge score={a.service_score} />
                    </TableCell>
                    <TableCell className="text-end">
                      <ArrowRightIcon aria-hidden="true" className="ms-auto size-4 text-muted-foreground rtl:rotate-180" />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardFrame>
        </>
      )}
    </>
  );
}
