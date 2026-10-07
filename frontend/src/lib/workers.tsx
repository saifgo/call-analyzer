// Remote agents (PCs that do the transcription / analysis for this server), polled so the sidebar, the header,
// Settings and the Agents page all show the same live state.
import * as React from "react";
import { api } from "@/lib/api";
import type { RunsOn, Worker, WorkersState, WorkerStep } from "@/lib/types";

type WorkersContextValue = {
  state: WorkersState | null;
  reload: () => Promise<void>;
};

const WorkersContext = React.createContext<WorkersContextValue | null>(null);

export function useWorkers(): WorkersContextValue {
  const ctx = React.useContext(WorkersContext);
  if (!ctx) throw new Error("useWorkers must be used within WorkersProvider");
  return ctx;
}

const POLL_MS = 8000;

/** `enabled={false}` for agent (sales) accounts: they can't see the remote agents. */
export function WorkersProvider({
  children,
  enabled = true,
}: {
  children: React.ReactNode;
  enabled?: boolean;
}): React.ReactElement {
  const [state, setState] = React.useState<WorkersState | null>(null);
  const timer = React.useRef<number | undefined>(undefined);

  const reload = React.useCallback(async () => {
    window.clearTimeout(timer.current);
    try {
      setState(await api<WorkersState>("/api/workers"));
    } catch {
      // keep the last state; the next poll retries
    }
    timer.current = window.setTimeout(reload, POLL_MS);
  }, []);

  React.useEffect(() => {
    if (!enabled) return;
    reload();
    return () => window.clearTimeout(timer.current);
  }, [reload, enabled]);

  const value = React.useMemo(() => ({ reload, state }), [reload, state]);
  return <WorkersContext.Provider value={value}>{children}</WorkersContext.Provider>;
}

/** The steps that can run on remote agents, in pipeline order. */
export const WORKER_STEPS: WorkerStep[] = ["transcribe", "voice", "analyze"];

export const STEP_NAMES: Record<WorkerStep, string> = {
  analyze: "Analysis",
  transcribe: "Transcription",
  voice: "Voice analysis",
};

export const RUNS_ON_LABELS: Record<RunsOn, string> = {
  agent: "Remote agents only",
  auto: "Agents when online, else this server",
  host: "This server",
};

/** Agents that are connected, enabled and set up for `step`. */
export function liveAgents(workers: Worker[], step?: WorkerStep): Worker[] {
  return workers.filter((w) => w.enabled && w.online && (!step || w.ready[step]));
}

/** Steps set to "agent" while no agent can do them: their calls wait in the queue. */
export function stalledSteps(state: WorkersState | null): WorkerStep[] {
  if (!state) return [];
  return WORKER_STEPS.filter(
    (step) => state.runs_on[step] === "agent" && liveAgents(state.workers, step).length === 0,
  );
}
