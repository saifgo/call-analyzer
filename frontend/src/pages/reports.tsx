import { CheckIcon, CircleAlertIcon, CopyIcon, ExternalLinkIcon, FileTextIcon, Link2Icon, SparklesIcon, UserIcon, UsersIcon } from "lucide-react";
import { marked } from "marked";
import * as React from "react";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { Skeleton } from "@/components/ui/skeleton";
import { toastManager } from "@/components/ui/toast";
import { api, useApi } from "@/lib/api";
import { fixBidiDom } from "@/lib/bidi";
import { fmtDateTime } from "@/lib/format";
import { useJob, useOnJobFinished } from "@/lib/jobs";
import { useMe } from "@/lib/me";
import { href, navigate, type Route } from "@/lib/router";
import type { ReportFile, Share } from "@/lib/types";
import { cn } from "@/lib/utils";

/** "20261003-1430-agent-101.md" -> { run: "20261003-1430", who: "Agent 101", team: false } */
function parseName(name: string) {
  const m = name.match(/^(\d{8}-\d{4})-(.+)\.md$/);
  if (!m) return { run: "", team: false, who: name.replace(/\.md$/, "") };
  const team = m[2] === "team";
  return { run: m[1], team, who: team ? "Whole team" : `Agent ${m[2].replace(/^agent-/, "")}` };
}

function runLabel(run: string, fallback: string) {
  const m = run.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})$/);
  return m ? fmtDateTime(`${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}`) : fallback;
}

function ReportShareDialog({ name, open, onOpenChange }: { name: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  const base = `/api/reports/${encodeURIComponent(name)}/share`;
  const { data: share, setData } = useApi<Share>(open ? base : null, [open, name]);
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
            A private link to this coaching report. Anyone with the link can read it without signing in.
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
                    restart the app. To send it to anyone, download the PDF instead.
                  </AlertDescription>
                </Alert>
              )}
            </>
          ) : (
            <p className="text-muted-foreground text-sm">No link exists for this report yet.</p>
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

function ReportView({ name }: { name: string }) {
  const { data } = useApi<{ name: string; text: string }>(`/api/reports/${encodeURIComponent(name)}`);
  const html = React.useMemo(() => (data ? (marked.parse(data.text, { async: false }) as string) : ""), [data]);
  const ref = React.useRef<HTMLDivElement>(null);
  React.useLayoutEffect(() => fixBidiDom(ref.current), [html]);

  if (!data || data.name !== name) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
        <Skeleton className="h-4 w-4/6" />
      </div>
    );
  }
  return (
    <article
      className="prose prose-neutral dark:prose-invert prose-sm sm:prose-base max-w-none prose-headings:font-heading prose-h1:text-2xl prose-headings:tracking-tight [&_[dir=rtl]]:text-right"
      // biome-ignore lint/security/noDangerouslySetInnerHtml: reports are generated locally by our own pipeline.
      dangerouslySetInnerHTML={{ __html: html }}
      ref={ref}
    />
  );
}

export function ReportsPage({ route }: { route: Route }): React.ReactElement {
  const job = useJob();
  // Agent accounts only get their own reports (the server filters them) and can't generate or share.
  const { isAdmin } = useMe();
  const { data: reports, reload } = useApi<ReportFile[]>("/api/reports");
  useOnJobFinished(reload);
  const selected = route.param ?? reports?.[0]?.name ?? null;
  const [shareOpen, setShareOpen] = React.useState(false);

  const groups = React.useMemo(() => {
    const map = new Map<string, ReportFile[]>();
    for (const r of reports ?? []) {
      const { run } = parseName(r.name);
      const key = run || r.modified;
      map.set(key, [...(map.get(key) ?? []), r]);
    }
    // Team report first within a run.
    return [...map.entries()].map(([run, files]) => ({
      files: files.sort((a, b) => Number(parseName(b.name).team) - Number(parseName(a.name).team)),
      label: runLabel(run, fmtDateTime(files[0].modified)),
      run,
    }));
  }, [reports]);

  const generate = (
    <Button disabled={!!job.state?.running} onClick={() => job.start(["report"], { min_duration: 0 })}>
      <SparklesIcon aria-hidden="true" />
      Generate reports
    </Button>
  );

  return (
    <>
      <PageHeader
        actions={isAdmin ? generate : undefined}
        description={isAdmin ? "Coaching reports for the whole team and for each agent." : "Your coaching reports."}
        title="Reports"
      />

      {!reports ? (
        <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
          <Skeleton className="h-80 rounded-2xl" />
          <Skeleton className="h-[60vh] rounded-2xl" />
        </div>
      ) : reports.length === 0 ? (
        <Card>
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <FileTextIcon />
              </EmptyMedia>
              <EmptyTitle>No reports yet</EmptyTitle>
              <EmptyDescription>
                {isAdmin
                  ? "Analyze some calls, then generate coaching reports from them."
                  : "Your coaching reports appear here once your manager generates them."}
              </EmptyDescription>
            </EmptyHeader>
            {isAdmin && <EmptyContent>{generate}</EmptyContent>}
          </Empty>
        </Card>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-[18rem_1fr]">
          <nav aria-label="Reports" className="flex flex-col gap-5 lg:sticky lg:top-20">
            {groups.map((g) => (
              <div className="flex flex-col gap-1" key={g.run}>
                <h2 className="px-2 font-medium text-muted-foreground text-xs">{g.label}</h2>
                {g.files.map((r) => {
                  const info = parseName(r.name);
                  const active = r.name === selected;
                  return (
                    <Button
                      aria-current={active ? "page" : undefined}
                      className={cn("justify-start font-normal", active && "bg-accent font-medium")}
                      key={r.name}
                      onClick={() => navigate(href("reports", r.name), { replace: true })}
                      variant="ghost"
                    >
                      {info.team ? <UsersIcon aria-hidden="true" /> : <UserIcon aria-hidden="true" />}
                      {info.who}
                    </Button>
                  );
                })}
              </div>
            ))}
          </nav>
          <Card className="min-w-0">
            <CardPanel className="p-6 sm:p-8">
              {selected && (
                <>
                  <div className="mb-6 flex flex-wrap items-center justify-end gap-2 border-b pb-4">
                    <Button
                      render={<a href={`/api/reports/${encodeURIComponent(selected)}/export.pdf`} />}
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        toastManager.add({
                          description: "The download starts in a few seconds.",
                          title: "Creating PDF…",
                          type: "info",
                        })
                      }
                    >
                      <FileTextIcon aria-hidden="true" />
                      Download PDF
                    </Button>
                    {isAdmin && (
                      <Button onClick={() => setShareOpen(true)} size="sm" variant="outline">
                        <Link2Icon aria-hidden="true" />
                        Share link
                      </Button>
                    )}
                  </div>
                  <ReportView key={selected} name={selected} />
                  {isAdmin && <ReportShareDialog name={selected} onOpenChange={setShareOpen} open={shareOpen} />}
                </>
              )}
            </CardPanel>
          </Card>
        </div>
      )}
    </>
  );
}
