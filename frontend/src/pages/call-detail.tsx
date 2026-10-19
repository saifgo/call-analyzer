import {
  CheckIcon,
  CircleAlertIcon,
  HeadsetIcon,
  BriefcaseIcon,
  ClockIcon,
  CopyIcon,
  DownloadIcon,
  ExternalLinkIcon,
  FileCodeIcon,
  FileTextIcon,
  LightbulbIcon,
  Link2Icon,
  MailIcon,
  MapPinIcon,
  MessageSquareTextIcon,
  MicIcon,
  PencilLineIcon,
  PhoneIcon,
  ShareIcon,
  SparklesIcon,
  Trash2Icon,
  UserRoundIcon,
  WorkflowIcon,
} from "lucide-react";
import * as React from "react";
import { OutcomeBadge, ScoreBadge, scoreVariant, StatusBadge } from "@/components/call-badges";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogPopup,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardPanel } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogPanel,
  DialogPopup,
  DialogTitle,
} from "@/components/ui/dialog";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Menu, MenuItem, MenuLinkItem, MenuPopup, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
import { Meter, MeterIndicator, MeterLabel, MeterTrack } from "@/components/ui/meter";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetDescription, SheetHeader, SheetPanel, SheetPopup, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { VoicePanel } from "@/components/voice-panel";
import { toastManager } from "@/components/ui/toast";
import { api, useApi } from "@/lib/api";
import { Bidi, textDir } from "@/lib/bidi";
import { fmtDate, fmtDateTime, fmtDuration, fmtRelative, humanize, numberFmt } from "@/lib/format";
import { labels, t, tx, useT } from "@/lib/i18n";
import { useJob, useOnJobFinished } from "@/lib/jobs";
import { campaignText } from "@/lib/campaign-text";
import { useMe } from "@/lib/me";
import type { Analysis, CallDetail, CrmLookup, CrmOpportunity, CrmPerson, HumanFeedback, Share } from "@/lib/types";
import { cn } from "@/lib/utils";

// Sales calls and customer service calls are judged on different score cards (ServiceScores in analyze.py).
const SALES_SCORE_NAMES: Record<string, string> = labels({
  closing: "value.closing",
  discovery: "value.discovery",
  objection_handling: "value.objection_handling",
  opening: "value.opening",
  pitch: "value.pitch",
  tone_and_listening: "value.tone_and_listening",
});

const SERVICE_SCORE_NAMES: Record<string, string> = labels({
  greeting: "value.greeting",
  understanding: "value.understanding",
  solution: "value.solution",
  clarity: "value.clarity",
  empathy_and_tone: "value.empathy_and_tone",
  resolution: "value.resolution",
});

const SCORE_COLOR = { error: "bg-destructive", success: "bg-success", warning: "bg-warning" };

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h3 className="font-heading font-semibold text-sm">{title}</h3>
      {children}
    </section>
  );
}

function BulletList({ items }: { items: string[] | undefined }) {
  if (!items?.length) return <p className="text-muted-foreground text-sm">{t("detail.none")}</p>;
  return (
    <ul className="flex flex-col gap-2 text-sm">
      {items.map((item, i) => {
        const dir = textDir(item);
        return (
          <li className="flex gap-2.5" dir={dir} key={i}>
            <span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-muted-foreground/48" />
            <Bidi as="span" className="text-start" text={item} />
          </li>
        );
      })}
    </ul>
  );
}

/** Label + text block inside a coaching card; the label sits on the same side as its text. */
function Labeled({ label, text, tone }: { label: string; text: string; tone?: "quote" | "better" | "muted" }) {
  const dir = textDir(text);
  return (
    <div className="flex flex-col gap-1" dir={dir}>
      <span className={cn("font-medium text-muted-foreground text-xs", tone === "better" && "text-success-foreground")}>
        {label}
      </span>
      <Bidi
        className={cn(
          "text-sm",
          tone === "quote" && "border-s-2 ps-3 italic",
          tone === "better" && "rounded-lg bg-success/8 px-3 py-2 dark:bg-success/16",
          tone === "muted" && "text-muted-foreground",
        )}
        text={text}
      />
    </div>
  );
}

/** "Analyzed 3 Oct, 12:52 · by Claude claude-opus-5-5 (API)" */
function ProcessedBy({ verb, at, by }: { verb: "detail.analyzedAt" | "detail.transcribedAt"; at: string | null; by: string | null }) {
  if (!at) return null;
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 text-muted-foreground text-xs">
      <ClockIcon aria-hidden="true" className="size-3.5" />
      <span title={fmtRelative(at)}>{t(verb, { time: fmtDateTime(at) })}</span>
      <span aria-hidden="true">·</span>
      <span className={by ? "font-medium text-foreground" : undefined}>{by ? t("detail.by", { by }) : t("detail.modelNotRecorded")}</span>
    </p>
  );
}

/** `onReanalyze` is only given to admins; agents just read the feedback. */
function Feedback({ call, onReanalyze }: { call: CallDetail; onReanalyze?: () => void }) {
  const a = call.analysis as Analysis;
  const isService = call.kind === "service";
  const scoreNames = isService ? SERVICE_SCORE_NAMES : SALES_SCORE_NAMES;
  if (call.kind === "other") {
    // Voicemail, no answer, wrong number...: not rated, and left out of reports and average scores.
    return (
      <div className="flex flex-col gap-6">
        <ProcessedBy at={call.analyzed_at} by={call.analyzed_by} verb="detail.analyzedAt" />
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="warning">{t("detail.notSalesOrService")}</Badge>
        </div>
        <Section title={t("insights.summary")}>
          <Bidi className="text-sm leading-relaxed" text={a.summary} />
        </Section>
        <p className="text-muted-foreground text-sm">{t("detail.notRatedHint")}</p>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-6">
      <ProcessedBy at={call.analyzed_at} by={call.analyzed_by} verb="detail.analyzedAt" />
      {call.status === "stale" && onReanalyze && (
        <Alert variant="warning">
          <PencilLineIcon aria-hidden="true" />
          <AlertTitle>{t("detail.transcriptChanged")}</AlertTitle>
          <AlertDescription>{t("detail.transcriptChangedHint")}</AlertDescription>
          <AlertAction>
            <Button onClick={onReanalyze} size="sm" variant="outline">
              {t("calls.reanalyze")}
            </Button>
          </AlertAction>
        </Alert>
      )}

      <div className="flex flex-wrap gap-1.5">
        {isService && <Badge variant="outline">{t("calls.kind.service")}</Badge>}
        <OutcomeBadge outcome={a.outcome ?? a.resolution_status} />
        {(a.call_category ?? a.issue_category) && (
          <Badge variant="secondary">{humanize((a.call_category ?? a.issue_category) as string)}</Badge>
        )}
        {a.customer_interest && <Badge variant="outline">{t("detail.interest", { value: humanize(a.customer_interest) })}</Badge>}
        {a.customer_sentiment && (
          <Badge variant="outline">{t("voice.customerTone", { tone: humanize(a.customer_sentiment) })}</Badge>
        )}
      </div>

      {call.desk && (
        <Alert variant={call.desk.success ? "success" : "info"}>
          <HeadsetIcon aria-hidden="true" />
          <AlertTitle>{t("detail.callDesk", { outcome: campaignText(call.desk.outcome_label) ?? humanize(call.desk.outcome) })}</AlertTitle>
          <AlertDescription>
            <span>
              {campaignText(call.desk.campaign)} · {t("detail.closedBy", { name: call.desk.agent_name })} · {fmtDateTime(call.desk.finished_at)}
              {call.desk.lead_url && (
                <>
                  {" · "}
                  <a className="underline" href={call.desk.lead_url} rel="noreferrer" target="_blank">
                    {t("leads.openInCrm")}
                  </a>
                </>
              )}
            </span>
            {call.desk.note && <Bidi className="w-full whitespace-pre-line text-foreground" text={call.desk.note} />}
          </AlertDescription>
        </Alert>
      )}

      <Section title={t("insights.summary")}>
        <Bidi className="text-sm leading-relaxed" text={a.summary} />
      </Section>

      {a.top_coaching_tip && (
        <Alert variant="info">
          <LightbulbIcon aria-hidden="true" />
          <AlertTitle>{t("detail.topTip")}</AlertTitle>
          <AlertDescription>
            <Bidi className="w-full text-foreground" text={a.top_coaching_tip} />
          </AlertDescription>
        </Alert>
      )}

      <Section title={t("detail.scores")}>
        <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
          {Object.entries(scoreNames).map(([key, name]) => {
            const value = a.scores?.[key];
            return (
              <Meter key={key} max={10} value={value ?? 0}>
                <div className="flex items-center justify-between gap-2">
                  <MeterLabel className="font-normal">{name}</MeterLabel>
                  <span className="font-medium text-sm tabular-nums">
                    {value ?? "–"}
                    <span className="font-normal text-muted-foreground">/10</span>
                  </span>
                </div>
                <MeterTrack className="rounded-full">
                  <MeterIndicator className={cn("rounded-full", value !== undefined && SCORE_COLOR[scoreVariant(value)])} />
                </MeterTrack>
              </Meter>
            );
          })}
        </div>
      </Section>

      <VoicePanel data={call.voice} tone={a.voice} />

      <Section title={t("detail.strengths")}>
        <BulletList items={a.strengths} />
      </Section>

      <Section title={t("detail.mistakes")}>
        {a.mistakes?.length ? (
          a.mistakes.map((m, i) => (
            <Card className="rounded-xl" key={i}>
              <CardPanel className="flex flex-col gap-3 p-4">
                <Labeled label={t("detail.said")} text={m.quote} tone="quote" />
                <Labeled label={t("detail.whyItHurt")} text={m.problem} />
                <Labeled label={t("detail.sayInstead")} text={m.better_version} tone="better" />
              </CardPanel>
            </Card>
          ))
        ) : (
          <p className="text-muted-foreground text-sm">{t("detail.none")}</p>
        )}
      </Section>

      {!isService && (
        <Section title={t("detail.objections")}>
          {a.objections?.length ? (
            a.objections.map((o, i) => (
              <Card className="rounded-xl" key={i}>
                <CardPanel className="flex flex-col gap-3 p-4">
                  <Labeled label={t("detail.objection")} text={o.objection} />
                  <Labeled label={t("detail.howHandled")} text={o.how_handled} tone="muted" />
                  <Labeled label={t("detail.betterAnswer")} text={o.better_answer} tone="better" />
                </CardPanel>
              </Card>
            ))
          ) : (
            <p className="text-muted-foreground text-sm">{t("detail.none")}</p>
          )}
        </Section>
      )}

      <Section title={t("detail.missed")}>
        <BulletList items={a.missed_opportunities} />
      </Section>

      <Section title={t("detail.followUp")}>
        <Bidi className="text-sm" text={a.follow_up_action} />
      </Section>

    </div>
  );
}

function TranscriptView({ call }: { call: CallDetail }) {
  if (call.transcript === null) {
    return (
      <Empty className="md:py-12">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <MicIcon />
          </EmptyMedia>
          <EmptyTitle>{t("detail.noTranscript")}</EmptyTitle>
          <EmptyDescription>{t("detail.notTranscribed")}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <ProcessedBy at={call.transcribed_at} by={call.transcribed_by} verb="detail.transcribedAt" />
      <div
        className="whitespace-pre-wrap rounded-xl border bg-muted/40 p-4 text-sm leading-relaxed"
        dir={textDir(call.transcript)}
      >
        {call.transcript}
      </div>
    </div>
  );
}

function TranscriptEditor({ call, onSaved }: { call: CallDetail; onSaved: () => void }) {
  const job = useJob();
  const original = call.transcript ?? "";
  const [text, setText] = React.useState(original);
  const [saving, setSaving] = React.useState(false);
  React.useEffect(() => setText(original), [original, call.id]);
  const dirty = text !== original;
  const canReanalyze = dirty || call.status === "stale" || (call.transcript !== null && !call.analysis);

  const save = async () => {
    await api(`/api/calls/${encodeURIComponent(call.id)}/transcript`, { body: { text }, method: "PUT" });
    toastManager.add({ title: t("detail.transcriptSaved"), type: "success" });
  };

  const run = async (reanalyze: boolean) => {
    setSaving(true);
    try {
      if (dirty) await save();
      if (reanalyze) await job.start(["analyze"], { ids: call.id, redo: true });
      onSaved();
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: t("common.couldntSave"), type: "error" });
    } finally {
      setSaving(false);
    }
  };

  if (call.transcript === null && !dirty) {
    return (
      <Empty className="md:py-12">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <MicIcon />
          </EmptyMedia>
          <EmptyTitle>{t("detail.noTranscript")}</EmptyTitle>
          <EmptyDescription>{call.has_audio ? t("detail.transcribeToEdit") : t("detail.downloadFirst")}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <ProcessedBy at={call.transcribed_at} by={call.transcribed_by} verb="detail.transcribedAt" />
      <p className="text-muted-foreground text-sm">{t("detail.editHint")}</p>
      <Textarea
        aria-label={t("detail.transcript")}
        className="min-h-[50vh] leading-relaxed"
        dir={textDir(text)}
        onChange={(e) => setText(e.target.value)}
        value={text}
      />
      <div className="flex flex-wrap items-center justify-end gap-2">
        <span className="me-auto text-muted-foreground text-xs">
          {dirty && <Badge variant="warning">{t("common.unsavedChanges")}</Badge>}
        </span>
        {dirty && (
          <Button onClick={() => setText(original)} variant="ghost">
            {t("common.discard")}
          </Button>
        )}
        <Button disabled={!dirty} loading={saving && !canReanalyze} onClick={() => run(false)} variant="outline">
          {t("common.save")}
        </Button>
        <Button disabled={!canReanalyze || !!job.state?.running} loading={saving} onClick={() => run(true)}>
          <SparklesIcon aria-hidden="true" />
          {t("detail.saveReanalyze")}
        </Button>
      </div>
    </div>
  );
}

function ShareDialog({ callId, open, onOpenChange }: { callId: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  const base = `/api/calls/${encodeURIComponent(callId)}/share`;
  const { data: share, setData } = useApi<Share>(open ? base : null, [open]);
  const [busy, setBusy] = React.useState(false);
  const [copied, setCopied] = React.useState(false);

  const create = async () => {
    setBusy(true);
    try {
      setData(await api<Share>(base, { method: "POST" }));
    } finally {
      setBusy(false);
    }
  };
  const revoke = async () => {
    await api(base, { method: "DELETE" });
    setData({ lan: share?.lan ?? false, token: null, url: null });
    toastManager.add({ title: t("share.revoked"), type: "success" });
  };
  const copy = async () => {
    if (!share?.url) return;
    await navigator.clipboard.writeText(share.url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogPopup className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("share.title")}</DialogTitle>
          <DialogDescription>{t("detail.shareDescription")}</DialogDescription>
        </DialogHeader>
        <DialogPanel className="flex flex-col gap-4">
          {!share ? (
            <Skeleton className="h-9 w-full" />
          ) : share.url ? (
            <>
              <InputGroup>
                <InputGroupInput aria-label={t("share.title")} dir="ltr" readOnly type="text" value={share.url} />
                <InputGroupAddon align="inline-end">
                  <Button aria-label={t("share.copy")} onClick={copy} size="icon-xs" variant="ghost">
                    {copied ? <CheckIcon aria-hidden="true" /> : <CopyIcon aria-hidden="true" />}
                  </Button>
                </InputGroupAddon>
              </InputGroup>
              {!share.lan && (
                <Alert variant="warning">
                  <CircleAlertIcon aria-hidden="true" />
                  <AlertTitle>{t("share.localOnly")}</AlertTitle>
                  <AlertDescription>{t("detail.localOnlyHint")}</AlertDescription>
                </Alert>
              )}
            </>
          ) : (
            <p className="text-muted-foreground text-sm">{t("detail.noLink")}</p>
          )}
        </DialogPanel>
        <DialogFooter>
          {share?.url ? (
            <>
              <Button className="sm:me-auto" onClick={revoke} variant="destructive-outline">
                {t("share.revoke")}
              </Button>
              <Button render={<a href={share.url} rel="noreferrer" target="_blank" />} variant="outline">
                <ExternalLinkIcon aria-hidden="true" />
                {t("share.open")}
              </Button>
              <DialogClose render={<Button />}>{t("common.done")}</DialogClose>
            </>
          ) : (
            <>
              <DialogClose render={<Button variant="ghost" />}>{t("common.cancel")}</DialogClose>
              <Button disabled={!share} loading={busy} onClick={create}>
                <Link2Icon aria-hidden="true" />
                {t("share.create")}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogPopup>
    </Dialog>
  );
}

const STAGE_VARIANT: Record<string, "success" | "info" | "warning" | "error" | "secondary"> = {
  ACCEPTED: "success",
  ACCOUNT_MADE: "success",
  ACTIVE: "success",
  ATTEMPTED: "warning",
  IN_TALK: "info",
  INSTALLING: "success",
  REJECTED: "error",
  WAITING_REPLY: "info",
};

function CrmField({ icon: Icon, children }: { icon: typeof MailIcon; children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-1.5">
      <Icon aria-hidden="true" className="size-3.5 shrink-0" />
      {children}
    </span>
  );
}

function CrmOpportunityRow({ o }: { o: CrmOpportunity }) {
  const amount = o.amount !== null ? `${numberFmt.format(o.amount)}${o.currency ? ` ${o.currency}` : ""}` : null;
  return (
    <li className="flex flex-col gap-1.5 rounded-lg border bg-muted/40 px-3 py-2.5 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <a className="inline-flex items-center gap-1.5 font-medium hover:underline" href={o.url} rel="noreferrer" target="_blank">
          {o.name}
          <ExternalLinkIcon aria-hidden="true" className="size-3 text-muted-foreground" />
        </a>
        {o.stage && <Badge variant={STAGE_VARIANT[o.stage] ?? "secondary"}>{humanize(o.stage)}</Badge>}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-muted-foreground text-xs">
        {amount && <span className="tabular-nums">{amount}</span>}
        {o.owner && <span>{t("detail.owner", { name: o.owner })}</span>}
        {o.company && <span>{o.company}</span>}
        {o.close_date && <span>{t("detail.closeDate", { date: fmtDate(o.close_date) })}</span>}
        {o.created_at && <span>{t("detail.createdOn", { date: fmtDate(o.created_at) })}</span>}
      </div>
    </li>
  );
}

function CrmPersonCard({ person }: { person: CrmPerson }) {
  return (
    <Card className="rounded-xl">
      <CardPanel className="flex flex-col gap-4 p-4">
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <a
              className="inline-flex items-center gap-1.5 font-heading font-semibold hover:underline"
              href={person.url}
              rel="noreferrer"
              target="_blank"
            >
              {person.name}
              <ExternalLinkIcon aria-hidden="true" className="size-3.5 text-muted-foreground" />
            </a>
            {person.job_title && <Badge variant="secondary">{person.job_title}</Badge>}
          </div>
          <div className="flex flex-col gap-1 text-muted-foreground text-sm">
            {person.phones.length > 0 && (
              <CrmField icon={PhoneIcon}>
                <span className="tabular-nums" dir="ltr">
                  {person.phones.join(" · ")}
                </span>
              </CrmField>
            )}
            {person.email && <CrmField icon={MailIcon}>{person.email}</CrmField>}
            {person.company && <CrmField icon={BriefcaseIcon}>{person.company}</CrmField>}
            {person.city && <CrmField icon={MapPinIcon}>{person.city}</CrmField>}
          </div>
          <p className="text-muted-foreground text-xs">
            {person.created_at && t("detail.inCrmSince", { date: fmtDate(person.created_at) })}
            {person.last_contact_at && ` · ${t("detail.lastContact", { time: fmtRelative(person.last_contact_at) })}`}
          </p>
        </div>
        <Separator />
        <div className="flex flex-col gap-2">
          <h4 className="font-medium text-sm">
            {t("detail.opportunities")}
            <span className="ms-1.5 font-normal text-muted-foreground tabular-nums">{person.opportunities.length}</span>
          </h4>
          {person.opportunities.length ? (
            <ul className="flex flex-col gap-2">
              {person.opportunities.map((o) => (
                <CrmOpportunityRow key={o.id} o={o} />
              ))}
            </ul>
          ) : (
            <p className="text-muted-foreground text-sm">{t("detail.noOpportunities")}</p>
          )}
        </div>
      </CardPanel>
    </Card>
  );
}

function CrmTab({ call, isAdmin }: { call: CallDetail; isAdmin: boolean }) {
  const { data, error, loading } = useApi<CrmLookup>(`/api/calls/${encodeURIComponent(call.id)}/crm`);

  if (error) {
    return (
      <Alert variant="error">
        <CircleAlertIcon aria-hidden="true" />
        <AlertTitle>{t("detail.crmFailed")}</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  if (!data || loading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </div>
    );
  }

  const empty = (title: string, description: string) => (
    <Empty className="md:py-12">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <UserRoundIcon />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
  if (!data.configured) {
    return empty(t("detail.crmNotConnected"), isAdmin ? t("detail.crmNotConnectedAdmin") : t("detail.crmNotConnectedAgent"));
  }
  if (!data.searched) {
    return empty(t("detail.noCustomerNumber"), t("detail.noCustomerNumberHint"));
  }
  if (!data.people.length) {
    return empty(t("detail.notInCrm"), t("detail.notInCrmHint", { number: data.number }));
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-muted-foreground text-sm">
        {tx("detail.contactsWithNumber", {
          count: data.people.length,
          number: (
            <span className="tabular-nums" dir="ltr">
              {data.number}
            </span>
          ),
        })}
      </p>
      {data.people.map((p) => (
        <CrmPersonCard key={p.id} person={p} />
      ))}
    </div>
  );
}

const scoreItems = () => [
  { label: t("detail.noScore"), value: "none" },
  ...Array.from({ length: 10 }, (_, i) => ({ label: `${i + 1} / 10`, value: String(i + 1) })),
];

/** Text + optional score; used to add feedback and to edit it. */
function FeedbackForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial?: { body: string; score: number | null };
  submitLabel: string;
  onSubmit: (value: { body: string; score: number | null }) => Promise<void>;
  onCancel?: () => void;
}) {
  const [body, setBody] = React.useState(initial?.body ?? "");
  const [score, setScore] = React.useState(initial?.score ? String(initial.score) : "none");
  const [busy, setBusy] = React.useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await onSubmit({ body, score: score === "none" ? null : Number(score) });
      if (!initial) {
        setBody("");
        setScore("none");
      }
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: t("detail.feedbackSaveFailed"), type: "error" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <Textarea
        aria-label={t("feedback.feedback")}
        className="min-h-24 leading-relaxed"
        dir={textDir(body)}
        onChange={(e) => setBody(e.target.value)}
        placeholder={t("detail.feedbackPlaceholder")}
        value={body}
      />
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Select items={scoreItems()} onValueChange={(v) => setScore(v as string)} value={score}>
          <SelectTrigger aria-label={t("detail.yourScore")} className="me-auto w-auto">
            <SelectValue />
          </SelectTrigger>
          <SelectPopup>
            {scoreItems().map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectPopup>
        </Select>
        {onCancel && (
          <Button onClick={onCancel} variant="ghost">
            {t("common.cancel")}
          </Button>
        )}
        <Button disabled={!body.trim()} loading={busy} onClick={submit}>
          {submitLabel}
        </Button>
      </div>
    </div>
  );
}

function FeedbackEntry({
  item,
  canEdit,
  onChanged,
}: {
  item: HumanFeedback;
  canEdit: boolean;
  onChanged: () => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const edited = item.updated_at !== item.created_at;

  const remove = async () => {
    setBusy(true);
    try {
      await api(`/api/feedback/${item.id}`, { method: "DELETE" });
      toastManager.add({ title: t("detail.feedbackDeleted"), type: "success" });
      onChanged();
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: t("common.couldntDelete"), type: "error" });
    } finally {
      setBusy(false);
      setDeleting(false);
    }
  };

  return (
    <Card className="rounded-xl">
      <CardPanel className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground text-xs">
          <span className="font-medium text-foreground text-sm">{item.author_name}</span>
          <span title={fmtDateTime(item.created_at)}>{fmtRelative(item.created_at)}</span>
          {edited && <span title={fmtDateTime(item.updated_at)}>· {t("detail.edited")}</span>}
          {item.score !== null && (
            <Badge className="ms-auto tabular-nums" variant="outline">
              {t("detail.scoreOf", { score: item.score })}
            </Badge>
          )}
        </div>
        {editing ? (
          <FeedbackForm
            initial={item}
            onCancel={() => setEditing(false)}
            onSubmit={async (value) => {
              await api(`/api/feedback/${item.id}`, { body: value, method: "PUT" });
              setEditing(false);
              onChanged();
            }}
            submitLabel={t("common.save")}
          />
        ) : (
          <>
            <Bidi className="whitespace-pre-wrap text-sm leading-relaxed" text={item.body} />
            {canEdit && (
              <div className="flex justify-end gap-1">
                <Button onClick={() => setEditing(true)} size="xs" variant="ghost">
                  <PencilLineIcon aria-hidden="true" />
                  {t("common.edit")}
                </Button>
                <Button onClick={() => setDeleting(true)} size="xs" variant="ghost">
                  <Trash2Icon aria-hidden="true" />
                  {t("common.delete")}
                </Button>
              </div>
            )}
          </>
        )}
        <AlertDialog onOpenChange={setDeleting} open={deleting}>
          <AlertDialogPopup>
            <AlertDialogHeader>
              <AlertDialogTitle>{t("detail.deleteFeedback")}</AlertDialogTitle>
              <AlertDialogDescription>{t("detail.deleteFeedbackHint")}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogClose render={<Button variant="ghost" />}>{t("common.cancel")}</AlertDialogClose>
              <Button loading={busy} onClick={remove} variant="destructive">
                {t("common.delete")}
              </Button>
            </AlertDialogFooter>
          </AlertDialogPopup>
        </AlertDialog>
      </CardPanel>
    </Card>
  );
}

/** Notes people wrote about this call. Admins add, edit and delete; agents just read. */
function HumanFeedbackTab({
  callId,
  isAdmin,
  items,
  onChanged,
}: {
  callId: string;
  isAdmin: boolean;
  items: HumanFeedback[] | undefined;
  onChanged: () => void;
}) {
  if (!items) return <Skeleton className="h-32 w-full rounded-xl" />;
  return (
    <div className="flex flex-col gap-5">
      {isAdmin && (
        <FeedbackForm
          onSubmit={async (value) => {
            await api(`/api/calls/${encodeURIComponent(callId)}/feedback`, { body: value, method: "POST" });
            toastManager.add({ title: t("detail.feedbackAdded"), type: "success" });
            onChanged();
          }}
          submitLabel={t("detail.addFeedback")}
        />
      )}
      {items.length ? (
        <div className="flex flex-col gap-3">
          {items.map((item) => (
            <FeedbackEntry canEdit={isAdmin} item={item} key={item.id} onChanged={onChanged} />
          ))}
        </div>
      ) : (
        <Empty className="md:py-10">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <MessageSquareTextIcon />
            </EmptyMedia>
            <EmptyTitle>{t("detail.noHuman")}</EmptyTitle>
            <EmptyDescription>{isAdmin ? t("detail.noHumanAdmin") : t("detail.noHumanAgent")}</EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
    </div>
  );
}

function CallBody({
  callId,
  onChanged,
  initialTab,
}: {
  callId: string;
  onChanged: () => void;
  initialTab?: string;
}) {
  const job = useJob();
  const { isAdmin } = useMe();
  const { data: call, error, reload } = useApi<CallDetail>(`/api/calls/${encodeURIComponent(callId)}`);
  useOnJobFinished(reload);
  const { data: human, reload: reloadHuman } = useApi<HumanFeedback[]>(`/api/calls/${encodeURIComponent(callId)}/feedback`);
  const [tab, setTab] = React.useState<string>(initialTab ?? "feedback");
  const [shareOpen, setShareOpen] = React.useState(false);
  const running = !!job.state?.running;

  if (error) {
    return (
      <SheetPanel>
        <Alert variant="error">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>{t("detail.loadFailed")}</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      </SheetPanel>
    );
  }
  if (!call || call.id !== callId) {
    return (
      <>
        <SheetHeader>
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-4 w-72" />
        </SheetHeader>
        <SheetPanel className="flex flex-col gap-4">
          <Skeleton className="h-10 w-full rounded-full" />
          <Skeleton className="h-8 w-80" />
          <Skeleton className="h-64 w-full rounded-xl" />
        </SheetPanel>
      </>
    );
  }

  const ids = { ids: call.id };
  const id = encodeURIComponent(call.id);
  const refresh = () => {
    reload();
    onChanged();
  };

  return (
    <>
      <SheetHeader className="pe-12">
        <div className="flex flex-wrap items-center gap-2">
          <SheetTitle>{t("detail.title", { id: call.id })}</SheetTitle>
          <StatusBadge call={call} />
          {call.score !== null && <ScoreBadge score={call.score} />}
        </div>
        <SheetDescription>
          {fmtDateTime(call.date_call)} · {call.type} · {t("shell.agentExt", { ext: call.agent })} ↔{" "}
          <span dir="ltr">{call.customer}</span> · {fmtDuration(call.duration)}
          {call.updated_at && (
            <span className="block text-xs" title={fmtDateTime(call.updated_at)}>
              {t("detail.lastUpdated", { time: fmtRelative(call.updated_at) })}
            </span>
          )}
        </SheetDescription>
      </SheetHeader>
      <SheetPanel className="flex flex-col gap-5">
        {call.has_audio ? (
          // biome-ignore lint/a11y/useMediaCaption: call recordings have no captions; the transcript is below.
          <audio className="h-10 w-full" controls preload="none" src={`/api/calls/${id}/audio`} />
        ) : (
          <div className="flex items-center justify-between gap-3 rounded-xl border border-dashed px-4 py-3 text-muted-foreground text-sm">
            {t("detail.noAudio")}
            {isAdmin && (
              <Button disabled={running} onClick={() => job.start(["download"], ids)} size="sm" variant="outline">
                <DownloadIcon aria-hidden="true" />
                {t("detail.downloadAudio")}
              </Button>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {isAdmin && (
            <>
              {(!call.analysis || call.error) && (
                <Button disabled={running} onClick={() => job.start(["download", "voice", "transcribe", "analyze"], ids)} size="sm">
                  <WorkflowIcon aria-hidden="true" />
                  {t("detail.processCall")}
                </Button>
              )}
              <Button
                disabled={running || !call.has_audio}
                onClick={() => job.start(["transcribe"], { ...ids, redo: true })}
                size="sm"
                variant="outline"
              >
                <MicIcon aria-hidden="true" />
                {call.transcript !== null ? t("calls.retranscribe") : t("jobs.step.transcribe")}
              </Button>
              <Button
                disabled={running || !call.transcript}
                onClick={() => job.start(["analyze"], { ...ids, redo: true })}
                size="sm"
                variant="outline"
              >
                <SparklesIcon aria-hidden="true" />
                {call.analysis ? t("calls.reanalyze") : t("jobs.step.analyze")}
              </Button>
              <Separator className="mx-1 h-5 max-sm:hidden" orientation="vertical" />
            </>
          )}
          <Menu>
            <MenuTrigger render={<Button size="sm" variant="outline" />}>
              <ShareIcon aria-hidden="true" />
              {isAdmin ? t("detail.exportShare") : t("detail.export")}
            </MenuTrigger>
            <MenuPopup align="start">
              <MenuLinkItem
                href={`/api/calls/${id}/export.pdf`}
                onClick={() =>
                  toastManager.add({ description: t("share.pdfStarting"), title: t("share.creatingPdf"), type: "info" })
                }
              >
                <FileTextIcon aria-hidden="true" />
                {t("share.downloadPdf")}
              </MenuLinkItem>
              <MenuLinkItem href={`/api/calls/${id}/export.html`}>
                <FileCodeIcon aria-hidden="true" />
                {t("detail.htmlWithAudio")}
              </MenuLinkItem>
              {isAdmin && (
                <>
                  <MenuSeparator />
                  <MenuItem onClick={() => setShareOpen(true)}>
                    <Link2Icon aria-hidden="true" />
                    {t("detail.shareLinkMenu")}
                  </MenuItem>
                </>
              )}
            </MenuPopup>
          </Menu>
        </div>

        {isAdmin && call.error && (
          <Alert variant="error">
            <CircleAlertIcon aria-hidden="true" />
            <AlertTitle>{t("detail.processingFailed")}</AlertTitle>
            <AlertDescription className="break-words">{call.error}</AlertDescription>
          </Alert>
        )}

        <Tabs onValueChange={(v) => setTab(v as string)} value={tab}>
          <TabsList className="w-full sm:w-auto" variant="underline">
            <TabsTab value="feedback">{t("feedback.feedback")}</TabsTab>
            <TabsTab value="transcript">{t("detail.transcript")}</TabsTab>
            <TabsTab value="human">
              {t("nav.feedback")}
              {!!human?.length && (
                <Badge className="ms-1.5 tabular-nums" size="sm" variant="secondary">
                  {human.length}
                </Badge>
              )}
            </TabsTab>
            <TabsTab value="crm">{t("nav.group.crm")}</TabsTab>
          </TabsList>
          <TabsPanel className="pt-5" value="feedback">
            {call.analysis ? (
              <Feedback
                call={call}
                onReanalyze={isAdmin ? () => job.start(["analyze"], { ...ids, redo: true }) : undefined}
              />
            ) : (
              <Empty className="md:py-12">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <SparklesIcon />
                  </EmptyMedia>
                  <EmptyTitle>{t("detail.noFeedback")}</EmptyTitle>
                  <EmptyDescription>{isAdmin ? t("detail.noFeedbackAdmin") : t("detail.noFeedbackAgent")}</EmptyDescription>
                </EmptyHeader>
                {isAdmin && (
                  <EmptyContent>
                    <Button disabled={running} onClick={() => job.start(["download", "voice", "transcribe", "analyze"], ids)} size="sm">
                      <WorkflowIcon aria-hidden="true" />
                      {t("detail.processCall")}
                    </Button>
                  </EmptyContent>
                )}
              </Empty>
            )}
          </TabsPanel>
          <TabsPanel className="pt-5" value="transcript">
            {isAdmin ? <TranscriptEditor call={call} onSaved={refresh} /> : <TranscriptView call={call} />}
          </TabsPanel>
          <TabsPanel className="pt-5" value="human">
            <HumanFeedbackTab
              callId={call.id}
              isAdmin={isAdmin}
              items={human}
              onChanged={() => {
                reloadHuman();
                onChanged();
              }}
            />
          </TabsPanel>
          <TabsPanel className="pt-5" value="crm">
            <CrmTab call={call} isAdmin={isAdmin} />
          </TabsPanel>
        </Tabs>
      </SheetPanel>
      {isAdmin && <ShareDialog callId={call.id} onOpenChange={setShareOpen} open={shareOpen} />}
    </>
  );
}

export function CallSheet({
  callId,
  onClose,
  onChanged,
  initialTab,
}: {
  callId: string | null;
  onClose: () => void;
  onChanged: () => void;
  /** Tab opened first: "feedback" (AI, default), "transcript", "human" or "crm". */
  initialTab?: string;
}): React.ReactElement {
  // Keep showing the last call while the sheet animates closed.
  const [shownId, setShownId] = React.useState(callId);
  React.useEffect(() => {
    if (callId) setShownId(callId);
  }, [callId]);
  const { dir } = useT();

  return (
    <Sheet onOpenChange={(open) => !open && onClose()} open={!!callId}>
      <SheetPopup className="max-w-3xl" side={dir === "rtl" ? "left" : "right"} variant="inset">
        {shownId && <CallBody callId={shownId} initialTab={initialTab} key={shownId} onChanged={onChanged} />}
      </SheetPopup>
    </Sheet>
  );
}
