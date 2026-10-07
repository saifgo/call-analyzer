// One background job at a time on the server; every page shares its state through this context.
import * as React from "react";
import { toastManager } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useGoVoice } from "@/lib/govoice";
import type { JobArgs, JobState } from "@/lib/types";

type JobContextValue = {
  state: JobState | null;
  lines: string[];
  /** Increments every time a job finishes, so pages can refetch their data. */
  finishedCount: number;
  start: (commands: string[], args?: JobArgs) => Promise<boolean>;
  stop: () => Promise<void>;
};

const JobContext = React.createContext<JobContextValue | null>(null);

export function useJob(): JobContextValue {
  const ctx = React.useContext(JobContext);
  if (!ctx) throw new Error("useJob must be used within JobProvider");
  return ctx;
}

/** Calls `fn` after each job finishes. */
export function useOnJobFinished(fn: () => void): void {
  const { finishedCount } = useJob();
  const ref = React.useRef(fn);
  ref.current = fn;
  const first = React.useRef(true);
  React.useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    ref.current();
  }, [finishedCount]);
}

export const STEP_LABELS: Record<string, string> = {
  check: "Setup check",
  sync: "Sync",
  download: "Download",
  transcribe: "Transcribe",
  voice: "Voice",
  analyze: "Analyze",
  report: "Report",
  run: "Run",
  "install-model": "Install Whisper model",
  "install-voice-model": "Install voice model",
};

/** Steps that talk to GoVoice and need a valid GoVoice session. */
const GOVOICE_STEPS = new Set(["sync", "download", "run"]);
/** Exit code of the CLI when the GoVoice session is missing or expired. */
const EXIT_GOVOICE_LOGIN = 3;

/** `enabled={false}` for agent accounts: they can't run jobs, so the job state isn't polled. */
export function JobProvider({
  children,
  enabled = true,
}: {
  children: React.ReactNode;
  enabled?: boolean;
}): React.ReactElement {
  const [state, setState] = React.useState<JobState | null>(null);
  const [lines, setLines] = React.useState<string[]>([]);
  const [finishedCount, setFinishedCount] = React.useState(0);
  const offset = React.useRef(0);
  const prev = React.useRef<JobState | null>(null);
  const timer = React.useRef<number | undefined>(undefined);
  const govoice = useGoVoice();
  const govoiceRef = React.useRef(govoice);
  React.useEffect(() => {
    govoiceRef.current = govoice;
  }, [govoice]);
  /** The last job started from this tab, retried after logging in to GoVoice. */
  const lastJob = React.useRef<{ commands: string[]; args: JobArgs; label: string } | null>(null);
  const startRef = React.useRef<(commands: string[], args?: JobArgs) => Promise<boolean>>(async () => false);

  const poll = React.useCallback(async () => {
    window.clearTimeout(timer.current);
    try {
      const next = await api<JobState>(`/api/jobs?since=${offset.current}`);
      const previous = prev.current;
      if (next.started_at !== previous?.started_at) {
        // A new job (possibly started from another tab): fetch its log from the start.
        offset.current = 0;
        if (next.offset > next.lines.length) {
          const full = await api<JobState>("/api/jobs?since=0");
          setLines(full.lines);
          offset.current = full.offset;
        } else {
          setLines(next.lines);
          offset.current = next.offset;
        }
      } else if (next.lines.length) {
        setLines((l) => [...l, ...next.lines]);
        offset.current = next.offset;
      }
      prev.current = next;
      setState(next);
      if (previous?.running && !next.running) {
        setFinishedCount((n) => n + 1);
        if (next.exit_code === EXIT_GOVOICE_LOGIN) {
          const job = lastJob.current?.label === next.label ? lastJob.current : null;
          govoiceRef.current.promptLogin(
            "The GoVoice session expired during the job",
            job ? () => startRef.current(job.commands, job.args) : undefined,
          );
          timer.current = window.setTimeout(poll, 4000);
          return;
        }
        const ok = next.exit_code === 0;
        // Ongoing mode runs every few minutes: only speak up when something went wrong.
        if (ok && next.auto) {
          timer.current = window.setTimeout(poll, 4000);
          return;
        }
        toastManager.add({
          title: ok ? "Job finished" : next.exit_code === -1 ? "Job stopped" : "Job failed",
          description: next.label,
          type: ok ? "success" : next.exit_code === -1 ? "warning" : "error",
        });
      }
      timer.current = window.setTimeout(poll, next.running ? 1000 : 4000);
    } catch {
      timer.current = window.setTimeout(poll, 4000);
    }
  }, []);

  React.useEffect(() => {
    if (!enabled) return;
    poll();
    return () => window.clearTimeout(timer.current);
  }, [poll, enabled]);

  const start = React.useCallback(
    async (commands: string[], args: JobArgs = {}): Promise<boolean> => {
      if (commands.some((c) => GOVOICE_STEPS.has(c))) {
        // Check the GoVoice session first; if it's expired, ask to log in and start the job afterwards.
        if (!(await govoiceRef.current.ensureConnected(() => startRef.current(commands, args)))) return false;
      }
      try {
        const res = await api<{ label?: string }>("/api/jobs", { method: "POST", body: { commands, args } });
        lastJob.current = { args, commands, label: res?.label ?? "" };
        toastManager.add({
          title: "Job started",
          description: commands.map((c) => STEP_LABELS[c] ?? c).join(" → "),
          type: "info",
        });
        poll();
        return true;
      } catch (err) {
        toastManager.add({ title: "Couldn't start the job", description: (err as Error).message, type: "error" });
        return false;
      }
    },
    [poll],
  );
  React.useEffect(() => {
    startRef.current = start;
  }, [start]);

  const stop = React.useCallback(async () => {
    await api("/api/jobs/stop", { method: "POST" });
    toastManager.add({ title: "Stopping job…", type: "warning" });
    poll();
  }, [poll]);

  const value = React.useMemo(
    () => ({ state, lines, finishedCount, start, stop }),
    [state, lines, finishedCount, start, stop],
  );
  return <JobContext.Provider value={value}>{children}</JobContext.Provider>;
}
