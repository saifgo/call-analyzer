import {
  BarChart3Icon,
  BriefcaseIcon,
  CalendarClockIcon,
  CheckIcon,
  ChevronDownIcon,
  CircleAlertIcon,
  CopyIcon,
  ExternalLinkIcon,
  FlaskConicalIcon,
  HeadsetIcon,
  HistoryIcon,
  LightbulbIcon,
  ListChecksIcon,
  MailIcon,
  MapPinIcon,
  PhoneCallIcon,
  PhoneIcon,
  PhoneOffIcon,
  PlayIcon,
  PlusIcon,
  Undo2Icon,
  XIcon,
  ZapIcon,
} from "lucide-react";
import * as React from "react";
import { OperationsBoard } from "@/pages/operations-board";
import { OperationsCampaigns } from "@/pages/operations-campaigns";
import { OperationsInsights } from "@/pages/operations-insights";
import { OperationsKpis } from "@/pages/operations-kpis";
import { PageHeader } from "@/components/page-header";
import { QuickActions } from "@/components/quick-actions";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsiblePanel, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Dialog, DialogClose, DialogDescription, DialogFooter, DialogHeader, DialogPanel, DialogPopup, DialogTitle } from "@/components/ui/dialog";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Form } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from "@/components/ui/input-group";
import { Label } from "@/components/ui/label";
import { Popover, PopoverPopup, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTab } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { toastManager } from "@/components/ui/toast";
import { Toggle } from "@/components/ui/toggle";
import { api, useApi } from "@/lib/api";
import { Bidi, textDir } from "@/lib/bidi";
import { fmtDate, fmtDateTime, fmtDuration, fmtRelative, humanize, parseDate } from "@/lib/format";
import { useMe } from "@/lib/me";
import { outcomeVariant, STAGE_VARIANT, useNow } from "@/lib/operations";
import { href, navigate, type Route } from "@/lib/router";
import { type CallEnd, useSoftphone } from "@/lib/softphone";
import type { CrmLookup, OpAnswers, OpCall, OpCampaign, OpConfig, OpContext, OpDesk, OpOutcome, OpQuestion } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How often the desk checks in (also what keeps the agent's contact reserved for them). */
const POLL_MS = 15_000;
/** The number last used for a test call, offered again next time. */
const TEST_PHONE_KEY = "operations.testPhone";
/** Whether the power dialer is on (kept per browser). */
const POWER_DIAL_KEY = "operations.powerDial";
/** Power dialer: seconds before a served contact is dialed, and before an unanswered call is closed. */
const AUTO_DIAL_SECONDS = 3;
const AUTO_CLOSE_SECONDS = 5;

/** The campaign a call belongs to (the first one for calls from before campaigns). */
export function campaignOf(config: OpConfig, id: number | null | undefined): OpCampaign {
  return config.campaigns.find((c) => c.id === id) ?? config.campaigns.find((c) => c.active) ?? config.campaigns[0];
}

/** "YYYY-MM-DDTHH:MM" in local time, what <input type="datetime-local"> takes. */
function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function inHours(h: number): string {
  const d = new Date(Date.now() + h * 3_600_000);
  d.setSeconds(0, 0);
  return toLocalInput(d);
}

function todayAt(hour: number): string {
  const d = new Date();
  d.setHours(hour, 0, 0, 0);
  return toLocalInput(d);
}

function tomorrowAt(hour: number): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(hour, 0, 0, 0);
  return toLocalInput(d);
}

function secondsSince(value: string | null, now: number, until?: string | null): number {
  const start = parseDate(value);
  if (!start) return 0;
  const end = parseDate(until)?.getTime() ?? now;
  return Math.max(0, Math.round((end - start.getTime()) / 1000));
}

/** Counts down from `seconds` while `active` and then calls `onDone` once; the seconds left, or null when idle. */
function useCountdown(active: boolean, seconds: number, onDone: () => void): number | null {
  const [left, setLeft] = React.useState<number | null>(null);
  const done = React.useRef(onDone);
  React.useEffect(() => {
    done.current = onDone;
  });
  React.useEffect(() => {
    if (!active) {
      setLeft(null);
      return;
    }
    setLeft(seconds);
    const end = Date.now() + seconds * 1000;
    const t = window.setInterval(() => {
      const remaining = Math.ceil((end - Date.now()) / 1000);
      if (remaining <= 0) {
        window.clearInterval(t);
        setLeft(null);
        done.current();
      } else {
        setLeft(remaining);
      }
    }, 250);
    return () => window.clearInterval(t);
  }, [active, seconds]);
  return left;
}

function CopyNumber({ number }: { number: string }) {
  const [copied, setCopied] = React.useState(false);
  return (
    <Button
      aria-label={`Copy ${number}`}
      onClick={async () => {
        await navigator.clipboard.writeText(number.replace(/\s/g, ""));
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
      size="icon-xs"
      variant="ghost"
    >
      {copied ? <CheckIcon aria-hidden="true" /> : <CopyIcon aria-hidden="true" />}
    </Button>
  );
}

function InfoLine({ icon: Icon, children }: { icon: typeof MailIcon; children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-1.5">
      <Icon aria-hidden="true" className="size-3.5 shrink-0" />
      {children}
    </span>
  );
}

// --- The contact --------------------------------------------------------------------------------

function HistorySection({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-medium text-sm">
        {title}
        {count !== undefined && <span className="ms-1.5 font-normal text-muted-foreground tabular-nums">{count}</span>}
      </h3>
      {children}
    </div>
  );
}

/** Who the contact is, why they're being called, and (folded away) everything said to them before. */
function ContactDetails({ op, config, context }: { op: OpCall; config: OpConfig; context: OpContext | undefined }) {
  const lead = op.lead;
  const contact = lead?.contact;
  const outcomes = Object.fromEntries(config.outcomes.map((o) => [o.value, o]));
  const booked = context?.callback_from;
  const last = context?.history[0];
  const total = context ? context.history.length + context.notes.length + context.recorded_calls.length : 0;
  return (
    <Card>
      <CardPanel className="flex flex-col gap-4 p-4">
        {op.source === "callback" && (
          <Alert variant="warning">
            <CalendarClockIcon aria-hidden="true" />
            <AlertTitle>Callback planned for {fmtDateTime(op.due_at)}</AlertTitle>
            <AlertDescription>
              Booked by {op.scheduled_by_name ?? op.scheduled_by ?? "an agent"}
              {booked?.outcome && ` after "${outcomes[booked.outcome]?.label ?? humanize(booked.outcome)}"`}.
              {op.callback_note && <Bidi className="mt-1 text-foreground" text={op.callback_note} />}
            </AlertDescription>
          </Alert>
        )}

        <div className="flex flex-col gap-1 text-muted-foreground text-sm">
          {contact?.job_title && <InfoLine icon={BriefcaseIcon}>{contact.job_title}</InfoLine>}
          {(contact?.company || lead?.company) && <InfoLine icon={BriefcaseIcon}>{contact?.company || lead?.company}</InfoLine>}
          {contact?.city && <InfoLine icon={MapPinIcon}>{contact.city}</InfoLine>}
          {contact?.email && <InfoLine icon={MailIcon}>{contact.email}</InfoLine>}
          <span className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span>
              {lead?.created_at && `In the CRM since ${fmtDate(lead.created_at)}`}
              {lead?.owner && ` · Owner: ${lead.owner}`}
            </span>
            {lead?.url && (
              <a className="inline-flex items-center gap-1 hover:underline" href={lead.url} rel="noreferrer" target="_blank">
                Open in CRM
                <ExternalLinkIcon aria-hidden="true" className="size-3" />
              </a>
            )}
          </span>
        </div>

        <Separator />
        {!context ? (
          <Skeleton className="h-5 w-40" />
        ) : (
          <Collapsible>
            <CollapsibleTrigger className="flex w-full items-center justify-between gap-2 text-start text-sm">
              <span className="flex flex-col gap-0.5">
                <span className="font-medium">
                  History
                  <span className="ms-1.5 font-normal text-muted-foreground tabular-nums">{total}</span>
                </span>
                <span className="text-muted-foreground text-xs">
                  {last
                    ? `Last call: ${outcomes[last.outcome ?? ""]?.label ?? humanize(last.outcome)} · ${fmtDateTime(last.finished_at)}`
                    : "Never called from the desk before."}
                </span>
              </span>
              <ChevronDownIcon aria-hidden="true" className="size-4 shrink-0 transition-transform [[data-panel-open]>&]:rotate-180" />
            </CollapsibleTrigger>
            <CollapsiblePanel>
              <div className="flex flex-col gap-5 pt-4">
                <HistorySection count={context.history.length} title="Earlier calls from the desk">
                  {context.history.length ? (
                    <ul className="flex flex-col gap-2">
                      {context.history.map((h) => (
                        <li className="flex flex-col gap-1 rounded-lg border bg-muted/40 px-3 py-2 text-sm" key={h.id}>
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <Badge variant={outcomeVariant(outcomes[h.outcome ?? ""])}>
                              {outcomes[h.outcome ?? ""]?.label ?? humanize(h.outcome)}
                            </Badge>
                            <span className="text-muted-foreground text-xs">
                              {h.agent_name} · {fmtDateTime(h.finished_at)}
                            </span>
                          </div>
                          {h.note && <Bidi className="whitespace-pre-line" text={h.note} />}
                          {h.call_id && (
                            <a className="inline-flex items-center gap-1 text-muted-foreground text-xs hover:underline" href={href("calls", h.call_id)}>
                              <PlayIcon aria-hidden="true" className="size-3" />
                              Recording and AI feedback
                            </a>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-muted-foreground text-sm">First time this contact is called from the desk.</p>
                  )}
                </HistorySection>

                <HistorySection count={context.notes.length} title="CRM notes">
                  {context.notes_error && <p className="text-destructive-foreground text-sm">{context.notes_error}</p>}
                  {context.notes.length ? (
                    <ul className="flex max-h-72 flex-col gap-2 overflow-y-auto">
                      {context.notes.map((n) => (
                        <li className="flex flex-col gap-1 rounded-lg border px-3 py-2 text-sm" key={n.id}>
                          <div className="flex flex-wrap items-center justify-between gap-2 text-muted-foreground text-xs">
                            <span className="font-medium text-foreground">{n.title || "Note"}</span>
                            <span>
                              {n.author && `${n.author} · `}
                              {fmtDate(n.created_at)}
                            </span>
                          </div>
                          {n.text && <Bidi className="line-clamp-6 whitespace-pre-line" text={n.text.replaceAll("**", "")} />}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    !context.notes_error && <p className="text-muted-foreground text-sm">No notes in the CRM.</p>
                  )}
                </HistorySection>

                <HistorySection count={context.recorded_calls.length} title="Recorded calls with this number">
                  {context.recorded_calls.length ? (
                    <ul className="flex flex-col gap-2">
                      {context.recorded_calls.map((c) => (
                        <li className="flex flex-col gap-1 rounded-lg border px-3 py-2 text-sm" key={c.id}>
                          <div className="flex flex-wrap items-center justify-between gap-2 text-muted-foreground text-xs">
                            <span>
                              {fmtDateTime(c.date_call)} · {fmtDuration(c.duration)} · ext. {c.agent}
                            </span>
                            {c.outcome && <Badge variant="secondary">{humanize(c.outcome)}</Badge>}
                          </div>
                          {c.summary && <Bidi className="line-clamp-3" text={c.summary} />}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-muted-foreground text-sm">No recorded call with this number yet.</p>
                  )}
                </HistorySection>
              </div>
            </CollapsiblePanel>
          </Collapsible>
        )}
      </CardPanel>
    </Card>
  );
}

// --- Data gathering -----------------------------------------------------------------------------

function visible(q: OpQuestion, answers: OpAnswers): boolean {
  return Object.entries(q.show_if ?? {}).every(([key, values]) => values.includes(String(answers[key] ?? "")));
}

function Chip({ pressed, onPressedChange, children }: { pressed: boolean; onPressedChange: (on: boolean) => void; children: React.ReactNode }) {
  return (
    <Toggle
      className="data-pressed:border-primary data-pressed:bg-primary/8 data-pressed:text-foreground dark:data-pressed:bg-primary/16"
      onPressedChange={onPressedChange}
      pressed={pressed}
      size="sm"
      variant="outline"
    >
      {pressed && <CheckIcon aria-hidden="true" />}
      {children}
    </Toggle>
  );
}

function QuestionInput({ q, value, onChange }: { q: OpQuestion; value: OpAnswers[string] | undefined; onChange: (v: OpAnswers[string] | undefined) => void }) {
  switch (q.type) {
    case "select":
      return (
        <div className="flex flex-wrap gap-1.5">
          {(q.options ?? []).map(([v, label]) => (
            <Chip key={v} onPressedChange={(on) => onChange(on ? v : undefined)} pressed={value === v}>
              {label}
            </Chip>
          ))}
        </div>
      );
    case "multi": {
      const list = Array.isArray(value) ? value : [];
      return (
        <div className="flex flex-wrap gap-1.5">
          {(q.options ?? []).map(([v, label]) => (
            <Chip
              key={v}
              onPressedChange={(on) => {
                const next = on ? [...list, v] : list.filter((x) => x !== v);
                onChange(next.length ? next : undefined);
              }}
              pressed={list.includes(v)}
            >
              {label}
            </Chip>
          ))}
        </div>
      );
    }
    case "boolean":
      return (
        <div className="flex flex-wrap gap-1.5">
          <Chip onPressedChange={(on) => onChange(on ? true : undefined)} pressed={value === true}>
            Yes
          </Chip>
          <Chip onPressedChange={(on) => onChange(on ? false : undefined)} pressed={value === false}>
            No
          </Chip>
        </div>
      );
    case "number":
      return (
        <InputGroup className="max-w-56">
          <InputGroupInput
            aria-label={q.label}
            inputMode="decimal"
            min={0}
            onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)}
            step={q.step ?? "any"}
            type="number"
            value={value === undefined ? "" : String(value)}
          />
          {q.unit && (
            <InputGroupAddon align="inline-end">
              <InputGroupText>{q.unit}</InputGroupText>
            </InputGroupAddon>
          )}
        </InputGroup>
      );
    case "textarea":
      return (
        <Textarea
          aria-label={q.label}
          className="min-h-20"
          dir={textDir(String(value ?? ""))}
          onChange={(e) => onChange(e.target.value || undefined)}
          value={String(value ?? "")}
        />
      );
    default:
      return (
        <Input
          aria-label={q.label}
          className="max-w-md"
          dir={textDir(String(value ?? ""))}
          onChange={(e) => onChange(e.target.value || undefined)}
          type="text"
          value={String(value ?? "")}
        />
      );
  }
}

function Questionnaire({
  questions,
  answers,
  onChange,
  saveState,
}: {
  questions: OpQuestion[];
  answers: OpAnswers;
  onChange: (answers: OpAnswers) => void;
  saveState: "idle" | "saving" | "saved" | "error";
}) {
  const sections = [...new Set(questions.map((q) => q.section))];
  const filled = questions.filter((q) => visible(q, answers) && answers[q.key] !== undefined).length;
  const shown = questions.filter((q) => visible(q, answers)).length;
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col gap-1">
          <CardTitle>Questions</CardTitle>
          <CardDescription>
            {filled} of {shown} answered · skip what doesn't come up
          </CardDescription>
        </div>
        <span className="text-muted-foreground text-xs" role="status">
          {saveState === "saving" ? "Saving…" : saveState === "saved" ? "Saved" : saveState === "error" ? "Not saved" : ""}
        </span>
      </CardHeader>
      <CardPanel className="flex flex-col gap-6">
        {sections.map((section) => (
          <fieldset className="flex flex-col gap-4" key={section}>
            <legend className="mb-3 font-semibold text-muted-foreground text-xs uppercase tracking-wide">{section}</legend>
            {questions
              .filter((q) => q.section === section && visible(q, answers))
              .map((q) => (
                <div className="flex flex-col gap-2" key={q.key}>
                  <span className="font-medium text-sm">{q.label}</span>
                  <QuestionInput
                    onChange={(v) => {
                      const next = { ...answers };
                      if (v === undefined) delete next[q.key];
                      else next[q.key] = v;
                      onChange(next);
                    }}
                    q={q}
                    value={answers[q.key]}
                  />
                  {q.help && <p className="text-muted-foreground text-xs">{q.help}</p>}
                </div>
              ))}
          </fieldset>
        ))}
      </CardPanel>
    </Card>
  );
}

// --- What comes out of the call ----------------------------------------------------------------------

type WrapUp = {
  outcome: string;
  note: string;
  stage: string;
  stageTouched: boolean;
  callback: boolean;
  callbackAt: string;
  callbackNote: string;
  callbackMine: boolean;
};

const KEEP_STAGE = "__keep";
const EMPTY_WRAP: WrapUp = {
  callback: false,
  callbackAt: "",
  callbackMine: false,
  callbackNote: "",
  note: "",
  outcome: "",
  stage: KEEP_STAGE,
  stageTouched: false,
};
/** The note, appointment and outcome being written, kept per call so a reload doesn't lose them. */
const wrapKey = (opId: number) => `operations.wrap.${opId}`;

function loadWrap(opId: number): WrapUp {
  try {
    return { ...EMPTY_WRAP, ...JSON.parse(localStorage.getItem(wrapKey(opId)) ?? "{}") };
  } catch {
    return EMPTY_WRAP;
  }
}

/** Picking an outcome also suggests the contact's stage and, for a call to try again, an appointment: for an
 * unanswered call, the campaign's next try (none after its last try). */
function outcomePatch(w: WrapUp, o: OpOutcome, op: OpCall, context: OpContext | undefined): Partial<WrapUp> {
  const patch: Partial<WrapUp> = { outcome: o.value };
  if (!w.stageTouched) patch.stage = o.stage && o.stage !== op.lead?.stage ? o.stage : KEEP_STAGE;
  if (o.callback && !w.callback) {
    if (o.reached) {
      patch.callback = true;
      patch.callbackAt = w.callbackAt || tomorrowAt(10);
    } else if (!context?.last_try) {
      patch.callback = true;
      patch.callbackAt = w.callbackAt || (context?.retry_at ? context.retry_at.slice(0, 16) : inHours(2));
    }
  }
  return patch;
}

/** The usual appointment times, from now. */
function quickPicks(): [string, string][] {
  return [
    ["In 1 hour", inHours(1)],
    ["In 3 hours", inHours(3)],
    ...(new Date().getHours() < 17 ? ([["Today 18:00", todayAt(18)]] as [string, string][]) : []),
    ["Tomorrow 10:00", tomorrowAt(10)],
    ["Tomorrow 15:00", tomorrowAt(15)],
  ];
}

/** Booking the next call: one click for the usual times, available from the first second of the call. */
function AppointmentButton({ op, value, onChange }: { op: OpCall; value: WrapUp; onChange: (patch: Partial<WrapUp>) => void }) {
  const [open, setOpen] = React.useState(false);
  const [picks, setPicks] = React.useState<[string, string][]>([]);
  const booked = value.callback && !!value.callbackAt;
  const openChange = (next: boolean) => {
    if (next) setPicks(quickPicks());
    setOpen(next);
  };
  return (
    <Popover onOpenChange={openChange} open={open}>
      <PopoverTrigger
        render={
          <Button
            className={cn(booked && "border-warning/60 bg-warning/10 hover:bg-warning/16")}
            size="lg"
            variant="outline"
          />
        }
      >
        <CalendarClockIcon aria-hidden="true" />
        {booked ? fmtDateTime(value.callbackAt) : "Appointment"}
      </PopoverTrigger>
      <PopoverPopup align="end" className="w-80">
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-0.5">
            <span className="font-medium">{booked ? "Call back on" : "When should we call back?"}</span>
            <span className="text-muted-foreground text-xs">Saved with the call when you close it.</span>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {picks.map(([label, at]) => (
              <Button
                key={label}
                onClick={() => onChange({ callback: true, callbackAt: at })}
                size="sm"
                variant={booked && value.callbackAt === at ? "default" : "outline"}
              >
                {label}
              </Button>
            ))}
          </div>
          <Input
            aria-label="Appointment date and time"
            onChange={(e) => onChange({ callback: !!e.target.value, callbackAt: e.target.value })}
            type="datetime-local"
            value={booked ? value.callbackAt : ""}
          />
          {booked && (
            <>
              <Input
                aria-label="Appointment note"
                dir={textDir(value.callbackNote)}
                onChange={(e) => onChange({ callbackNote: e.target.value })}
                placeholder="Why (optional), e.g. owner is back after 17:00"
                type="text"
                value={value.callbackNote}
              />
              <Label className="flex items-center gap-2 font-normal text-sm">
                <Checkbox
                  checked={value.callbackMine || op.test}
                  disabled={op.test}
                  onCheckedChange={(on) => onChange({ callbackMine: !!on })}
                />
                Keep it for me
              </Label>
              <div className="flex justify-between gap-2">
                <Button onClick={() => onChange({ callback: false, callbackAt: "" })} size="sm" variant="ghost">
                  <XIcon aria-hidden="true" />
                  Remove
                </Button>
                <Button onClick={() => setOpen(false)} size="sm">
                  Done
                </Button>
              </div>
            </>
          )}
        </div>
      </PopoverPopup>
    </Popover>
  );
}

function OutcomeButtons({ title, outcomes, value, onPick }: { title: string; outcomes: OpOutcome[]; value: string; onPick: (o: OpOutcome) => void }) {
  if (!outcomes.length) return null;
  return (
    <div className="flex flex-col gap-2">
      <span className="font-medium text-muted-foreground text-xs uppercase tracking-wide">{title}</span>
      <div className="grid gap-2 sm:grid-cols-2">
        {outcomes.map((o) => (
          <Button
            className="justify-start"
            key={o.value}
            onClick={() => onPick(o)}
            variant={value === o.value ? "default" : "outline"}
          >
            {value === o.value && <CheckIcon aria-hidden="true" />}
            {o.label}
          </Button>
        ))}
      </div>
    </div>
  );
}

function WrapUpForm({
  config,
  campaign,
  context,
  op,
  value,
  onChange,
  onOutcome,
  onSubmit,
  saving,
}: {
  config: OpConfig;
  campaign: OpCampaign;
  context: OpContext | undefined;
  op: OpCall;
  value: WrapUp;
  onChange: (patch: Partial<WrapUp>) => void;
  onOutcome: (o: OpOutcome) => void;
  onSubmit: (pauseAfter: boolean) => void;
  saving: boolean;
}) {
  const [changingStage, setChangingStage] = React.useState(value.stageTouched);
  const stageLabel = (v: string | null | undefined) => config.stages.find((s) => s.value === v)?.label ?? humanize(v);
  const stageItems = [
    { label: `Keep at ${stageLabel(op.lead?.stage) || "its stage"}`, value: KEEP_STAGE },
    ...config.stages.filter((s) => s.value !== op.lead?.stage).map((s) => ({ label: s.label, value: s.value })),
  ];
  return (
    <Card className="border-primary/40">
      <CardHeader>
        <CardTitle>How did it go?</CardTitle>
        <CardDescription>Pick one, then save. Your note and appointment are saved with it.</CardDescription>
      </CardHeader>
      <CardPanel className="flex flex-col gap-5">
        <OutcomeButtons
          onPick={onOutcome}
          outcomes={campaign.outcomes.filter((o) => o.reached)}
          title="Spoke with them"
          value={value.outcome}
        />
        <OutcomeButtons
          onPick={onOutcome}
          outcomes={campaign.outcomes.filter((o) => !o.reached)}
          title="Didn't speak with them"
          value={value.outcome}
        />
        {context?.last_try && value.outcome && !campaign.outcomes.find((o) => o.value === value.outcome)?.reached && (
          <Alert variant="warning">
            <CircleAlertIcon aria-hidden="true" />
            <AlertDescription>
              Last try: {context.attempts + 1} unanswered calls in a row. No callback is booked
              {campaign.exhausted_stage && `, and the contact moves to ${config.stages.find((s) => s.value === campaign.exhausted_stage)?.label ?? humanize(campaign.exhausted_stage)}`}.
            </AlertDescription>
          </Alert>
        )}

        {value.outcome &&
          (changingStage ? (
            <Field>
              <FieldLabel>Move the contact to</FieldLabel>
              <Select
                items={stageItems}
                onValueChange={(v) => onChange({ stage: v as string, stageTouched: true })}
                value={value.stage}
              >
                <SelectTrigger className="max-w-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectPopup>
                  {stageItems.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectPopup>
              </Select>
            </Field>
          ) : (
            <p className="text-muted-foreground text-sm">
              {value.stage === KEEP_STAGE ? "The contact stays at " : "The contact moves to "}
              <span className="font-medium text-foreground">
                {stageLabel(value.stage === KEEP_STAGE ? op.lead?.stage : value.stage)}
              </span>
              .{" "}
              <button className="underline underline-offset-2 hover:text-foreground" onClick={() => setChangingStage(true)} type="button">
                Change
              </button>
            </p>
          ))}

        <p className="flex items-center gap-1.5 text-muted-foreground text-sm">
          <CalendarClockIcon aria-hidden="true" className="size-4" />
          {value.callback && value.callbackAt ? (
            <span>
              Appointment: <span className="font-medium text-foreground">{fmtDateTime(value.callbackAt)}</span>
            </span>
          ) : (
            "No appointment booked."
          )}
        </p>

        <div className="flex flex-wrap justify-end gap-2">
          <Button disabled={!value.outcome || saving} onClick={() => onSubmit(true)} variant="outline">
            Save and pause
          </Button>
          <Button disabled={!value.outcome} loading={saving} onClick={() => onSubmit(false)} size="lg">
            Save and next contact
          </Button>
        </div>
      </CardPanel>
    </Card>
  );
}

// --- The contact being served ------------------------------------------------------------------------

/** The outcome a call that never connected suggests, from the softphone's end cause. */
function unansweredOutcome(cause: string): string {
  if (cause === "Busy" || cause === "Rejected") return "busy";
  if (cause === "Unavailable" || cause === "Not Found") return "unreachable";
  return "no_answer";
}

function ServingDesk({
  op: initial,
  config,
  powerDial,
  onFinished,
}: {
  op: OpCall;
  config: OpConfig;
  powerDial: boolean;
  onFinished: (pauseAfter: boolean) => void;
}) {
  const sp = useSoftphone();
  const [op, setOp] = React.useState(initial);
  const campaign = campaignOf(config, op.campaign_id);
  const { data: context } = useApi<OpContext>(`/api/operations/${op.id}/context`);
  // The softphone's call-ended handler outlives renders: it reads these through refs.
  const contextRef = React.useRef(context);
  const powerDialRef = React.useRef(powerDial);
  React.useEffect(() => {
    contextRef.current = context;
    powerDialRef.current = powerDial;
  });
  const [answers, setAnswers] = React.useState<OpAnswers>(op.answers ?? {});
  const [dirty, setDirty] = React.useState(false);
  const [saveState, setSaveState] = React.useState<"idle" | "saving" | "saved" | "error">("idle");
  const [busy, setBusy] = React.useState(false);
  const [wrap, setWrap] = React.useState<WrapUp>(() => loadWrap(initial.id));
  /** Power dialer: the unanswered call closes itself unless the agent touches the form. */
  const [autoClose, setAutoClose] = React.useState(false);
  const patchWrap = (patch: Partial<WrapUp>) => {
    setAutoClose(false);
    setWrap((w) => ({ ...w, ...patch }));
  };

  React.useEffect(() => {
    localStorage.setItem(wrapKey(op.id), JSON.stringify(wrap));
  }, [op.id, wrap]);

  // Start from what an earlier call found out, unless this one already has answers.
  const prefilled = React.useRef(false);
  React.useEffect(() => {
    if (!context || prefilled.current) return;
    prefilled.current = true;
    if (!Object.keys(op.answers ?? {}).length && Object.keys(context.previous_answers).length) {
      setAnswers(context.previous_answers);
      setDirty(true);
    }
  }, [context, op.answers]);

  // Save answers a moment after the agent stops typing.
  React.useEffect(() => {
    if (!dirty) return;
    const t = window.setTimeout(async () => {
      setSaveState("saving");
      try {
        await api(`/api/operations/${op.id}/answers`, { body: { answers }, method: "PUT" });
        setSaveState("saved");
        setDirty(false);
      } catch {
        setSaveState("error");
      }
    }, 800);
    return () => window.clearTimeout(t);
  }, [answers, dirty, op.id]);

  const onCall = op.status === "in_call" && !op.call_ended_at;
  const wrapping = !!op.call_ended_at;
  const now = useNow(onCall || wrapping);

  // Once the call ends, bring the closing step (at the bottom) into view.
  const wrapRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (wrapping) wrapRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [wrapping]);

  // One at a time, so a call that fails right away can't have its "end" overtaken by its "start".
  const queue = React.useRef(Promise.resolve());
  const act = (action: "call" | "end", body?: Record<string, unknown>) => {
    queue.current = queue.current.then(async () => {
      setBusy(true);
      try {
        setOp(await api<OpCall>(`/api/operations/${op.id}/${action}`, { body, method: "POST" }));
      } catch (err) {
        toastManager.add({ description: (err as Error).message, title: "Couldn't update the call", type: "error" });
      } finally {
        setBusy(false);
      }
    });
  };

  const [dialed, setDialed] = React.useState(false);
  const dial = (phone: string) => {
    setDialed(true);
    const placed = sp.call(phone, {
      onEnded: (end: CallEnd) => {
        if (!end.answered) {
          const o = campaign.outcomes.find((x) => x.value === unansweredOutcome(end.cause));
          if (o) {
            setWrap((w) => (w.outcome ? w : { ...w, ...outcomePatch(w, o, op, contextRef.current) }));
            if (powerDialRef.current) setAutoClose(true);
          }
        }
        act("end");
      },
    });
    if (placed) act("call", { phone });
    else toastManager.add({ description: "Dial it on your phone, then press Start call.", title: "The browser phone can't call right now", type: "warning" });
  };

  const giveBack = async () => {
    setBusy(true);
    try {
      await api(`/api/operations/${op.id}/give-back`, { method: "POST" });
      localStorage.removeItem(wrapKey(op.id));
      toastManager.add({ title: "Contact given back to the queue", type: "success" });
      onFinished(false);
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't give the contact back", type: "error" });
      setBusy(false);
    }
  };

  const endCall = () => {
    if (sp.active) sp.hangup(); // its onEnded closes the call here
    else act("end");
  };

  const submit = async (pauseAfter: boolean) => {
    setBusy(true);
    try {
      const done = await api<OpCall>(`/api/operations/${op.id}/finish`, {
        body: {
          answers,
          callback_at: wrap.callback && wrap.callbackAt ? wrap.callbackAt : null,
          callback_mine: wrap.callbackMine,
          callback_note: wrap.callbackNote,
          note: wrap.note,
          outcome: wrap.outcome,
          stage: wrap.stage === KEEP_STAGE ? null : wrap.stage,
        },
        method: "POST",
      });
      localStorage.removeItem(wrapKey(op.id));
      if (done.attempts_exhausted) {
        toastManager.add({
          description: "That was the campaign's last try: no callback was booked.",
          title: "Contact never answered",
          type: "info",
        });
      }
      if (done.test) {
        toastManager.add({ title: "Test call saved (nothing was sent to the CRM)", type: "success" });
      } else if (done.crm_error) {
        toastManager.add({ description: done.crm_error, title: "Call saved, but the CRM wasn't fully updated", type: "warning" });
      } else {
        toastManager.add({ title: "Call saved and written to the CRM", type: "success" });
      }
      onFinished(pauseAfter);
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't save the call", type: "error" });
      setBusy(false);
    }
  };

  const lead = op.lead;
  const phones = lead?.contact?.phones ?? [];
  const stage = config.stages.find((s) => s.value === lead?.stage);

  // Power dialer: dial a served contact after a short countdown, and close an unanswered call by itself.
  const [dialCancelled, setDialCancelled] = React.useState(false);
  const autoDial = powerDial && op.status === "assigned" && sp.ready && phones.length > 0 && !dialed && !dialCancelled && !busy;
  const dialIn = useCountdown(autoDial, AUTO_DIAL_SECONDS, () => dial(phones[0]));
  const closing = autoClose && wrapping && !!wrap.outcome && !busy;
  const closeIn = useCountdown(closing, AUTO_CLOSE_SECONDS, () => submit(false));
  const ringing = onCall && sp.active?.direction === "outgoing" && sp.active.state === "calling";
  const browserPhone = sp.ready;

  return (
    <div className="flex flex-col gap-4">
      {op.test && (
        <Alert variant="info">
          <FlaskConicalIcon aria-hidden="true" />
          <AlertDescription>Test call: nothing is written to the CRM and it doesn't count in your figures.</AlertDescription>
        </Alert>
      )}
      {dialIn !== null && (
        <Alert variant="info">
          <ZapIcon aria-hidden="true" />
          <AlertTitle>Calling {lead?.contact?.name ?? phones[0]} in {dialIn}s</AlertTitle>
          <AlertDescription className="flex flex-wrap gap-2">
            <Button onClick={() => dial(phones[0])} size="sm">
              <PhoneCallIcon aria-hidden="true" />
              Call now
            </Button>
            <Button onClick={() => setDialCancelled(true)} size="sm" variant="outline">
              Wait
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {closeIn !== null && (
        <Alert variant="info">
          <ZapIcon aria-hidden="true" />
          <AlertTitle>
            No answer: saving as "{campaign.outcomes.find((o) => o.value === wrap.outcome)?.label}" and moving on in {closeIn}s
          </AlertTitle>
          <AlertDescription className="flex flex-wrap gap-2">
            <Button onClick={() => submit(false)} size="sm">
              Save now
            </Button>
            <Button onClick={() => setAutoClose(false)} size="sm" variant="outline">
              Keep it open
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {/* Who, the number, where the call is at, and what to do next: always in view. */}
      <Card className={cn("sticky top-16 z-[5] shadow-md", onCall && "border-success/50")}>
        <CardPanel className="flex flex-wrap items-center gap-x-6 gap-y-3 p-4">
          <div className="flex min-w-48 flex-1 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-1.5">
              {op.source === "callback" && (
                <Badge variant="warning">
                  <CalendarClockIcon aria-hidden="true" />
                  Callback
                </Badge>
              )}
              {op.source === "direct" && <Badge variant="info">Sales call</Badge>}
              {config.campaigns.filter((c) => c.active).length > 1 && <Badge variant="outline">{campaign.name}</Badge>}
              {context && context.attempts > 0 && (
                <Badge variant={context.last_try ? "error" : "secondary"}>
                  {context.last_try
                    ? `Last try (${context.attempts} unanswered)`
                    : `Try ${context.attempts + 1}${context.max_attempts ? ` of ${context.max_attempts}` : ""}`}
                </Badge>
              )}
              {lead?.stage && <Badge variant={STAGE_VARIANT[lead.stage] ?? "secondary"}>{stage?.label ?? humanize(lead.stage)}</Badge>}
            </div>
            <Bidi as="div" className="font-heading font-semibold text-xl" text={lead?.contact?.name ?? "No point of contact"} />
            <Bidi className="text-muted-foreground text-sm" text={lead?.name} />
          </div>

          <div className="flex flex-col gap-1">
            {phones.map((phone) => (
              <span className="flex items-center gap-1" key={phone}>
                <span className="font-semibold text-lg tabular-nums" dir="ltr">
                  {phone}
                </span>
                <CopyNumber number={phone} />
                {op.status === "assigned" && browserPhone && phones.length > 1 && (
                  <Button aria-label={`Call ${phone}`} disabled={busy} onClick={() => dial(phone)} size="icon-xs" variant="ghost">
                    <PhoneIcon aria-hidden="true" />
                  </Button>
                )}
              </span>
            ))}
          </div>

          <div className="flex items-center gap-2.5">
            <span
              aria-hidden="true"
              className={cn("size-2.5 rounded-full", onCall ? "animate-pulse bg-success" : wrapping ? "bg-muted-foreground" : "bg-warning")}
            />
            <span className="flex flex-col text-sm">
              <span className="font-medium">
                {op.status === "assigned" ? "Not called yet" : ringing ? "Ringing…" : onCall ? "On the call" : "Call ended"}
              </span>
              <span className="text-muted-foreground tabular-nums">
                {op.status === "assigned"
                  ? browserPhone
                    ? "Press Call to dial"
                    : "Dial on your phone, then Start call"
                  : fmtDuration(secondsSince(op.call_started_at, now, op.call_ended_at))}
              </span>
            </span>
          </div>

          <div className="ms-auto flex flex-wrap items-center gap-2">
            {op.status === "assigned" && (
              <Button disabled={busy} onClick={giveBack} size="lg" variant="ghost">
                <Undo2Icon aria-hidden="true" />
                Give back
              </Button>
            )}
            <AppointmentButton onChange={patchWrap} op={op} value={wrap} />
            {op.status === "assigned" &&
              (browserPhone ? (
                <Button disabled={busy || !phones.length} onClick={() => dial(phones[0])} size="lg">
                  <PhoneCallIcon aria-hidden="true" />
                  Call
                </Button>
              ) : (
                <Button loading={busy} onClick={() => act("call")} size="lg">
                  <PhoneCallIcon aria-hidden="true" />
                  Start call
                </Button>
              ))}
            {onCall && (
              <Button loading={busy} onClick={endCall} size="lg" variant="destructive">
                <PhoneOffIcon aria-hidden="true" />
                End call
              </Button>
            )}
          </div>
        </CardPanel>
      </Card>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="flex flex-col gap-4">
          <Questionnaire
            answers={answers}
            onChange={(next) => {
              setAutoClose(false);
              setAnswers(next);
              setDirty(true);
            }}
            questions={campaign.questions}
            saveState={saveState}
          />
          {wrapping && (
            <div className="scroll-mb-6" ref={wrapRef}>
              <WrapUpForm
                campaign={campaign}
                config={config}
                context={context}
                onChange={patchWrap}
                onOutcome={(o) => {
                  setAutoClose(false);
                  setWrap((w) => ({ ...w, ...outcomePatch(w, o, op, context) }));
                }}
                onSubmit={submit}
                op={op}
                saving={busy}
                value={wrap}
              />
            </div>
          )}
        </div>
        <div className="flex flex-col gap-4 lg:sticky lg:top-48">
          <QuickActions op={op} />
          <Card>
            <CardPanel className="flex flex-col gap-2 p-4">
              <Label className="font-medium" htmlFor="op-note">
                Notes
              </Label>
              <Textarea
                className="min-h-28"
                dir={textDir(wrap.note)}
                id="op-note"
                onChange={(e) => patchWrap({ note: e.target.value })}
                placeholder="What was said, what was promised…"
                value={wrap.note}
              />
            </CardPanel>
          </Card>
          <ContactDetails config={config} context={context} op={op} />
        </div>
      </div>
    </div>
  );
}


// --- A sales call outside the queue -------------------------------------------------------------------

/** Enough digits to look a number up in the CRM (Tunisian numbers are 8). */
const searchable = (phone: string) => phone.replace(/\D/g, "").length >= 8;

function NewCallDialog({
  open,
  onOpenChange,
  onStarted,
  config,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStarted: (op: OpCall) => void;
  config: OpConfig;
}) {
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogPopup className="sm:max-w-lg">
        {/* Mounted on every open, so the search starts fresh. */}
        <NewCallForm config={config} onDone={() => onOpenChange(false)} onStarted={onStarted} />
      </DialogPopup>
    </Dialog>
  );
}

function NewCallForm({ config, onStarted, onDone }: { config: OpConfig; onStarted: (op: OpCall) => void; onDone: () => void }) {
  const [phone, setPhone] = React.useState("");
  const [result, setResult] = React.useState<CrmLookup | null>(null);
  const [searching, setSearching] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  /** What is being sent: an opportunity id, a person id, or "new". */
  const [busy, setBusy] = React.useState<string | null>(null);
  const [name, setName] = React.useState("");
  const [city, setCity] = React.useState("");
  const [email, setEmail] = React.useState("");

  // Look the number up as soon as it's complete.
  React.useEffect(() => {
    if (!searchable(phone)) return;
    let cancelled = false;
    const t = window.setTimeout(async () => {
      setSearching(true);
      try {
        const found = await api<CrmLookup>(`/api/operations/lookup?phone=${encodeURIComponent(phone)}`);
        if (!cancelled) {
          setResult(found);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setSearching(false);
      }
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [phone]);

  const run = async (key: string, request: () => Promise<{ current: OpCall | null }>, queued?: string) => {
    setBusy(key);
    setError(null);
    try {
      const res = await request();
      if (res.current) onStarted(res.current);
      else {
        toastManager.add({ title: queued ?? "Added to the queue", type: "success" });
        onDone();
      }
    } catch (err) {
      setError((err as Error).message);
      setBusy(null);
    }
  };

  const callOpportunity = (id: string) =>
    run(id, () => api("/api/operations/direct", { body: { opportunity_id: id }, method: "POST" }));
  const addLead = (key: string, body: Record<string, unknown>, call: boolean) =>
    run(
      `${key}:${call}`,
      () => api("/api/operations/leads", { body: { ...body, call }, method: "POST" }),
      "Added to the CRM and to the queue",
    );

  const stageLabel = (v: string | null) => config.stages.find((s) => s.value === v)?.label ?? humanize(v);
  const matches = searchable(phone) && result?.number === phone ? result.people : null;

  return (
    <>
      <DialogHeader>
        <DialogTitle>New sales call</DialogTitle>
        <DialogDescription>Type the number: we look for the contact in the CRM, or you add them.</DialogDescription>
      </DialogHeader>
      <DialogPanel className="flex flex-col gap-4">
        <InputGroup>
          <InputGroupAddon>
            <PhoneIcon aria-hidden="true" />
          </InputGroupAddon>
          <InputGroupInput
            aria-label="Phone number"
            autoFocus
            dir="ltr"
            maxLength={40}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="e.g. 20 123 456"
            type="tel"
            value={phone}
          />
          {searching && (
            <InputGroupAddon align="inline-end">
              <Spinner />
            </InputGroupAddon>
          )}
        </InputGroup>

        {error && (
          <Alert variant="error">
            <CircleAlertIcon aria-hidden="true" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {matches && matches.length > 0 && (
          <div className="flex flex-col gap-3">
            <span className="flex items-center gap-1.5 font-medium text-sm">
              <CheckIcon aria-hidden="true" className="size-4 text-success" />
              Found in the CRM
            </span>
            {matches.map((person) => (
              <div className="flex flex-col gap-3 rounded-lg border p-3" key={person.id}>
                <div className="flex flex-col gap-0.5">
                  <Bidi as="span" className="font-semibold" text={person.name} />
                  <span className="text-muted-foreground text-xs">
                    <span dir="ltr">{person.phones.join(" · ")}</span>
                    {person.city && ` · ${person.city}`}
                    {person.company && ` · ${person.company}`}
                  </span>
                </div>
                {person.opportunities.length ? (
                  <ul className="flex flex-col gap-1.5">
                    {person.opportunities.map((o) => (
                      <li className="flex items-center justify-between gap-2 text-sm" key={o.id}>
                        <span className="flex min-w-0 items-center gap-2">
                          {o.stage && <Badge variant={STAGE_VARIANT[o.stage] ?? "secondary"}>{stageLabel(o.stage)}</Badge>}
                          <Bidi as="span" className="truncate text-muted-foreground" text={o.name} />
                        </span>
                        <Button disabled={!!busy} loading={busy === o.id} onClick={() => callOpportunity(o.id)} size="sm">
                          <PhoneCallIcon aria-hidden="true" />
                          Call
                        </Button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    <Button
                      disabled={!!busy}
                      loading={busy === `${person.id}:false`}
                      onClick={() => addLead(person.id, { name: person.name, person_id: person.id }, false)}
                      size="sm"
                      variant="outline"
                    >
                      Add to the queue
                    </Button>
                    <Button
                      disabled={!!busy}
                      loading={busy === `${person.id}:true`}
                      onClick={() => addLead(person.id, { name: person.name, person_id: person.id }, true)}
                      size="sm"
                    >
                      <PhoneCallIcon aria-hidden="true" />
                      Call
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {matches && matches.length === 0 && (
          <Form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              addLead("new", { city, email, name, phone }, true);
            }}
          >
            <p className="text-muted-foreground text-sm">Not in the CRM yet. Add them to call them now or later:</p>
            <Field>
              <FieldLabel>Name</FieldLabel>
              <Input
                dir={textDir(name)}
                maxLength={100}
                onChange={(e) => setName(e.target.value)}
                placeholder="Full name or shop name"
                required
                type="text"
                value={name}
              />
            </Field>
            <Field>
              <FieldLabel>City / area</FieldLabel>
              <Input dir={textDir(city)} maxLength={200} onChange={(e) => setCity(e.target.value)} type="text" value={city} />
            </Field>
            <Field>
              <FieldLabel>Email (optional)</FieldLabel>
              <Input dir="ltr" maxLength={200} onChange={(e) => setEmail(e.target.value)} type="email" value={email} />
            </Field>
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                disabled={!!busy || !name.trim()}
                loading={busy === "new:false"}
                onClick={() => addLead("new", { city, email, name, phone }, false)}
                type="button"
                variant="outline"
              >
                Add to the queue
              </Button>
              <Button disabled={!!busy || !name.trim()} loading={busy === "new:true"} type="submit">
                <PhoneCallIcon aria-hidden="true" />
                Add and call
              </Button>
            </div>
          </Form>
        )}
      </DialogPanel>
    </>
  );
}

// --- The desk ---------------------------------------------------------------------------------------

function MyCallbacks({ callbacks, onChange }: { callbacks: OpCall[]; onChange: () => void }) {
  const now = useNow(callbacks.length > 0, 30_000);
  if (!callbacks.length) return null;
  const cancel = async (cb: OpCall) => {
    try {
      await api(`/api/operations/callbacks/${cb.id}`, { method: "DELETE" });
      toastManager.add({ title: "Callback cancelled", type: "success" });
      onChange();
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't cancel", type: "error" });
    }
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CalendarClockIcon aria-hidden="true" className="size-4" />
          My callbacks
        </CardTitle>
        <CardDescription>Served to you (or to the first free agent) when they're due.</CardDescription>
      </CardHeader>
      <CardPanel>
        <ul className="flex flex-col divide-y">
          {callbacks.map((cb) => {
            const due = (parseDate(cb.due_at)?.getTime() ?? 0) <= now;
            return (
              <li className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm" key={cb.id}>
                <div className="flex min-w-0 flex-col">
                  <Bidi as="span" className="font-medium" text={cb.lead?.contact?.name ?? cb.lead?.name ?? "Contact"} />
                  <span className="text-muted-foreground text-xs">
                    {cb.test && "Test · "}
                    {cb.assign_to ? "Kept for you" : "Anyone"}
                    {cb.callback_note && ` · ${cb.callback_note}`}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={due ? "warning" : "secondary"}>
                    {due ? "Due" : fmtRelative(cb.due_at)} · {fmtDateTime(cb.due_at)}
                  </Badge>
                  <Button aria-label="Cancel callback" onClick={() => cancel(cb)} size="icon-xs" variant="ghost">
                    <XIcon aria-hidden="true" />
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      </CardPanel>
    </Card>
  );
}

function TestCallDialog({ open, onOpenChange, onStarted }: { open: boolean; onOpenChange: (open: boolean) => void; onStarted: (op: OpCall) => void }) {
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogPopup className="sm:max-w-md">
        {/* Mounted on every open, so the form starts fresh. */}
        <TestCallForm onStarted={onStarted} />
      </DialogPopup>
    </Dialog>
  );
}

function TestCallForm({ onStarted }: { onStarted: (op: OpCall) => void }) {
  const [phone, setPhone] = React.useState(() => localStorage.getItem(TEST_PHONE_KEY) ?? "");
  const [name, setName] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const res = await api<{ current: OpCall }>("/api/operations/test", { body: { name, phone }, method: "POST" });
      localStorage.setItem(TEST_PHONE_KEY, phone);
      onStarted(res.current);
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <Form className="contents" onSubmit={submit}>
      <DialogHeader>
        <DialogTitle>Test call</DialogTitle>
        <DialogDescription>
          Try the desk on a number of your own. You get a made-up contact and go through the call as usual, but nothing is
          written to the CRM. You're paused, so no real contact comes after it.
        </DialogDescription>
      </DialogHeader>
      <DialogPanel className="flex flex-col gap-4">
        {error && (
          <Alert variant="error">
            <CircleAlertIcon aria-hidden="true" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <Field>
          <FieldLabel>Number to call</FieldLabel>
          <Input
            autoFocus
            dir="ltr"
            maxLength={40}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="e.g. +216 20 123 456"
            required
            type="tel"
            value={phone}
          />
          <FieldDescription>Your own mobile, or a colleague's who knows it's a test.</FieldDescription>
        </Field>
        <Field>
          <FieldLabel>Contact name</FieldLabel>
          <Input
            dir={textDir(name)}
            maxLength={100}
            onChange={(e) => setName(e.target.value)}
            placeholder="Test contact"
            type="text"
            value={name}
          />
        </Field>
      </DialogPanel>
      <DialogFooter>
        <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
        <Button loading={saving} type="submit">
          <FlaskConicalIcon aria-hidden="true" />
          Start test call
        </Button>
      </DialogFooter>
    </Form>
  );
}

function DeskBar({
  desk,
  config,
  onReady,
  onCampaign,
  onNewCall,
  onTest,
  powerDial,
  onPowerDial,
  toggling,
}: {
  desk: OpDesk;
  config: OpConfig;
  onReady: (ready: boolean) => void;
  onCampaign: (id: number) => void;
  onNewCall: () => void;
  onTest: () => void;
  powerDial: boolean;
  onPowerDial: (on: boolean) => void;
  toggling: boolean;
}) {
  const sp = useSoftphone();
  const q = desk.queue;
  const active = config.campaigns.filter((c) => c.active);
  const items = active.map((c) => ({ label: c.name, value: String(c.id) }));
  return (
    <Card>
      <CardPanel className="flex flex-wrap items-center justify-between gap-4 p-4">
        <Label className="flex items-center gap-3 font-medium">
          <Switch checked={desk.ready} disabled={toggling} onCheckedChange={onReady} />
          <span className="flex flex-col">
            {desk.ready ? "Taking calls" : "Paused"}
            <span className="font-normal text-muted-foreground text-xs">
              {desk.ready ? "You get the next contact as soon as you're free." : "Turn on to get contacts from the queue."}
            </span>
          </span>
        </Label>
        {active.length > 1 && (
          <Field className="w-auto min-w-48">
            <FieldLabel className="text-muted-foreground text-xs">Campaign</FieldLabel>
            <Select
              disabled={desk.current?.status === "in_call"}
              items={items}
              onValueChange={(v) => onCampaign(Number(v))}
              value={String(desk.campaign_id)}
            >
              <SelectTrigger size="sm">
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
          </Field>
        )}
        <Label className="flex items-center gap-3 font-medium">
          <Switch checked={powerDial} disabled={!powerDial && sp.status !== "registered"} onCheckedChange={onPowerDial} />
          <span className="flex flex-col">
            <span className="flex items-center gap-1">
              <ZapIcon aria-hidden="true" className="size-3.5" />
              Power dial
            </span>
            <span className="font-normal text-muted-foreground text-xs">
              {sp.status === "registered" ? "Dial each contact by itself" : "Needs the browser phone"}
            </span>
          </span>
        </Label>
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <div className="flex flex-col">
            <dt className="text-muted-foreground text-xs">Calls today</dt>
            <dd className="font-semibold tabular-nums">{desk.today.done}</dd>
          </div>
          <div className="flex flex-col">
            <dt className="text-muted-foreground text-xs">Reached</dt>
            <dd className="font-semibold tabular-nums">{desk.today.reached}</dd>
          </div>
          <div className="flex flex-col">
            <dt className="text-muted-foreground text-xs">Wins</dt>
            <dd className="font-semibold tabular-nums">{desk.today.success}</dd>
          </div>
          <div className="flex flex-col">
            <dt className="text-muted-foreground text-xs">Talk time</dt>
            <dd className="font-semibold tabular-nums">{fmtDuration(desk.today.talk_seconds)}</dd>
          </div>
          <div className="flex flex-col">
            <dt className="text-muted-foreground text-xs">In the queue</dt>
            <dd className="font-semibold tabular-nums">
              {q.waiting ?? "–"}
              {q.due_callbacks > 0 && <span className="ms-1 font-normal text-warning-foreground">+{q.due_callbacks} due</span>}
            </dd>
          </div>
        </dl>
        <div className="flex flex-wrap gap-2">
          <Button disabled={!!desk.current} onClick={onTest} size="sm" variant="ghost">
            <FlaskConicalIcon aria-hidden="true" />
            Test call
          </Button>
          <Button disabled={desk.current?.status === "in_call"} onClick={onNewCall} size="sm">
            <PlusIcon aria-hidden="true" />
            New call
          </Button>
        </div>
      </CardPanel>
    </Card>
  );
}

function Desk() {
  const { data: config, error: configError } = useApi<OpConfig>("/api/operations/config");
  const [desk, setDesk] = React.useState<OpDesk>();
  const [reason, setReason] = React.useState<string | null>(null);
  const [toggling, setToggling] = React.useState(false);
  const [testOpen, setTestOpen] = React.useState(false);
  const [newOpen, setNewOpen] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [powerDial, setPowerDial] = React.useState(() => localStorage.getItem(POWER_DIAL_KEY) === "1");
  const changePowerDial = (on: boolean) => {
    localStorage.setItem(POWER_DIAL_KEY, on ? "1" : "0");
    setPowerDial(on);
  };

  const load = React.useCallback(async () => {
    try {
      setDesk(await api<OpDesk>("/api/operations/desk"));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  React.useEffect(() => {
    load();
    const t = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(t);
  }, [load]);

  // Free and ready: ask for the next contact (again after every check-in while the queue is empty).
  React.useEffect(() => {
    if (!desk?.ready || desk.current) return;
    let cancelled = false;
    api<{ current: OpCall | null; reason: string | null }>("/api/operations/next", { method: "POST" })
      .then((r) => {
        if (cancelled) return;
        setReason(r.reason);
        if (r.current) setDesk((d) => (d ? { ...d, current: r.current } : d));
      })
      .catch((err: Error) => !cancelled && setReason(err.message));
    return () => {
      cancelled = true;
    };
  }, [desk]);

  const setReady = async (ready: boolean) => {
    setToggling(true);
    try {
      await api("/api/operations/ready", { body: { ready }, method: "POST" });
      await load();
    } finally {
      setToggling(false);
    }
  };

  const setCampaign = async (campaignId: number) => {
    try {
      await api("/api/operations/campaign", { body: { campaign_id: campaignId }, method: "POST" });
      setReason(null);
      await load();
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't change the campaign", type: "error" });
    }
  };

  const directStarted = (op: OpCall) => {
    setNewOpen(false);
    setReason(null);
    setDesk((d) => (d ? { ...d, current: op } : d));
  };

  const testStarted = (op: OpCall) => {
    setTestOpen(false);
    setReason(null);
    setDesk((d) => (d ? { ...d, current: op, ready: false } : d));
  };

  const finished = async (pauseAfter: boolean) => {
    if (pauseAfter) await api("/api/operations/ready", { body: { ready: false }, method: "POST" });
    setDesk((d) => (d ? { ...d, current: null } : d));
    await load();
  };

  if (configError || error) {
    return (
      <Alert variant="error">
        <CircleAlertIcon aria-hidden="true" />
        <AlertTitle>Couldn't load the call desk</AlertTitle>
        <AlertDescription>{configError?.message ?? error}</AlertDescription>
      </Alert>
    );
  }
  if (!config || !desk) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-20 w-full rounded-2xl" />
        <Skeleton className="h-96 w-full rounded-2xl" />
      </div>
    );
  }

  return (
    <>
      <DeskBar
        config={config}
        desk={desk}
        onCampaign={setCampaign}
        onNewCall={() => setNewOpen(true)}
        onPowerDial={changePowerDial}
        onReady={setReady}
        onTest={() => setTestOpen(true)}
        powerDial={powerDial}
        toggling={toggling}
      />
      <TestCallDialog onOpenChange={setTestOpen} onStarted={testStarted} open={testOpen} />
      <NewCallDialog config={config} onOpenChange={setNewOpen} onStarted={directStarted} open={newOpen} />
      {desk.current ? (
        <ServingDesk config={config} key={desk.current.id} onFinished={finished} op={desk.current} powerDial={powerDial} />
      ) : (
        <Empty className="rounded-xl border md:py-16">
          <EmptyHeader>
            <EmptyMedia variant="icon">{desk.ready && !reason ? <Spinner /> : <HeadsetIcon />}</EmptyMedia>
            <EmptyTitle>
              {!desk.ready ? "You're paused" : reason ? "Can't get a contact" : desk.queue.waiting === 0 ? "The queue is empty" : "Getting your next contact…"}
            </EmptyTitle>
            <EmptyDescription>
              {!desk.ready
                ? "Start taking calls and you'll be given the oldest contact nobody is calling yet."
                : reason
                  ? reason
                  : desk.queue.waiting === 0
                    ? "Every contact in this campaign's queue has been handled. You'll get the next one, or a callback, as soon as it comes in."
                    : "One moment."}
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent className="flex-row flex-wrap justify-center">
            {!desk.ready && (
              <Button loading={toggling} onClick={() => setReady(true)}>
                <HeadsetIcon aria-hidden="true" />
                Start taking calls
              </Button>
            )}
            <Button onClick={() => setNewOpen(true)} variant="outline">
              <PlusIcon aria-hidden="true" />
              New sales call
            </Button>
          </EmptyContent>
        </Empty>
      )}
      <MyCallbacks callbacks={desk.callbacks} onChange={load} />
    </>
  );
}

/** Operations: agents work the CRM's New contacts one by one; admins also get the team board. */
const TABS = {
  campaigns: {
    admin: true,
    description: "What each campaign's queue is made of, what agents ask, how calls can end, and the calling rules.",
    icon: ListChecksIcon,
    label: "Campaigns",
    title: "Campaigns",
  },
  desk: {
    admin: false,
    description: "Call your campaign's contacts one at a time, oldest first, and record what you learn.",
    icon: HeadsetIcon,
    label: "My desk",
    title: "Call desk",
  },
  insights: {
    admin: true,
    description: "How the outcomes agents pick line up with the AI's scores of the same recorded calls.",
    icon: LightbulbIcon,
    label: "Insights",
    title: "Outcomes and AI scores",
  },
  kpis: {
    admin: false,
    description: "Calls, contacts reached, wins, and how the time on the desk is spent.",
    icon: BarChart3Icon,
    label: "KPIs",
    title: "Desk KPIs",
  },
  team: {
    admin: true,
    description: "Who is on the desk, the queues, the callbacks and the latest results.",
    icon: HistoryIcon,
    label: "Team board",
    title: "Team board",
  },
} as const;
type Tab = keyof typeof TABS;
const TAB_ORDER: Tab[] = ["desk", "team", "kpis", "insights", "campaigns"];

/** Operations: agents work their campaign's contacts one by one and see their KPIs; admins also get the team board,
 * everyone's KPIs, the outcome / AI score insights and the campaigns. */
export function OperationsPage({ route }: { route: Route }): React.ReactElement {
  const { isAdmin } = useMe();
  const tabs = TAB_ORDER.filter((t) => isAdmin || !TABS[t].admin);
  const asked = route.query.get("tab") as Tab | null;
  const tab: Tab = asked && tabs.includes(asked) ? asked : "desk";
  return (
    <>
      <PageHeader
        actions={
          <Tabs onValueChange={(v) => navigate(href("operations", null, { tab: v === "desk" ? "" : String(v) }), { replace: true })} value={tab}>
            <TabsList>
              {tabs.map((t) => {
                const Icon = TABS[t].icon;
                return (
                  <TabsTab key={t} value={t}>
                    <Icon aria-hidden="true" />
                    {t === "kpis" && !isAdmin ? "My KPIs" : TABS[t].label}
                  </TabsTab>
                );
              })}
            </TabsList>
          </Tabs>
        }
        description={TABS[tab].description}
        title={TABS[tab].title}
      />
      {tab === "desk" ? (
        <Desk />
      ) : tab === "team" ? (
        <OperationsBoard />
      ) : tab === "kpis" ? (
        <OperationsKpis route={route} />
      ) : tab === "insights" ? (
        <OperationsInsights route={route} />
      ) : (
        <OperationsCampaigns />
      )}
    </>
  );
}
