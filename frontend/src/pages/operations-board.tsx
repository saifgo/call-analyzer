import { CircleAlertIcon, RefreshCwIcon, Undo2Icon, XIcon } from "lucide-react";
import * as React from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardFrame, CardFrameHeader, CardFrameTitle, CardPanel } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toastManager } from "@/components/ui/toast";
import { Tooltip, TooltipPopup, TooltipTrigger } from "@/components/ui/tooltip";
import { api, useApi } from "@/lib/api";
import { Bidi } from "@/lib/bidi";
import { fmtDateTime, fmtRelative, humanize, numberFmt, parseDate } from "@/lib/format";
import { outcomeVariant, STAGE_VARIANT, useNow } from "@/lib/operations";
import type { OpAgentState, OpBoard, OpCall, OpConfig } from "@/lib/types";

const REFRESH_MS = 10_000;

const STATE: Record<OpAgentState, { label: string; variant: "success" | "info" | "warning" | "secondary" | "outline" }> = {
  offline: { label: "Offline", variant: "outline" },
  on_call: { label: "On a call", variant: "success" },
  paused: { label: "Paused", variant: "secondary" },
  ready: { label: "Waiting for a contact", variant: "info" },
  serving: { label: "About to call", variant: "info" },
  wrap_up: { label: "Closing a call", variant: "warning" },
};

function contactName(op: OpCall | null): string {
  const name = op?.lead?.contact?.name ?? op?.lead?.name ?? "Contact";
  return op?.test ? `${name} (test)` : name;
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
  const { data: config } = useApi<OpConfig>("/api/operations/config");
  const { data, error, reload } = useApi<OpBoard>("/api/operations/board");
  const now = useNow(true, REFRESH_MS);
  React.useEffect(() => {
    const t = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(t);
  }, [reload]);

  const run = async (path: string, method: string, success: string) => {
    try {
      await api(path, { method });
      toastManager.add({ title: success, type: "success" });
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "That didn't work", type: "error" });
    }
    reload();
  };

  if (error && !data) {
    return (
      <Alert variant="error">
        <CircleAlertIcon aria-hidden="true" />
        <AlertTitle>Couldn't load the team board</AlertTitle>
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

  return (
    <>
      {q.error && (
        <Alert variant="error">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>Couldn't read the queue from the CRM</AlertTitle>
          <AlertDescription>{q.error}</AlertDescription>
        </Alert>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat hint={`${onCall} on a call right now`} label="Agents taking calls" value={working.length} />
        <Stat
          hint={q.no_phone ? `${numberFmt.format(q.no_phone)} more have no phone number` : "Contacts with a phone number"}
          label="Waiting in the queue"
          value={q.waiting === null ? "–" : numberFmt.format(q.waiting)}
        />
        <Stat hint={`${q.scheduled} scheduled in total`} label="Callbacks due" value={q.due_callbacks} />
        <Stat
          hint={
            Object.entries(data.outcomes_today)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 3)
              .map(([o, n]) => `${n} ${(outcomes[o]?.label ?? humanize(o)).toLowerCase()}`)
              .join(" · ") || "No call closed yet"
          }
          label="Calls closed today"
          value={doneToday}
        />
      </div>

      {data.queues.length > 1 && (
        <CardFrame>
          <CardFrameHeader>
            <CardFrameTitle>Queues</CardFrameTitle>
          </CardFrameHeader>
          <Table variant="card">
            <TableHeader>
              <TableRow>
                <TableHead>Campaign</TableHead>
                <TableHead>Calling hours</TableHead>
                <TableHead className="text-end">Waiting</TableHead>
                <TableHead className="text-end">Callbacks due</TableHead>
                <TableHead className="text-end">Scheduled</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.queues.map((queue) => (
                <TableRow key={queue.campaign_id}>
                  <TableCell className="font-medium">{queue.campaign}</TableCell>
                  <TableCell>
                    <Badge variant={queue.open ? "success" : "secondary"}>{queue.open ? "Open" : "Closed"}</Badge>
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
          <CardFrameTitle>Agents</CardFrameTitle>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>Agent</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Contact</TableHead>
              <TableHead className="text-end">Closed today</TableHead>
              <TableHead className="w-10">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.agents.length === 0 && (
              <TableRow>
                <TableCell className="text-muted-foreground" colSpan={5}>
                  Nobody has opened the call desk yet.
                </TableCell>
              </TableRow>
            )}
            {data.agents.map((a) => (
              <TableRow key={a.username}>
                <TableCell>
                  <div className="flex flex-col">
                    <span className="font-medium">{a.name}</span>
                    {data.queues.length > 1 && a.campaign && <span className="text-muted-foreground text-xs">{a.campaign}</span>}
                  </div>
                </TableCell>
                <TableCell>
                  <Badge variant={STATE[a.state].variant}>{STATE[a.state].label}</Badge>
                  {a.state === "offline" && a.last_seen && (
                    <span className="ms-2 text-muted-foreground text-xs">seen {fmtRelative(a.last_seen)}</span>
                  )}
                </TableCell>
                <TableCell className="whitespace-normal">
                  {a.current ? (
                    <div className="flex flex-col">
                      <Bidi as="span" text={contactName(a.current)} />
                      <span className="text-muted-foreground text-xs">
                        {a.current.source === "callback" ? "Callback · " : a.current.source === "direct" ? "Sales call · " : ""}
                        since {fmtRelative(a.current.call_started_at ?? a.current.assigned_at)}
                      </span>
                    </div>
                  ) : (
                    <span className="text-muted-foreground">–</span>
                  )}
                </TableCell>
                <TableCell className="text-end tabular-nums">{a.done_today}</TableCell>
                <TableCell>
                  {a.current && (
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <Button
                            aria-label="Give the contact back to the queue"
                            onClick={() =>
                              run(`/api/operations/${a.current?.id}/release`, "POST", "Contact given back to the queue")
                            }
                            size="icon-sm"
                            variant="ghost"
                          />
                        }
                      >
                        <Undo2Icon aria-hidden="true" />
                      </TooltipTrigger>
                      <TooltipPopup>Give the contact back to the queue</TooltipPopup>
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
          <CardFrameTitle>Scheduled callbacks</CardFrameTitle>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>Due</TableHead>
              <TableHead>Contact</TableHead>
              <TableHead>Booked by</TableHead>
              <TableHead>For</TableHead>
              <TableHead>Note</TableHead>
              <TableHead className="w-10">
                <span className="sr-only">Cancel</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.callbacks.length === 0 && (
              <TableRow>
                <TableCell className="text-muted-foreground" colSpan={6}>
                  No callback scheduled.
                </TableCell>
              </TableRow>
            )}
            {data.callbacks.map((cb) => {
              const due = (parseDate(cb.due_at)?.getTime() ?? 0) <= now;
              return (
                <TableRow key={cb.id}>
                  <TableCell className="whitespace-nowrap">
                    <Badge variant={due ? "warning" : "secondary"}>{due ? "Due" : fmtRelative(cb.due_at)}</Badge>
                    <span className="ms-2 text-muted-foreground text-xs">{fmtDateTime(cb.due_at)}</span>
                  </TableCell>
                  <TableCell className="whitespace-normal">
                    <Bidi as="span" text={contactName(cb)} />
                  </TableCell>
                  <TableCell>{cb.scheduled_by_name ?? "–"}</TableCell>
                  <TableCell>{cb.assign_to_name ?? "Anyone"}</TableCell>
                  <TableCell className="max-w-64 whitespace-normal text-muted-foreground">
                    {cb.callback_note && <Bidi as="span" text={cb.callback_note} />}
                  </TableCell>
                  <TableCell>
                    <Button
                      aria-label="Cancel callback"
                      onClick={() => run(`/api/operations/callbacks/${cb.id}`, "DELETE", "Callback cancelled")}
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
          <CardFrameTitle>Latest results</CardFrameTitle>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>Closed</TableHead>
              <TableHead>Agent</TableHead>
              <TableHead>Contact</TableHead>
              <TableHead>Outcome</TableHead>
              <TableHead>Stage</TableHead>
              <TableHead className="min-w-56">Note</TableHead>
              <TableHead>CRM</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.recent.length === 0 && (
              <TableRow>
                <TableCell className="text-muted-foreground" colSpan={7}>
                  No call closed from the desk yet.
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
                    <span className="text-muted-foreground text-xs">Unchanged</span>
                  )}
                </TableCell>
                <TableCell className="whitespace-normal text-sm">
                  {r.note && <Bidi className="line-clamp-3" text={r.note} />}
                </TableCell>
                <TableCell>
                  {r.test ? (
                    <Badge variant="outline">Test, not sent</Badge>
                  ) : r.crm_error ? (
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <Button
                            onClick={() => run(`/api/operations/${r.id}/sync`, "POST", "Sent to the CRM again")}
                            size="xs"
                            variant="destructive-outline"
                          />
                        }
                      >
                        <RefreshCwIcon aria-hidden="true" />
                        Retry
                      </TooltipTrigger>
                      <TooltipPopup className="max-w-sm">{r.crm_error}</TooltipPopup>
                    </Tooltip>
                  ) : (
                    <Badge variant="success">Saved</Badge>
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
