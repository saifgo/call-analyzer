import {
  CheckIcon,
  CircleAlertIcon,
  CopyIcon,
  CpuIcon,
  DownloadIcon,
  EllipsisIcon,
  KeyRoundIcon,
  MonitorSmartphoneIcon,
  PauseIcon,
  PencilIcon,
  PlayIcon,
  PlusIcon,
  Trash2Icon,
  UploadIcon,
  XIcon,
} from "lucide-react";
import * as React from "react";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogPopup,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardFooter,
  CardFrame,
  CardFrameHeader,
  CardFrameTitle,
  CardHeader,
  CardPanel,
  CardTitle,
} from "@/components/ui/card";
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
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Form } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Menu, MenuItem, MenuPopup, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
import { Progress, ProgressIndicator, ProgressTrack } from "@/components/ui/progress";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toastManager } from "@/components/ui/toast";
import { Tooltip, TooltipPopup, TooltipTrigger } from "@/components/ui/tooltip";
import { api, loginUrl, useApi } from "@/lib/api";
import { fmtDateTime, fmtRelative, numberFmt } from "@/lib/format";
import { href } from "@/lib/router";
import type { AgentInstaller, RunsOn, Worker, WorkersState, WorkerStep, WorkerTask } from "@/lib/types";
import { liveAgents, RUNS_ON_LABELS, STEP_NAMES, useWorkers } from "@/lib/workers";
import { cn } from "@/lib/utils";

const STEPS: WorkerStep[] = ["transcribe", "analyze"];
const SETTING_KEY: Record<WorkerStep, string> = { analyze: "ANALYZE_RUNS_ON", transcribe: "TRANSCRIBE_RUNS_ON" };
const RUNS_ON_ITEMS = (Object.keys(RUNS_ON_LABELS) as RunsOn[]).map((value) => ({
  label: RUNS_ON_LABELS[value],
  value,
}));
const STEP_HELP: Record<WorkerStep, string> = {
  analyze: "Claude or Cursor writes the feedback for each call.",
  transcribe: "Whisper turns each recording into text.",
};

/** Settings an agent works with, in the order they're shown. */
const SHOWN_SETTINGS = [
  "whisper_model",
  "whisper_device",
  "whisper_language",
  "transcribe_provider",
  "analysis_backend",
  "claude_backend",
  "claude_model",
  "feedback_language",
] as const;

function CopyField({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toastManager.add({ title: "Couldn't copy", description: "Select the text and copy it by hand.", type: "warning" });
    }
  };
  return (
    <div className="flex items-start gap-2">
      <pre
        aria-label={label}
        className="min-w-0 flex-1 select-all overflow-x-auto whitespace-pre-wrap break-all rounded-lg border bg-muted/48 px-3 py-2 font-mono text-xs"
      >
        {value}
      </pre>
      <Button aria-label={`Copy ${label}`} onClick={copy} size="icon" variant="outline">
        {copied ? <CheckIcon aria-hidden="true" /> : <CopyIcon aria-hidden="true" />}
      </Button>
    </div>
  );
}

/** One string with the server address and the token: what the installed agent asks for (see agent.encode_code). */
function connectionCode(server: string, token: string): string {
  const b64 = btoa(JSON.stringify({ s: server, t: token })).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
  return `ca1.${b64}`;
}

const mb = (bytes: number) => `${Math.round(bytes / 1_000_000)} MB`;

/** How to connect a PC: install the agent, paste the code. The command line is there for developers. */
function ConnectInstructions({ token }: { token: string }) {
  const { state } = useWorkers();
  const server = state?.public_url || location.origin;
  const code = connectionCode(server, token);
  const installers = state?.installers ?? [];
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <span className="font-medium text-sm">1. Install the agent on the PC</span>
        {installers.length > 0 || state?.download_url ? (
          <div className="flex flex-wrap gap-2">
            {installers.map((i) => (
              <Button
                key={i.name}
                render={<a download href={`/api/workers/installers/${encodeURIComponent(i.name)}`} />}
                variant="outline"
              >
                <DownloadIcon aria-hidden="true" />
                {i.kind === "gpu" ? "GPU installer" : "CPU installer"} ({mb(i.size)})
              </Button>
            ))}
            {state?.download_url && (
              <Button render={<a href={state.download_url} rel="noreferrer" target="_blank" />} variant="outline">
                <DownloadIcon aria-hidden="true" />
                Download the installer
              </Button>
            )}
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">
            Run <code className="rounded bg-muted px-1">CallAnalyzerAgent-Setup.exe</code> on the PC. (Put the
            installer in the server's <code className="rounded bg-muted px-1">data/downloads</code> folder, or set{" "}
            <code className="rounded bg-muted px-1">AGENT_DOWNLOAD_URL</code> in Settings, and it is offered here.)
          </p>
        )}
      </div>
      <div className="flex flex-col gap-2">
        <span className="font-medium text-sm">2. Paste this connection code when the agent asks for it</span>
        <CopyField label="connection code" value={code} />
        <p className="text-muted-foreground text-xs">
          The agent then shows an icon near the clock and works for this server. It connects out to{" "}
          <span className="font-mono">{server}</span>: no ports to open.
        </p>
      </div>
      <details className="text-sm">
        <summary className="w-fit cursor-pointer text-muted-foreground text-xs underline-offset-2 hover:underline">
          Command line (developers, or a PC without the installer)
        </summary>
        <div className="mt-2 flex flex-col gap-2">
          <CopyField label="login command" value={`python -m call_analyzer agent login --code ${code}`} />
          <CopyField label="run command" value="python -m call_analyzer agent run" />
        </div>
      </details>
    </div>
  );
}

function AddAgentDialog({ open, onOpenChange, onAdded }: { open: boolean; onOpenChange: (open: boolean) => void; onAdded: () => void }) {
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogPopup className="sm:max-w-xl">
        {/* Mounted on every open, so the form starts empty. */}
        <AddAgentForm onAdded={onAdded} />
      </DialogPopup>
    </Dialog>
  );
}

function AddAgentForm({ onAdded }: { onAdded: () => void }) {
  const [name, setName] = React.useState("");
  const [token, setToken] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const res = await api<{ token: string }>("/api/workers", { body: { name }, method: "POST" });
      setToken(res.token);
      onAdded();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (token) {
    return (
      <>
        <DialogHeader>
          <DialogTitle>Connect “{name}”</DialogTitle>
          <DialogDescription>The token is shown only once. Anyone who has it can work as this agent.</DialogDescription>
        </DialogHeader>
        <DialogPanel>
          <ConnectInstructions token={token} />
        </DialogPanel>
        <DialogFooter>
          <DialogClose render={<Button />}>Done</DialogClose>
        </DialogFooter>
      </>
    );
  }
  return (
    <Form className="contents" onSubmit={submit}>
      <DialogHeader>
        <DialogTitle>Add an agent</DialogTitle>
        <DialogDescription>
          A PC that transcribes and analyzes calls for this server, with its own GPU and Claude login.
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
          <FieldLabel>Name</FieldLabel>
          <Input
            autoFocus
            maxLength={64}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Office PC"
            required
            type="text"
            value={name}
          />
          <FieldDescription>Shown in the list and on every call this agent processes.</FieldDescription>
        </Field>
      </DialogPanel>
      <DialogFooter>
        <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
        <Button loading={saving} type="submit">
          Create agent
        </Button>
      </DialogFooter>
    </Form>
  );
}

/** Keeps showing the last agent while a dialog closes (its target is cleared as soon as it starts closing). */
function useLastWorker(worker: Worker | null): Worker | null {
  const [last, setLast] = React.useState(worker);
  if (worker && worker !== last) setLast(worker);
  return worker ?? last;
}

function RenameDialog({ worker, onOpenChange, onDone }: { worker: Worker | null; onOpenChange: (open: boolean) => void; onDone: () => void }) {
  const shown = useLastWorker(worker);
  return (
    <Dialog onOpenChange={onOpenChange} open={!!worker}>
      <DialogPopup className="sm:max-w-sm">
        {shown && (
          <RenameForm
            key={shown.id}
            onDone={() => {
              onDone();
              onOpenChange(false);
            }}
            worker={shown}
          />
        )}
      </DialogPopup>
    </Dialog>
  );
}

function RenameForm({ worker, onDone }: { worker: Worker; onDone: () => void }) {
  const [name, setName] = React.useState(worker.name);
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    try {
      await api(`/api/workers/${worker.id}`, { body: { name }, method: "PATCH" });
      onDone();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };
  return (
    <Form className="contents" onSubmit={submit}>
      <DialogHeader>
        <DialogTitle>Rename agent</DialogTitle>
      </DialogHeader>
      <DialogPanel className="flex flex-col gap-3">
        {error && (
          <Alert variant="error">
            <CircleAlertIcon aria-hidden="true" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <Input aria-label="Name" maxLength={64} onChange={(e) => setName(e.target.value)} required type="text" value={name} />
      </DialogPanel>
      <DialogFooter>
        <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
        <Button loading={saving} type="submit">
          Save
        </Button>
      </DialogFooter>
    </Form>
  );
}

/** Replaces the token and shows the new one once. */
function NewTokenDialog({ worker, onOpenChange }: { worker: Worker | null; onOpenChange: (open: boolean) => void }) {
  const shown = useLastWorker(worker);
  return (
    <Dialog onOpenChange={onOpenChange} open={!!worker}>
      <DialogPopup className="sm:max-w-xl">{shown && <NewTokenForm key={shown.id} worker={shown} />}</DialogPopup>
    </Dialog>
  );
}

function NewTokenForm({ worker }: { worker: Worker }) {
  const [token, setToken] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const generate = async () => {
    setBusy(true);
    try {
      setToken((await api<{ token: string }>(`/api/workers/${worker.id}/token`, { method: "POST" })).token);
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't create a token", type: "error" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <DialogHeader>
        <DialogTitle>New token for “{worker.name}”</DialogTitle>
        <DialogDescription>
          {token
            ? "The token is shown only once."
            : "The current token stops working at once: the agent has to log in again with the new one."}
        </DialogDescription>
      </DialogHeader>
      {token && (
        <DialogPanel>
          <ConnectInstructions token={token} />
        </DialogPanel>
      )}
      <DialogFooter>
        <DialogClose render={<Button variant="ghost" />}>{token ? "Done" : "Cancel"}</DialogClose>
        {!token && (
          <Button loading={busy} onClick={generate} variant="destructive">
            Replace token
          </Button>
        )}
      </DialogFooter>
    </>
  );
}

function RemoveDialog({ worker, onOpenChange, onDone }: { worker: Worker | null; onOpenChange: (open: boolean) => void; onDone: () => void }) {
  const [busy, setBusy] = React.useState(false);
  const shown = useLastWorker(worker);
  const remove = async () => {
    if (!worker) return;
    setBusy(true);
    try {
      await api(`/api/workers/${worker.id}`, { method: "DELETE" });
      toastManager.add({ title: `Removed ${worker.name}`, type: "success" });
      onDone();
      onOpenChange(false);
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't remove the agent", type: "error" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <AlertDialog onOpenChange={onOpenChange} open={!!worker}>
      <AlertDialogPopup>
        <AlertDialogHeader>
          <AlertDialogTitle>Remove {shown?.name}?</AlertDialogTitle>
          <AlertDialogDescription>
            Its token stops working and it disconnects. What it was working on goes back to the queue. Calls it already
            processed keep their results.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogClose render={<Button variant="ghost" />}>Cancel</AlertDialogClose>
          <Button loading={busy} onClick={remove} variant="destructive">
            Remove agent
          </Button>
        </AlertDialogFooter>
      </AlertDialogPopup>
    </AlertDialog>
  );
}

function CancelQueueDialog({ open, onOpenChange, onDone }: { open: boolean; onOpenChange: (open: boolean) => void; onDone: () => void }) {
  const [busy, setBusy] = React.useState(false);
  const cancel = async () => {
    setBusy(true);
    try {
      const res = await api<{ cancelled: number }>("/api/workers/tasks/cancel", { body: {}, method: "POST" });
      toastManager.add({ title: `Cancelled ${res.cancelled} ${res.cancelled === 1 ? "task" : "tasks"}`, type: "success" });
      onDone();
      onOpenChange(false);
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't cancel", type: "error" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <AlertDialog onOpenChange={onOpenChange} open={open}>
      <AlertDialogPopup>
        <AlertDialogHeader>
          <AlertDialogTitle>Cancel all waiting and running tasks?</AlertDialogTitle>
          <AlertDialogDescription>
            The calls stay as they are and can be processed again from the Pipeline page.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogClose render={<Button variant="ghost" />}>Keep them</AlertDialogClose>
          <Button loading={busy} onClick={cancel} variant="destructive">
            Cancel tasks
          </Button>
        </AlertDialogFooter>
      </AlertDialogPopup>
    </AlertDialog>
  );
}

// --- Installers ---------------------------------------------------------------------------------

const KIND_HELP: Record<AgentInstaller["kind"], string> = {
  cpu: "Works on any PC. Transcription runs on the processor.",
  gpu: "For PCs with an NVIDIA graphics card: much faster transcription. Includes the CUDA libraries, so it is large.",
};

function RemoveInstallerDialog({
  installer,
  onOpenChange,
  onDone,
}: {
  installer: AgentInstaller | null;
  onOpenChange: (open: boolean) => void;
  onDone: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [last, setLast] = React.useState(installer);
  if (installer && installer !== last) setLast(installer);
  const shown = installer ?? last;
  const remove = async () => {
    if (!installer) return;
    setBusy(true);
    try {
      await api(`/api/workers/installers/${encodeURIComponent(installer.name)}`, { method: "DELETE" });
      onDone();
      onOpenChange(false);
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't delete the installer", type: "error" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <AlertDialog onOpenChange={onOpenChange} open={!!installer}>
      <AlertDialogPopup>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {shown?.name}?</AlertDialogTitle>
          <AlertDialogDescription>
            It can no longer be downloaded from this page. PCs that already have it installed keep working.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogClose render={<Button variant="ghost" />}>Cancel</AlertDialogClose>
          <Button loading={busy} onClick={remove} variant="destructive">
            Delete
          </Button>
        </AlertDialogFooter>
      </AlertDialogPopup>
    </AlertDialog>
  );
}

/** Where people get the agent: download buttons for the installers on this server, and an upload for the admin. */
function InstallersCard({ state, reload }: { state: WorkersState; reload: () => Promise<void> }) {
  const input = React.useRef<HTMLInputElement>(null);
  const [upload, setUpload] = React.useState<{ name: string; pct: number } | null>(null);
  const [removing, setRemoving] = React.useState<AgentInstaller | null>(null);
  const installers = [...state.installers].sort((a, b) => a.kind.localeCompare(b.kind) || b.name.localeCompare(a.name));

  const send = (file: File) => {
    // XMLHttpRequest rather than fetch: it reports upload progress, which matters for a 1 GB file.
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `/api/workers/installers/${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) setUpload({ name: file.name, pct: Math.round((e.loaded * 100) / e.total) });
    };
    const fail = (detail: string) => {
      setUpload(null);
      toastManager.add({ description: detail, title: "Couldn't upload the installer", type: "error" });
    };
    xhr.onerror = () => fail("The connection dropped. Large files can also be refused by a proxy in front of the server.");
    xhr.onload = () => {
      if (xhr.status === 401) {
        location.href = loginUrl();
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        setUpload(null);
        toastManager.add({ title: `${file.name} uploaded`, type: "success" });
        reload();
        return;
      }
      let detail = xhr.statusText;
      try {
        detail = JSON.parse(xhr.responseText).detail || detail;
      } catch {
        // not JSON
      }
      fail(detail);
    };
    setUpload({ name: file.name, pct: 0 });
    xhr.send(file);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Get the agent for Windows</CardTitle>
        <CardDescription>
          Install it on any PC that should transcribe and analyze calls for this server. Then add the PC below and
          paste its connection code.
        </CardDescription>
      </CardHeader>
      <CardPanel className="flex flex-col gap-3">
        {installers.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No installer on this server yet. Build it on a Windows PC with{" "}
            <code className="rounded bg-muted px-1">packaging\build_agent.ps1</code> (see the README), then upload it
            here.
          </p>
        ) : (
          <ul className="flex flex-col divide-y rounded-lg border">
            {installers.map((i) => (
              <li className="flex flex-wrap items-center gap-x-4 gap-y-2 p-3" key={i.name}>
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-medium text-sm">{i.name}</span>
                    <Badge variant={i.kind === "gpu" ? "info" : "secondary"}>{i.kind === "gpu" ? "GPU" : "CPU"}</Badge>
                    {i.version && <Badge variant="outline">v{i.version}</Badge>}
                  </div>
                  <span className="text-muted-foreground text-xs">
                    {KIND_HELP[i.kind]} {mb(i.size)} · uploaded {fmtRelative(i.modified)}
                  </span>
                </div>
                <Button render={<a download href={`/api/workers/installers/${encodeURIComponent(i.name)}`} />}>
                  <DownloadIcon aria-hidden="true" />
                  Download
                </Button>
                <Button aria-label={`Delete ${i.name}`} onClick={() => setRemoving(i)} size="icon" variant="ghost">
                  <Trash2Icon aria-hidden="true" />
                </Button>
              </li>
            ))}
          </ul>
        )}
        {upload && (
          <Progress value={upload.pct}>
            <div className="flex items-center justify-between gap-2 text-sm">
              <span className="truncate">Uploading {upload.name}</span>
              <span className="text-muted-foreground tabular-nums">{upload.pct}%</span>
            </div>
            <ProgressTrack>
              <ProgressIndicator />
            </ProgressTrack>
          </Progress>
        )}
      </CardPanel>
      <CardFooter className="flex-wrap justify-between gap-2 border-t">
        <span className="text-muted-foreground text-xs">
          {state.download_url ? (
            <>
              Also available at{" "}
              <a className="underline underline-offset-2" href={state.download_url} rel="noreferrer" target="_blank">
                {state.download_url}
              </a>
            </>
          ) : (
            "Installers are stored in the server's data/downloads folder."
          )}
        </span>
        <input
          accept=".exe,.msi,.zip"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) send(file);
          }}
          ref={input}
          type="file"
        />
        <Button disabled={!!upload} onClick={() => input.current?.click()} size="sm" variant="outline">
          <UploadIcon aria-hidden="true" />
          Upload installer
        </Button>
      </CardFooter>
      <RemoveInstallerDialog installer={removing} onDone={reload} onOpenChange={(open) => !open && setRemoving(null)} />
    </Card>
  );
}

// --- Where each step runs -----------------------------------------------------------------------

function stepStatus(mode: RunsOn, ready: number): { text: string; warn: boolean } {
  if (mode === "host") return { text: "This server does it itself; agents are not used.", warn: false };
  const agents = `${ready} ${ready === 1 ? "agent is" : "agents are"} ready`;
  if (ready > 0) return { text: `${agents}${mode === "auto" ? "; the server steps in if they all go offline" : ""}.`, warn: false };
  return mode === "agent"
    ? { text: "No agent is ready: calls wait in the queue until one connects.", warn: true }
    : { text: "No agent is ready: this server does it for now.", warn: false };
}

function RoutingCard({ state, reload, onCancelQueue }: { state: WorkersState; reload: () => Promise<void>; onCancelQueue: () => void }) {
  const [saving, setSaving] = React.useState<WorkerStep | null>(null);
  const change = async (step: WorkerStep, value: RunsOn) => {
    setSaving(step);
    try {
      await api("/api/settings", { body: { [SETTING_KEY[step]]: value }, method: "PUT" });
      await reload();
      toastManager.add({ description: "Used by the next job.", title: "Saved", type: "success" });
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't save", type: "error" });
    } finally {
      setSaving(null);
    }
  };
  const queued = state.queue.queued;
  const running = state.queue.running;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Where processing runs</CardTitle>
        <CardDescription>
          Choose, for each step, whether this server does the work or remote agents do. Also in{" "}
          <a className="underline underline-offset-2" href={href("settings")}>
            Settings
          </a>
          .
        </CardDescription>
      </CardHeader>
      <CardPanel className="grid gap-6 md:grid-cols-2">
        {STEPS.map((step) => {
          const status = stepStatus(state.runs_on[step], liveAgents(state.workers, step).length);
          return (
            <Field key={step}>
              <FieldLabel>{STEP_NAMES[step]}</FieldLabel>
              <Select
                disabled={saving === step}
                items={RUNS_ON_ITEMS}
                onValueChange={(v) => change(step, v as RunsOn)}
                value={state.runs_on[step]}
              >
                <SelectTrigger aria-label={`${STEP_NAMES[step]} runs on`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectPopup>
                  {RUNS_ON_ITEMS.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectPopup>
              </Select>
              <FieldDescription className={cn(status.warn && "text-warning-foreground")}>
                {STEP_HELP[step]} {status.text}
              </FieldDescription>
            </Field>
          );
        })}
      </CardPanel>
      <CardFooter className="flex-wrap justify-between gap-2 border-t">
        <span className="text-muted-foreground text-sm">
          Queue: <span className="font-medium text-foreground tabular-nums">{numberFmt.format(queued)}</span> waiting ·{" "}
          <span className="font-medium text-foreground tabular-nums">{numberFmt.format(running)}</span> running
        </span>
        <Button disabled={queued + running === 0} onClick={onCancelQueue} size="sm" variant="outline">
          <XIcon aria-hidden="true" />
          Cancel tasks
        </Button>
      </CardFooter>
    </Card>
  );
}

// --- One agent ----------------------------------------------------------------------------------

function StatusBadge({ worker }: { worker: Worker }) {
  if (!worker.online) {
    return (
      <Tooltip>
        <TooltipTrigger render={<Badge variant="secondary" />}>Offline</TooltipTrigger>
        <TooltipPopup>{worker.last_seen ? `Last seen ${fmtRelative(worker.last_seen)}` : "Never connected yet"}</TooltipPopup>
      </Tooltip>
    );
  }
  return worker.enabled ? <Badge variant="success">Online</Badge> : <Badge variant="warning">Paused</Badge>;
}

function StepBadge({ step, worker }: { step: WorkerStep; worker: Worker }) {
  const cap = worker.info.capabilities?.[step];
  if (!cap) return <Badge variant="outline">{STEP_NAMES[step]}: unknown</Badge>;
  return (
    <Tooltip>
      <TooltipTrigger render={<Badge variant={cap.ok ? "success" : "warning"} />}>
        {STEP_NAMES[step]}
        {cap.ok ? "" : " · not ready"}
      </TooltipTrigger>
      <TooltipPopup className="max-w-xs">
        {cap.ok ? `Ready: ${cap.detail}${cap.slots > 1 ? ` (${cap.slots} at a time)` : ""}` : cap.reason || "Not set up"}
      </TooltipPopup>
    </Tooltip>
  );
}

function SettingsList({ worker, defaults }: { worker: Worker; defaults: Record<string, string> }) {
  const effective = worker.info.effective ?? {};
  const own = worker.info.overrides ?? {};
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
      {SHOWN_SETTINGS.filter((k) => k in effective || k in own).map((key) => {
        const value = key in own ? own[key] : (effective[key] ?? defaults[key] ?? "");
        return (
          <React.Fragment key={key}>
            <dt className="font-mono text-muted-foreground text-xs leading-5">{key}</dt>
            <dd className="flex min-w-0 items-center gap-1.5">
              <span className="truncate" dir="auto" title={String(value)}>
                {String(value) || <span className="text-muted-foreground">(empty)</span>}
              </span>
              {key in own && (
                <Tooltip>
                  <TooltipTrigger render={<Badge size="sm" variant="info" />}>agent.toml</TooltipTrigger>
                  <TooltipPopup className="max-w-xs">
                    Set on the agent itself. The server's default is “{defaults[key] ?? "not set"}”.
                  </TooltipPopup>
                </Tooltip>
              )}
            </dd>
          </React.Fragment>
        );
      })}
    </dl>
  );
}

function AgentCard({
  worker,
  defaults,
  onRename,
  onToken,
  onRemove,
  onToggle,
}: {
  worker: Worker;
  defaults: Record<string, string>;
  onRename: () => void;
  onToken: () => void;
  onRemove: () => void;
  onToggle: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const { info } = worker;
  const machine = [info.hostname, info.os, info.version && `v${info.version}`].filter(Boolean).join(" · ");
  return (
    <Card className={cn(!worker.online && "opacity-80")}>
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <span
                aria-hidden="true"
                className={cn(
                  "size-2 shrink-0 rounded-full",
                  worker.online ? (worker.enabled ? "bg-success" : "bg-warning") : "bg-muted-foreground/40",
                )}
              />
              <span className="truncate" dir="auto">
                {worker.name}
              </span>
              <StatusBadge worker={worker} />
            </CardTitle>
            <CardDescription className="truncate">{machine || "Hasn't connected yet"}</CardDescription>
          </div>
          <Menu>
            <MenuTrigger render={<Button aria-label={`Actions for ${worker.name}`} size="icon-sm" variant="ghost" />}>
              <EllipsisIcon aria-hidden="true" />
            </MenuTrigger>
            <MenuPopup align="end">
              <MenuItem onClick={onToggle}>
                {worker.enabled ? <PauseIcon aria-hidden="true" /> : <PlayIcon aria-hidden="true" />}
                {worker.enabled ? "Pause" : "Resume"}
              </MenuItem>
              <MenuItem onClick={onRename}>
                <PencilIcon aria-hidden="true" />
                Rename
              </MenuItem>
              <MenuItem onClick={onToken}>
                <KeyRoundIcon aria-hidden="true" />
                New token
              </MenuItem>
              <MenuSeparator />
              <MenuItem onClick={onRemove} variant="destructive">
                <Trash2Icon aria-hidden="true" />
                Remove
              </MenuItem>
            </MenuPopup>
          </Menu>
        </div>
      </CardHeader>
      <CardPanel className="flex flex-col gap-4">
        <div className="flex flex-wrap gap-1.5">
          {info.gpu !== undefined && (
            <Badge variant="outline">
              <CpuIcon aria-hidden="true" />
              {info.gpu ? "GPU" : "CPU only"}
            </Badge>
          )}
          {STEPS.map((step) => (
            <StepBadge key={step} step={step} worker={worker} />
          ))}
        </div>

        {worker.running.length > 0 ? (
          <ul className="flex flex-col gap-1.5 text-sm">
            {worker.running.map((t) => (
              <li className="flex items-center gap-2" key={t.id}>
                <span aria-hidden="true" className="size-1.5 shrink-0 animate-pulse rounded-full bg-info" />
                <span className="truncate">
                  {STEP_NAMES[t.kind]} · call {t.call_id}
                  {t.progress && <span className="text-muted-foreground"> · {t.progress}</span>}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground text-sm">{worker.online ? "Idle." : "Not connected."}</p>
        )}

        {Object.keys(info.effective ?? {}).length > 0 && (
          <div className="flex flex-col gap-2">
            <button
              className="w-fit text-muted-foreground text-xs underline-offset-2 hover:underline"
              onClick={() => setOpen((o) => !o)}
              type="button"
            >
              {open ? "Hide settings" : "Show the settings this agent uses"}
              {Object.keys(info.overrides ?? {}).length > 0 && ` (${Object.keys(info.overrides ?? {}).length} of its own)`}
            </button>
            {open && <SettingsList defaults={defaults} worker={worker} />}
          </div>
        )}
      </CardPanel>
      <CardFooter className="justify-between gap-2 border-t text-muted-foreground text-xs">
        <span>
          <span className="tabular-nums">{numberFmt.format(worker.done)}</span> done
          {worker.failed > 0 && (
            <>
              {" "}
              · <span className="tabular-nums">{numberFmt.format(worker.failed)}</span> failed
            </>
          )}
        </span>
        <span>{worker.online ? "Connected now" : worker.last_seen ? `Seen ${fmtRelative(worker.last_seen)}` : "Never seen"}</span>
      </CardFooter>
    </Card>
  );
}

// --- Tasks --------------------------------------------------------------------------------------

const TASK_VARIANT = {
  cancelled: "warning",
  done: "success",
  failed: "error",
  queued: "secondary",
  running: "info",
} as const;

function TasksTable({ state }: { state: WorkersState }) {
  const { data: tasks } = useApi<WorkerTask[]>("/api/workers/tasks?limit=30", [state]);
  if (!tasks?.length) return null;
  return (
    <CardFrame>
      <CardFrameHeader>
        <CardFrameTitle>Recent tasks</CardFrameTitle>
      </CardFrameHeader>
      <Table variant="card">
        <TableHeader>
          <TableRow>
            <TableHead>Call</TableHead>
            <TableHead>Step</TableHead>
            <TableHead>Agent</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="max-md:hidden">When</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tasks.map((t) => (
            <TableRow key={t.id}>
              <TableCell>
                <a className="font-medium underline-offset-2 hover:underline" href={href("calls", t.call_id)}>
                  {t.filename ?? t.call_id}
                </a>
                {t.customer && <div className="text-muted-foreground text-xs">{t.customer}</div>}
              </TableCell>
              <TableCell>{STEP_NAMES[t.kind]}</TableCell>
              <TableCell className="text-muted-foreground">{t.worker_name ?? "—"}</TableCell>
              <TableCell className="max-w-72">
                <Badge variant={TASK_VARIANT[t.status]}>{t.status}</Badge>
                {(t.status === "running" ? t.progress : t.error) && (
                  <div className="mt-0.5 truncate text-muted-foreground text-xs" title={(t.status === "running" ? t.progress : t.error) ?? ""}>
                    {t.status === "running" ? t.progress : t.error}
                  </div>
                )}
              </TableCell>
              <TableCell className="whitespace-nowrap text-muted-foreground max-md:hidden">
                {fmtDateTime(t.finished_at ?? t.created_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </CardFrame>
  );
}

// --- Page ---------------------------------------------------------------------------------------

export function AgentsPage(): React.ReactElement {
  const { state, reload } = useWorkers();
  const [adding, setAdding] = React.useState(false);
  const [renaming, setRenaming] = React.useState<Worker | null>(null);
  const [tokenFor, setTokenFor] = React.useState<Worker | null>(null);
  const [removing, setRemoving] = React.useState<Worker | null>(null);
  const [cancelling, setCancelling] = React.useState(false);

  const toggle = async (worker: Worker) => {
    try {
      await api(`/api/workers/${worker.id}`, { body: { enabled: !worker.enabled }, method: "PATCH" });
      await reload();
      toastManager.add({
        description: worker.enabled ? "It finishes what it's doing and takes no new work." : undefined,
        title: worker.enabled ? `Paused ${worker.name}` : `Resumed ${worker.name}`,
        type: "success",
      });
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't update the agent", type: "error" });
    }
  };

  const addButton = (
    <Button onClick={() => setAdding(true)}>
      <PlusIcon aria-hidden="true" />
      Add agent
    </Button>
  );
  const online = state ? state.workers.filter((w) => w.online && w.enabled).length : 0;

  return (
    <>
      <PageHeader
        actions={addButton}
        description={
          state
            ? `${online} of ${state.workers.length} ${state.workers.length === 1 ? "agent" : "agents"} online. Agents are PCs that connect to this server and do the transcription and analysis.`
            : "PCs that connect to this server and do the transcription and analysis."
        }
        title="Remote agents"
      />

      {!state ? (
        <div className="flex flex-col gap-6">
          <Skeleton className="h-52 rounded-2xl" />
          <Skeleton className="h-64 rounded-2xl" />
        </div>
      ) : (
        <>
          <InstallersCard reload={reload} state={state} />
          <RoutingCard onCancelQueue={() => setCancelling(true)} reload={reload} state={state} />

          {state.workers.length === 0 ? (
            <Card>
              <Empty>
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <MonitorSmartphoneIcon />
                  </EmptyMedia>
                  <EmptyTitle>No agents yet</EmptyTitle>
                  <EmptyDescription>
                    Add a PC with a GPU or a Claude login: it connects to this server, takes the calls to process and
                    sends the results back. It only needs internet access.
                  </EmptyDescription>
                </EmptyHeader>
                <EmptyContent>{addButton}</EmptyContent>
              </Empty>
            </Card>
          ) : (
            <>
              {STEPS.some((s) => state.runs_on[s] === "agent") && online === 0 && (
                <Alert variant="warning">
                  <CircleAlertIcon aria-hidden="true" />
                  <AlertTitle>No agent is online</AlertTitle>
                  <AlertDescription>
                    Calls for steps set to “Remote agents only” wait in the queue and are processed as soon as an agent
                    connects.
                  </AlertDescription>
                </Alert>
              )}
              <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
                {state.workers.map((w) => (
                  <AgentCard
                    defaults={state.defaults}
                    key={w.id}
                    onRemove={() => setRemoving(w)}
                    onRename={() => setRenaming(w)}
                    onToggle={() => toggle(w)}
                    onToken={() => setTokenFor(w)}
                    worker={w}
                  />
                ))}
              </div>
            </>
          )}

          <TasksTable state={state} />
        </>
      )}

      <AddAgentDialog onAdded={reload} onOpenChange={setAdding} open={adding} />
      <RenameDialog onDone={reload} onOpenChange={(open) => !open && setRenaming(null)} worker={renaming} />
      <NewTokenDialog onOpenChange={(open) => !open && setTokenFor(null)} worker={tokenFor} />
      <RemoveDialog onDone={reload} onOpenChange={(open) => !open && setRemoving(null)} worker={removing} />
      <CancelQueueDialog onDone={reload} onOpenChange={setCancelling} open={cancelling} />
    </>
  );
}
