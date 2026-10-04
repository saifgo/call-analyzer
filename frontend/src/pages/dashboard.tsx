import {
  ArrowRightIcon,
  CircleAlertIcon,
  DownloadCloudIcon,
  PencilLineIcon,
  PhoneIcon,
  PlayIcon,
  RefreshCwIcon,
} from "lucide-react";
import type * as React from "react";
import { OUTCOME_COLOR, ScoreBadge } from "@/components/call-badges";
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
import { useJob, useOnJobFinished } from "@/lib/jobs";
import { useMe } from "@/lib/me";
import { href, navigate } from "@/lib/router";
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

export function DashboardPage(): React.ReactElement {
  const { data: s, reload } = useApi<Stats>("/api/stats");
  const job = useJob();
  const { isAdmin } = useMe();
  useOnJobFinished(reload);
  const running = !!job.state?.running;

  const analyzedWithScore = s?.agents.reduce((n, a) => n + (a.avg_score !== null ? a.analyzed : 0), 0) ?? 0;
  const avgScore = s && analyzedWithScore
    ? s.agents.reduce((sum, a) => sum + (a.avg_score ?? 0) * (a.avg_score !== null ? a.analyzed : 0), 0) / analyzedWithScore
    : null;
  const wins = s?.agents.reduce((n, a) => n + (a.wins ?? 0), 0) ?? 0;
  const minutes = s?.agents.reduce((n, a) => n + (a.minutes ?? 0), 0) ?? 0;
  const outcomeTotal = s?.outcomes.reduce((n, o) => n + o.n, 0) ?? 0;

  const actions = (
    <>
      <Button disabled={running} onClick={() => job.start(["sync"])} variant="outline">
        <RefreshCwIcon aria-hidden="true" />
        Sync call list
      </Button>
      <Button disabled={running} onClick={() => job.start(["download", "transcribe", "analyze"])} variant="outline">
        <DownloadCloudIcon aria-hidden="true" />
        Process new calls
      </Button>
      <Button disabled={running} onClick={() => job.start(["sync", "download", "transcribe", "analyze", "report"])}>
        <PlayIcon aria-hidden="true" />
        Run full pipeline
      </Button>
    </>
  );

  return (
    <>
      <PageHeader
        actions={isAdmin ? actions : undefined}
        description={
          s?.last_call
            ? `Latest call ${fmtRelative(s.last_call)} · ${fmtDateTime(s.last_call)}`
            : isAdmin
              ? "Pipeline progress, agent performance and call outcomes."
              : "Your calls, scores and outcomes."
        }
        title={isAdmin ? "Dashboard" : "My performance"}
      />

      {!s ? (
        <DashboardSkeleton />
      ) : s.total === 0 ? (
        <Card>
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <PhoneIcon />
              </EmptyMedia>
              <EmptyTitle>No calls yet</EmptyTitle>
              <EmptyDescription>
                {isAdmin
                  ? "Sync the call list from GoVoice to start analyzing your team’s calls."
                  : "Your calls appear here once they are analyzed. Ask your manager if this takes long."}
              </EmptyDescription>
            </EmptyHeader>
            {isAdmin && (
              <EmptyContent>
                <Button disabled={running} onClick={() => job.start(["sync"])}>
                  <RefreshCwIcon aria-hidden="true" />
                  Sync call list
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
                  <AlertTitle>
                    {s.stale} {s.stale === 1 ? "call needs" : "calls need"} re-analysis
                  </AlertTitle>
                  <AlertDescription>The transcript was edited after the feedback was written.</AlertDescription>
                  <AlertAction>
                    <Button render={<a href={href("calls", null, { status: "stale" })} />} size="sm" variant="outline">
                      Review
                    </Button>
                  </AlertAction>
                </Alert>
              )}
              {s.errors > 0 && (
                <Alert variant="error">
                  <CircleAlertIcon aria-hidden="true" />
                  <AlertTitle>
                    {s.errors} {s.errors === 1 ? "call" : "calls"} failed to process
                  </AlertTitle>
                  <AlertDescription>Open them to see the error, then retry.</AlertDescription>
                  <AlertAction>
                    <Button render={<a href={href("calls", null, { status: "error" })} />} size="sm" variant="outline">
                      View errors
                    </Button>
                  </AlertAction>
                </Alert>
              )}
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi hint={`${numberFmt.format(minutes)} minutes recorded`} label="Total calls" value={numberFmt.format(s.total)} />
            <Kpi
              hint={`${pct(s.analyzed, s.total)}% of ${isAdmin ? "all" : "your"} calls have feedback`}
              label="Analyzed"
              value={numberFmt.format(s.analyzed)}
            />
            <Kpi
              hint={avgScore === null ? "No analyzed calls yet" : "Across every analyzed call"}
              label="Average score"
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
              hint={`${pct(wins, s.analyzed)}% of analyzed calls`}
              label="Sales & next steps"
              value={numberFmt.format(wins)}
            />
          </div>

          <div className={cn("grid gap-4", isAdmin && "lg:grid-cols-2")}>
            {isAdmin && (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Pipeline coverage</CardTitle>
                  <CardDescription>How far each call has gone through the pipeline.</CardDescription>
                </CardHeader>
                <CardPanel className="flex flex-col gap-5">
                  <CoverageMeter label="Downloaded" total={s.total} value={s.downloaded} />
                  <CoverageMeter className="bg-info" label="Transcribed" total={s.total} value={s.transcribed} />
                  <CoverageMeter className="bg-success" label="Analyzed" total={s.total} value={s.analyzed} />
                </CardPanel>
              </Card>
            )}
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Outcomes</CardTitle>
                <CardDescription>Result of each analyzed call.</CardDescription>
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
                  <p className="text-muted-foreground text-sm">No analyzed calls yet.</p>
                )}
              </CardPanel>
            </Card>
          </div>

          <CardFrame>
            <CardFrameHeader>
              <CardFrameTitle>{isAdmin ? "Agents" : "Your extensions"}</CardFrameTitle>
              <CardFrameDescription>
                {isAdmin ? "Select an agent to see their calls." : "Select an extension to see its calls."}
              </CardFrameDescription>
            </CardFrameHeader>
            <Table variant="card">
              <TableHeader>
                <TableRow>
                  <TableHead>Extension</TableHead>
                  <TableHead className="text-right">Calls</TableHead>
                  <TableHead className="text-right">Minutes</TableHead>
                  <TableHead className="text-right">Analyzed</TableHead>
                  <TableHead className="text-right">Avg score</TableHead>
                  <TableHead className="text-right">Sales / next steps</TableHead>
                  <TableHead className="w-10">
                    <span className="sr-only">Open</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {s.agents.map((a) => (
                  <TableRow
                    className="cursor-pointer"
                    key={a.agent}
                    onClick={() => navigate(href("calls", null, { agent: a.agent }))}
                  >
                    <TableCell>
                      <span className="font-medium tabular-nums">{a.agent}</span>
                      {a.name && (
                        <span className="ms-2 text-muted-foreground" dir="auto">
                          {a.name}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{numberFmt.format(a.calls)}</TableCell>
                    <TableCell className="text-right tabular-nums">{numberFmt.format(a.minutes ?? 0)}</TableCell>
                    <TableCell className="text-right tabular-nums">{numberFmt.format(a.analyzed)}</TableCell>
                    <TableCell className="text-right">
                      <ScoreBadge score={a.avg_score} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{a.wins ?? 0}</TableCell>
                    <TableCell className="text-right">
                      <ArrowRightIcon aria-hidden="true" className="ms-auto size-4 text-muted-foreground" />
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
