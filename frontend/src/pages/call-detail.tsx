import {
  CheckIcon,
  CircleAlertIcon,
  ClockIcon,
  CopyIcon,
  DownloadIcon,
  ExternalLinkIcon,
  FileCodeIcon,
  FileTextIcon,
  LightbulbIcon,
  Link2Icon,
  MicIcon,
  PencilLineIcon,
  ShareIcon,
  SparklesIcon,
  WorkflowIcon,
} from "lucide-react";
import * as React from "react";
import { OutcomeBadge, ScoreBadge, scoreVariant, StatusBadge } from "@/components/call-badges";
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
import { Menu, MenuItem, MenuLinkItem, MenuPopup, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
import { Meter, MeterIndicator, MeterLabel, MeterTrack } from "@/components/ui/meter";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetDescription, SheetHeader, SheetPanel, SheetPopup, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { toastManager } from "@/components/ui/toast";
import { api, useApi } from "@/lib/api";
import { Bidi, textDir } from "@/lib/bidi";
import { fmtDateTime, fmtDuration, fmtRelative, humanize } from "@/lib/format";
import { useJob, useOnJobFinished } from "@/lib/jobs";
import { useMe } from "@/lib/me";
import type { Analysis, CallDetail, Share } from "@/lib/types";
import { cn } from "@/lib/utils";

const SCORE_NAMES: Record<string, string> = {
  closing: "Closing",
  discovery: "Discovery",
  objection_handling: "Objections",
  opening: "Opening",
  pitch: "Pitch",
  tone_and_listening: "Tone & listening",
};

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
  if (!items?.length) return <p className="text-muted-foreground text-sm">None</p>;
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
function ProcessedBy({ verb, at, by }: { verb: string; at: string | null; by: string | null }) {
  if (!at) return null;
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 text-muted-foreground text-xs">
      <ClockIcon aria-hidden="true" className="size-3.5" />
      <span title={fmtRelative(at)}>
        {verb} {fmtDateTime(at)}
      </span>
      <span aria-hidden="true">·</span>
      <span className={by ? "font-medium text-foreground" : undefined}>{by ? `by ${by}` : "model not recorded"}</span>
    </p>
  );
}

/** `onReanalyze` is only given to admins; agents just read the feedback. */
function Feedback({ call, onReanalyze }: { call: CallDetail; onReanalyze?: () => void }) {
  const a = call.analysis as Analysis;
  return (
    <div className="flex flex-col gap-6">
      <ProcessedBy at={call.analyzed_at} by={call.analyzed_by} verb="Analyzed" />
      {call.status === "stale" && onReanalyze && (
        <Alert variant="warning">
          <PencilLineIcon aria-hidden="true" />
          <AlertTitle>Transcript changed after this analysis</AlertTitle>
          <AlertDescription>Re-analyze so the feedback uses your corrections.</AlertDescription>
          <AlertAction>
            <Button onClick={onReanalyze} size="sm" variant="outline">
              Re-analyze
            </Button>
          </AlertAction>
        </Alert>
      )}

      <div className="flex flex-wrap gap-1.5">
        <OutcomeBadge outcome={a.outcome} />
        {a.call_category && <Badge variant="secondary">{humanize(a.call_category)}</Badge>}
        {a.customer_interest && <Badge variant="outline">Interest: {humanize(a.customer_interest)}</Badge>}
        {a.is_sales_conversation === false && <Badge variant="warning">Not a sales conversation</Badge>}
      </div>

      <Section title="Summary">
        <Bidi className="text-sm leading-relaxed" text={a.summary} />
      </Section>

      {a.top_coaching_tip && (
        <Alert variant="info">
          <LightbulbIcon aria-hidden="true" />
          <AlertTitle>Top coaching tip</AlertTitle>
          <AlertDescription>
            <Bidi className="w-full text-foreground" text={a.top_coaching_tip} />
          </AlertDescription>
        </Alert>
      )}

      <Section title="Scores">
        <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
          {Object.entries(SCORE_NAMES).map(([key, name]) => {
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

      <Section title="Strengths">
        <BulletList items={a.strengths} />
      </Section>

      <Section title="Mistakes and what to say instead">
        {a.mistakes?.length ? (
          a.mistakes.map((m, i) => (
            <Card className="rounded-xl" key={i}>
              <CardPanel className="flex flex-col gap-3 p-4">
                <Labeled label="Said" text={m.quote} tone="quote" />
                <Labeled label="Why it hurt" text={m.problem} />
                <Labeled label="Say instead" text={m.better_version} tone="better" />
              </CardPanel>
            </Card>
          ))
        ) : (
          <p className="text-muted-foreground text-sm">None</p>
        )}
      </Section>

      <Section title="Objections">
        {a.objections?.length ? (
          a.objections.map((o, i) => (
            <Card className="rounded-xl" key={i}>
              <CardPanel className="flex flex-col gap-3 p-4">
                <Labeled label="Objection" text={o.objection} />
                <Labeled label="How it was handled" text={o.how_handled} tone="muted" />
                <Labeled label="Better answer" text={o.better_answer} tone="better" />
              </CardPanel>
            </Card>
          ))
        ) : (
          <p className="text-muted-foreground text-sm">None</p>
        )}
      </Section>

      <Section title="Missed opportunities">
        <BulletList items={a.missed_opportunities} />
      </Section>

      <Section title="Follow-up">
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
          <EmptyTitle>No transcript yet</EmptyTitle>
          <EmptyDescription>This call hasn't been transcribed yet.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <ProcessedBy at={call.transcribed_at} by={call.transcribed_by} verb="Transcribed" />
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
    toastManager.add({ title: "Transcript saved", type: "success" });
  };

  const run = async (reanalyze: boolean) => {
    setSaving(true);
    try {
      if (dirty) await save();
      if (reanalyze) await job.start(["analyze"], { ids: call.id, redo: true });
      onSaved();
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't save", type: "error" });
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
          <EmptyTitle>No transcript yet</EmptyTitle>
          <EmptyDescription>
            {call.has_audio ? "Transcribe this call to read and correct it here." : "Download and transcribe this call first."}
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <ProcessedBy at={call.transcribed_at} by={call.transcribed_by} verb="Transcribed" />
      <p className="text-muted-foreground text-sm">
        Fix misheard words or speaker names, then save and re-analyze so the feedback uses your corrections.
      </p>
      <Textarea
        aria-label="Transcript"
        className="min-h-[50vh] leading-relaxed"
        dir={textDir(text)}
        onChange={(e) => setText(e.target.value)}
        value={text}
      />
      <div className="flex flex-wrap items-center justify-end gap-2">
        <span className="me-auto text-muted-foreground text-xs">
          {dirty && <Badge variant="warning">Unsaved changes</Badge>}
        </span>
        {dirty && (
          <Button onClick={() => setText(original)} variant="ghost">
            Discard
          </Button>
        )}
        <Button disabled={!dirty} loading={saving && !canReanalyze} onClick={() => run(false)} variant="outline">
          Save
        </Button>
        <Button disabled={!canReanalyze || !!job.state?.running} loading={saving} onClick={() => run(true)}>
          <SparklesIcon aria-hidden="true" />
          Save & re-analyze
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
    toastManager.add({ title: "Share link revoked", type: "success" });
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
          <DialogTitle>Share link</DialogTitle>
          <DialogDescription>
            A private link to a review page with an audio player. Anyone with the link can open it without signing in.
          </DialogDescription>
        </DialogHeader>
        <DialogPanel className="flex flex-col gap-4">
          {!share ? (
            <Skeleton className="h-9 w-full" />
          ) : share.url ? (
            <>
              <InputGroup>
                <InputGroupInput aria-label="Share link" readOnly type="text" value={share.url} />
                <InputGroupAddon align="inline-end">
                  <Button aria-label="Copy link" onClick={copy} size="icon-xs" variant="ghost">
                    {copied ? <CheckIcon aria-hidden="true" /> : <CopyIcon aria-hidden="true" />}
                  </Button>
                </InputGroupAddon>
              </InputGroup>
              {!share.lan && (
                <Alert variant="warning">
                  <CircleAlertIcon aria-hidden="true" />
                  <AlertTitle>Only works on this computer</AlertTitle>
                  <AlertDescription>
                    To share with others, set PUBLIC_URL (hosted) or SHARE_ON_LAN=true (local network) in Settings and
                    restart the app. To send it to anyone, export a PDF or HTML file instead.
                  </AlertDescription>
                </Alert>
              )}
            </>
          ) : (
            <p className="text-muted-foreground text-sm">No link exists for this call yet.</p>
          )}
        </DialogPanel>
        <DialogFooter>
          {share?.url ? (
            <>
              <Button className="sm:me-auto" onClick={revoke} variant="destructive-outline">
                Revoke link
              </Button>
              <Button render={<a href={share.url} rel="noreferrer" target="_blank" />} variant="outline">
                <ExternalLinkIcon aria-hidden="true" />
                Open
              </Button>
              <DialogClose render={<Button />}>Done</DialogClose>
            </>
          ) : (
            <>
              <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
              <Button disabled={!share} loading={busy} onClick={create}>
                <Link2Icon aria-hidden="true" />
                Create link
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogPopup>
    </Dialog>
  );
}

function CallBody({ callId, onChanged }: { callId: string; onChanged: () => void }) {
  const job = useJob();
  const { isAdmin } = useMe();
  const { data: call, error, reload } = useApi<CallDetail>(`/api/calls/${encodeURIComponent(callId)}`);
  useOnJobFinished(reload);
  const [tab, setTab] = React.useState<string>("feedback");
  const [shareOpen, setShareOpen] = React.useState(false);
  const running = !!job.state?.running;

  if (error) {
    return (
      <SheetPanel>
        <Alert variant="error">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>Couldn’t load this call</AlertTitle>
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
          <SheetTitle>Call #{call.id}</SheetTitle>
          <StatusBadge call={call} />
          {call.score !== null && <ScoreBadge score={call.score} />}
        </div>
        <SheetDescription>
          {fmtDateTime(call.date_call)} · {call.type} · Agent {call.agent} ↔ {call.customer} · {fmtDuration(call.duration)}
          {call.updated_at && (
            <span className="block text-xs" title={fmtDateTime(call.updated_at)}>
              Last updated {fmtRelative(call.updated_at)}
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
            Audio not downloaded yet.
            {isAdmin && (
              <Button disabled={running} onClick={() => job.start(["download"], ids)} size="sm" variant="outline">
                <DownloadIcon aria-hidden="true" />
                Download audio
              </Button>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {isAdmin && (
            <>
              {(!call.analysis || call.error) && (
                <Button disabled={running} onClick={() => job.start(["download", "transcribe", "analyze"], ids)} size="sm">
                  <WorkflowIcon aria-hidden="true" />
                  Process call
                </Button>
              )}
              <Button
                disabled={running || !call.has_audio}
                onClick={() => job.start(["transcribe"], { ...ids, redo: true })}
                size="sm"
                variant="outline"
              >
                <MicIcon aria-hidden="true" />
                {call.transcript !== null ? "Re-transcribe" : "Transcribe"}
              </Button>
              <Button
                disabled={running || !call.transcript}
                onClick={() => job.start(["analyze"], { ...ids, redo: true })}
                size="sm"
                variant="outline"
              >
                <SparklesIcon aria-hidden="true" />
                {call.analysis ? "Re-analyze" : "Analyze"}
              </Button>
              <Separator className="mx-1 h-5 max-sm:hidden" orientation="vertical" />
            </>
          )}
          <Menu>
            <MenuTrigger render={<Button size="sm" variant="outline" />}>
              <ShareIcon aria-hidden="true" />
              {isAdmin ? "Export & share" : "Export"}
            </MenuTrigger>
            <MenuPopup align="start">
              <MenuLinkItem
                href={`/api/calls/${id}/export.pdf`}
                onClick={() =>
                  toastManager.add({ description: "The download starts in a few seconds.", title: "Creating PDF…", type: "info" })
                }
              >
                <FileTextIcon aria-hidden="true" />
                Download PDF
              </MenuLinkItem>
              <MenuLinkItem href={`/api/calls/${id}/export.html`}>
                <FileCodeIcon aria-hidden="true" />
                HTML with audio
              </MenuLinkItem>
              {isAdmin && (
                <>
                  <MenuSeparator />
                  <MenuItem onClick={() => setShareOpen(true)}>
                    <Link2Icon aria-hidden="true" />
                    Share link…
                  </MenuItem>
                </>
              )}
            </MenuPopup>
          </Menu>
        </div>

        {isAdmin && call.error && (
          <Alert variant="error">
            <CircleAlertIcon aria-hidden="true" />
            <AlertTitle>Processing failed</AlertTitle>
            <AlertDescription className="break-words">{call.error}</AlertDescription>
          </Alert>
        )}

        <Tabs onValueChange={(v) => setTab(v as string)} value={tab}>
          <TabsList className="w-full sm:w-auto" variant="underline">
            <TabsTab value="feedback">Feedback</TabsTab>
            <TabsTab value="transcript">Transcript</TabsTab>
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
                  <EmptyTitle>No feedback yet</EmptyTitle>
                  <EmptyDescription>
                    {isAdmin
                      ? "Transcribe and analyze this call to get coaching."
                      : "The AI review of this call isn't ready yet."}
                  </EmptyDescription>
                </EmptyHeader>
                {isAdmin && (
                  <EmptyContent>
                    <Button disabled={running} onClick={() => job.start(["download", "transcribe", "analyze"], ids)} size="sm">
                      <WorkflowIcon aria-hidden="true" />
                      Process call
                    </Button>
                  </EmptyContent>
                )}
              </Empty>
            )}
          </TabsPanel>
          <TabsPanel className="pt-5" value="transcript">
            {isAdmin ? <TranscriptEditor call={call} onSaved={refresh} /> : <TranscriptView call={call} />}
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
}: {
  callId: string | null;
  onClose: () => void;
  onChanged: () => void;
}): React.ReactElement {
  // Keep showing the last call while the sheet animates closed.
  const [shownId, setShownId] = React.useState(callId);
  React.useEffect(() => {
    if (callId) setShownId(callId);
  }, [callId]);

  return (
    <Sheet onOpenChange={(open) => !open && onClose()} open={!!callId}>
      <SheetPopup className="max-w-3xl" side="right" variant="inset">
        {shownId && <CallBody callId={shownId} key={shownId} onChanged={onChanged} />}
      </SheetPopup>
    </Sheet>
  );
}
