import { CircleAlertIcon, RefreshCwIcon, Undo2Icon, XIcon } from "lucide-react";
import * as React from "react";
import { DeskAlerts } from "@/components/desk-alerts";
import { GoalBars, PauseBadge } from "@/components/goal-progress";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardFrame, CardFrameHeader, CardFrameTitle, CardPanel } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toastManager } from "@/components/ui/toast";
import { Tooltip, TooltipPopup, TooltipTrigger } from "@/components/ui/tooltip";
import { api, useApi } from "@/lib/api";
import { campaignText, useOpConfig } from "@/lib/campaign-text";
import { Bidi } from "@/lib/bidi";
import { fmtDateTime, fmtDuration, fmtRelative, humanize, numberFmt, parseDate } from "@/lib/format";
import { pct } from "@/components/desk-charts";
import { t } from "@/lib/i18n";
import { contactName, fmtGoalValue, goalStatus, METRIC_LABELS, outcomeVariant, secondsFrom, STAGE_VARIANT, STATE, useNow } from "@/lib/operations";
import type { OpBoard, OpProgress } from "@/lib/types";
import { cn } from "@/lib/utils";

const REFRESH_MS = 10_000;

/** "Calls 12/40 · Wins 1/3", each coloured by whether it keeps pace. */
function ProgressLine({ progress }: { progress: OpProgress[] }) {
  if (!progress.length) return <span className="text-muted-foreground">–</span>;
  return (
    <span className="flex flex-wrap justify-end gap-x-3 gap-y-0.5 text-xs">
      {progress.map((p) => {
        const status = goalStatus(p);
        return (
          <span className="whitespace-nowrap" key={p.metric}>
            <span className="text-muted-foreground">{METRIC_LABELS[p.metric]} </span>
            <span
              className={cn(
                "font-medium tabular-nums",
                status === "behind" && "text-warning-foreground",
                status === "done" && "text-success-foreground",
              )}
            >
              {fmtGoalValue(p.metric, p.value)}/{fmtGoalValue(p.metric, p.target)}
            </span>
          </span>
        );
      })}
    </span>
  );
}

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: React.ReactNode }) {
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

export function OperationsBoard(): React.ReactElement {
  const { data: config } = useOpConfig();
  const { data, error, reload } = useApi<OpBoard>("/api/operations/board");
  const now = useNow(true, 1000);
  React.useEffect(() => {
    const timer = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [reload]);

  const run = async (path: string, method: string, success: string) => {
    try {
      await api(path, { method });
      toastManager.add({ title: success, type: "success" });
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: t("common.didntWork"), type: "error" });
    }
    reload();
  };

  if (error && !data) {
    return (
      <Alert variant="error">
        <CircleAlertIcon aria-hidden="true" />
        <AlertTitle>{t("board.loadFailed")}</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  if (!data || !config) {
    return (
      <div className="flex flex-col gap-6">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton className="h-24 rounded-2xl" key={i} />
          ))}
        </div>
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    );
  }

  const outcomes = Object.fromEntries(config.outcomes.map((o) => [o.value, o]));
  const stages = Object.fromEntries(config.stages.map((s) => [s.value, s.label]));
  const working = data.agents.filter((a) => a.state !== "offline" && a.state !== "paused");
  const onCall = data.agents.filter((a) => a.state === "on_call").length;
  const doneToday = Object.values(data.outcomes_today).reduce((a, b) => a + b, 0);
  const q = data.queue;
  const inb = data.inbound_today;

  return (
    <>
      <DeskAlerts />
      {q.error && (
        <Alert variant="error">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>{t("board.queueFailed")}</AlertTitle>
          <AlertDescription>{q.error}</AlertDescription>
        </Alert>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Stat hint={t("board.onCallNow", { count: onCall })} label={t("board.agentsTaking")} value={working.length} />
        <Stat
          hint={q.no_phone ? t("board.noPhone", { count: q.no_phone }) : t("board.withPhone")}
          label={t("board.waitingInQueue")}
          value={q.waiting === null ? "–" : numberFmt.format(q.waiting)}
        />
        <Stat hint={t("board.scheduledTotal", { count: q.scheduled })} label={t("board.callbacksDue")} value={q.due_callbacks} />
        <Stat
          hint={
            Object.entries(data.outcomes_today)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 3)
              .map(([o, n]) => `${n} ${(outcomes[o]?.label ?? humanize(o)).toLocaleLowerCase()}`)
              .join(" · ") || t("wall.noCallClosed")
          }
          label={t("board.closedToday")}
          value={doneToday}
        />
        <Stat
          hint={t("inbound.todayHint", {
            missed: inb.missed,
            rate: pct(inb.answer_rate),
            waiting: inb.waiting,
          })}
          label={t("inbound.todayLabel")}
          value={`${inb.answered}/${inb.calls}`}
        />
      </div>

      {data.team_progress.length > 0 && (
        <Card>
          <CardPanel className="flex flex-col gap-2 p-4">
            <span className="text-muted-foreground text-xs">
              {t("board.teamTargetsToday", { end: data.workday.end, start: data.workday.start })}
            </span>
            <GoalBars progress={data.team_progress} />
          </CardPanel>
        </Card>
      )}

      {data.queues.length > 1 && (
        <CardFrame>
          <CardFrameHeader>
            <CardFrameTitle>{t("board.queues")}</CardFrameTitle>
          </CardFrameHeader>
          <Table variant="card">
            <TableHeader>
              <TableRow>
                <TableHead>{t("board.campaign")}</TableHead>
                <TableHead>{t("board.callingHours")}</TableHead>
                <TableHead className="text-end">{t("board.waiting")}</TableHead>
                <TableHead className="text-end">{t("board.callbacksDue")}</TableHead>
                <TableHead className="text-end">{t("board.scheduled")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.queues.map((queue) => (
                <TableRow key={queue.campaign_id}>
                  <TableCell className="font-medium">{campaignText(queue.campaign)}</TableCell>
                  <TableCell>
                    <Badge variant={queue.open ? "success" : "secondary"}>{queue.open ? t("board.open") : t("board.closed")}</Badge>
                    <span className="ms-2 text-muted-foreground text-xs">{queue.hours}</span>
                  </TableCell>
                  <TableCell className="text-end tabular-nums">
                    {queue.error ? (
                      <Tooltip>
                        <TooltipTrigger render={<span className="text-destructive-foreground" />}>–</TooltipTrigger>
                        <TooltipPopup>{queue.error}</TooltipPopup>
                      </Tooltip>
                    ) : (
                      numberFmt.format(queue.waiting ?? 0)
                    )}
                  </TableCell>
                  <TableCell className="text-end tabular-nums">{queue.due_callbacks}</TableCell>
                  <TableCell className="text-end tabular-nums">{queue.scheduled}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardFrame>
      )}

      <CardFrame>
        <CardFrameHeader>
          <CardFrameTitle>{t("board.agents")}</CardFrameTitle>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>{t("shell.agent")}</TableHead>
              <TableHead>{t("board.status")}</TableHead>
              <TableHead>{t("ops.contact")}</TableHead>
              <TableHead className="text-end">{t("dates.today")}</TableHead>
              <TableHead className="w-10">
                <span className="sr-only">{t("board.actions")}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.agents.length === 0 && (
              <TableRow>
                <TableCell className="text-muted-foreground" colSpan={5}>
                  {t("board.nobodyYet")}
                </TableCell>
              </TableRow>
            )}
            {data.agents.map((a) => (
              <TableRow key={a.username}>
                <TableCell>
                  <div className="flex flex-col">
                    <span className="font-medium">{a.name}</span>
                    {data.queues.length > 1 && a.campaign && <span className="text-muted-foreground text-xs">{campaignText(a.campaign)}</span>}
                  </div>
                </TableCell>
                <TableCell>
                  {a.state === "paused" && a.pause ? (
                    <PauseBadge now={now} pause={a.pause} />
                  ) : (
                    <Badge variant={STATE[a.state].variant}>{STATE[a.state].label}</Badge>
                  )}
                  {a.state === "offline" && a.last_seen ? (
                    <span className="ms-2 text-muted-foreground text-xs">{t("board.seen", { time: fmtRelative(a.last_seen) })}</span>
                  ) : (
                    !(a.state === "paused" && a.pause) &&
                    secondsFrom(a.state_since, now) !== null && (
                      <span className="ms-2 text-muted-foreground text-xs tabular-nums">
                        {fmtDuration(secondsFrom(a.state_since, now) ?? 0)}
                      </span>
                    )
                  )}
                </TableCell>
                <TableCell className="whitespace-normal">
                  {a.current ? (
                    <div className="flex flex-col">
                      <Bidi as="span" text={contactName(a.current)} />
                      <span className="text-muted-foreground text-xs">
                        {a.current.source === "callback"
                          ? `${t("board.callback")} · `
                          : a.current.source === "direct"
                            ? `${t("board.salesCall")} · `
                            : ""}
                        {t("wall.since", { time: fmtRelative(a.current.call_started_at ?? a.current.assigned_at) })}
                      </span>
                    </div>
                  ) : (
                    <span className="text-muted-foreground">–</span>
                  )}
                </TableCell>
                <TableCell className="text-end tabular-nums">
                  {a.progress.length ? (
                    <ProgressLine progress={a.progress} />
                  ) : (
                    <span>{t("board.closedWon", { done: a.today.done, won: a.today.success })}</span>
                  )}
                  {a.today.pause_seconds > 0 && (
                    <span className="block text-muted-foreground text-xs">{t("board.pausedFor", { time: fmtDuration(a.today.pause_seconds) })}</span>
                  )}
                </TableCell>
                <TableCell>
                  {a.current && (
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <Button
                            aria-label={t("board.giveBack")}
                            onClick={() => run(`/api/operations/${a.current?.id}/release`, "POST", t("board.givenBack"))}
                            size="icon-sm"
                            variant="ghost"
                          />
                        }
                      >
                        <Undo2Icon aria-hidden="true" className="rtl:-scale-x-100" />
                      </TooltipTrigger>
                      <TooltipPopup>{t("board.giveBack")}</TooltipPopup>
                    </Tooltip>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardFrame>

      <CardFrame>
        <CardFrameHeader>
          <CardFrameTitle className="flex items-center gap-2">
            {t("inbound.missedTitle")}
            {data.missed.length > 0 && <Badge variant="warning">{data.missed.length}</Badge>}
          </CardFrameTitle>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>{t("inbound.waiting")}</TableHead>
              <TableHead>{t("ops.contact")}</TableHead>
              <TableHead>{t("inbound.tries")}</TableHead>
              <TableHead>{t("inbound.rangFor")}</TableHead>
              <TableHead>{t("inbound.callsBack")}</TableHead>
              <TableHead className="w-10">
                <span className="sr-only">{t("inbound.dismiss")}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.missed.length === 0 && (
              <TableRow>
                <TableCell className="text-muted-foreground" colSpan={6}>
                  {t("inbound.noMissed")}
                </TableCell>
              </TableRow>
            )}
            {data.missed.map((m) => (
              <TableRow key={m.key}>
                <TableCell className="whitespace-nowrap">
                  <Badge variant={m.waiting_minutes >= 10 ? "error" : "warning"}>{fmtDuration(m.waiting_minutes * 60)}</Badge>
                  <span className="ms-2 text-muted-foreground text-xs">{fmtDateTime(m.first_rang_at)}</span>
                </TableCell>
                <TableCell className="whitespace-normal">
                  <Bidi as="span" text={m.contact_name ?? m.number} />
                  {m.contact_name && (
                    <span className="ms-2 text-muted-foreground text-xs tabular-nums" dir="ltr">
                      {m.number}
                    </span>
                  )}
                </TableCell>
                <TableCell className="tabular-nums">
                  {m.tries}
                  {m.busy && <span className="ms-1 text-muted-foreground text-xs">{t("inbound.someBusy")}</span>}
                </TableCell>
                <TableCell className="whitespace-normal text-muted-foreground">{m.agents.join(", ")}</TableCell>
                <TableCell>
                  {m.serving ? (
                    <Badge variant="info">{t("inbound.callingBack", { name: m.serving.agent_name })}</Badge>
                  ) : (
                    <span>
                      {m.prefer_name}
                      {m.knows && <span className="ms-1 text-muted-foreground text-xs">{t("inbound.knowsThem")}</span>}
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  <Button
                    aria-label={t("inbound.dismiss")}
                    onClick={() => run(`/api/operations/missed/${encodeURIComponent(m.key)}/dismiss`, "POST", t("inbound.dismissed"))}
                    size="icon-sm"
                    variant="ghost"
                  >
                    <XIcon aria-hidden="true" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardFrame>

      <CardFrame>
        <CardFrameHeader>
          <CardFrameTitle>{t("board.scheduledCallbacks")}</CardFrameTitle>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>{t("board.due")}</TableHead>
              <TableHead>{t("ops.contact")}</TableHead>
              <TableHead>{t("board.bookedBy")}</TableHead>
              <TableHead>{t("board.for")}</TableHead>
              <TableHead>{t("board.note")}</TableHead>
              <TableHead className="w-10">
                <span className="sr-only">{t("common.cancel")}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.callbacks.length === 0 && (
              <TableRow>
                <TableCell className="text-muted-foreground" colSpan={6}>
                  {t("board.noCallbacks")}
                </TableCell>
              </TableRow>
            )}
            {data.callbacks.map((cb) => {
              const due = (parseDate(cb.due_at)?.getTime() ?? 0) <= now;
              return (
                <TableRow key={cb.id}>
                  <TableCell className="whitespace-nowrap">
                    <Badge variant={due ? "warning" : "secondary"}>{due ? t("board.due") : fmtRelative(cb.due_at)}</Badge>
                    <span className="ms-2 text-muted-foreground text-xs">{fmtDateTime(cb.due_at)}</span>
                  </TableCell>
                  <TableCell className="whitespace-normal">
                    <Bidi as="span" text={contactName(cb)} />
                  </TableCell>
                  <TableCell>{cb.scheduled_by_name ?? "–"}</TableCell>
                  <TableCell>{cb.assign_to_name ?? t("board.anyone")}</TableCell>
                  <TableCell className="max-w-64 whitespace-normal text-muted-foreground">
                    {cb.callback_note && <Bidi as="span" text={cb.callback_note} />}
                  </TableCell>
                  <TableCell>
                    <Button
                      aria-label={t("board.cancelCallback")}
                      onClick={() => run(`/api/operations/callbacks/${cb.id}`, "DELETE", t("board.callbackCancelled"))}
                      size="icon-sm"
                      variant="ghost"
                    >
                      <XIcon aria-hidden="true" />
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardFrame>

      <CardFrame>
        <CardFrameHeader>
          <CardFrameTitle>{t("board.latestResults")}</CardFrameTitle>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>{t("insights.closed")}</TableHead>
              <TableHead>{t("shell.agent")}</TableHead>
              <TableHead>{t("ops.contact")}</TableHead>
              <TableHead>{t("insights.outcome")}</TableHead>
              <TableHead>{t("board.stage")}</TableHead>
              <TableHead className="min-w-56">{t("board.note")}</TableHead>
              <TableHead>{t("nav.group.crm")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.recent.length === 0 && (
              <TableRow>
                <TableCell className="text-muted-foreground" colSpan={7}>
                  {t("board.noResults")}
                </TableCell>
              </TableRow>
            )}
            {data.recent.map((r) => (
              <TableRow className="align-top" key={r.id}>
                <TableCell className="whitespace-nowrap">{fmtDateTime(r.finished_at)}</TableCell>
                <TableCell>{r.agent_name}</TableCell>
                <TableCell className="whitespace-normal">
                  {r.lead?.url ? (
                    <a className="hover:underline" href={r.lead.url} rel="noreferrer" target="_blank">
                      <Bidi as="span" text={contactName(r)} />
                    </a>
                  ) : (
                    <Bidi as="span" text={contactName(r)} />
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant={outcomeVariant(outcomes[r.outcome ?? ""])}>
                    {outcomes[r.outcome ?? ""]?.label ?? humanize(r.outcome)}
                  </Badge>
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  {r.stage_after && r.stage_after !== r.stage_before ? (
                    <Badge variant={STAGE_VARIANT[r.stage_after] ?? "secondary"}>
                      {stages[r.stage_after] ?? humanize(r.stage_after)}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground text-xs">{t("board.unchanged")}</span>
                  )}
                </TableCell>
                <TableCell className="whitespace-normal text-sm">
                  {r.note && <Bidi className="line-clamp-3" text={r.note} />}
                </TableCell>
                <TableCell>
                  {r.test ? (
                    <Badge variant="outline">{t("board.testNotSent")}</Badge>
                  ) : r.crm_error ? (
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <Button
                            onClick={() => run(`/api/operations/${r.id}/sync`, "POST", t("board.resent"))}
                            size="xs"
                            variant="destructive-outline"
                          />
                        }
                      >
                        <RefreshCwIcon aria-hidden="true" />
                        {t("common.retry")}
                      </TooltipTrigger>
                      <TooltipPopup className="max-w-sm">{r.crm_error}</TooltipPopup>
                    </Tooltip>
                  ) : (
                    <Badge variant="success">{t("board.saved")}</Badge>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardFrame>
    </>
  );
}
