import { CircleCheckIcon, PlayIcon, SquareIcon, StethoscopeIcon } from "lucide-react";
import * as React from "react";
import { JobLog } from "@/components/job-log";
import { PageHeader } from "@/components/page-header";
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
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  NumberField,
  NumberFieldDecrement,
  NumberFieldGroup,
  NumberFieldIncrement,
  NumberFieldInput,
} from "@/components/ui/number-field";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toastManager } from "@/components/ui/toast";
import { useApi } from "@/lib/api";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { useJob } from "@/lib/jobs";
import type { Stats } from "@/lib/types";

const STEPS = [
  { description: "Fetch the list of recordings from GoVoice", key: "sync", label: "Sync" },
  { description: "Download the mp3 files", key: "download", label: "Download" },
  { description: "Speech-to-text (local Whisper by default)", key: "transcribe", label: "Transcribe" },
  { description: "Per-call feedback from Claude or Cursor", key: "analyze", label: "Analyze" },
  { description: "Coaching reports for the team and each agent", key: "report", label: "Report" },
];

type Form = {
  steps: string[];
  since: string;
  until: string;
  agent: string;
  min_duration: number | null;
  limit: number | null;
  workers: number | null;
  redo: boolean;
  team_only: boolean;
};

// Kept across page visits.
let savedForm: Form = {
  agent: "",
  limit: null,
  min_duration: 30,
  redo: false,
  since: "",
  steps: STEPS.map((s) => s.key),
  team_only: false,
  until: "",
  workers: 4,
};

function NumberInput({
  label,
  value,
  onChange,
  min,
  max,
  placeholder,
}: {
  label: string;
  value: number | null;
  onChange: (v: number | null) => void;
  min?: number;
  max?: number;
  placeholder?: string;
}) {
  return (
    <Field>
      <FieldLabel>{label}</FieldLabel>
      <NumberField max={max} min={min} onValueChange={onChange} value={value}>
        <NumberFieldGroup>
          <NumberFieldDecrement />
          <NumberFieldInput placeholder={placeholder} />
          <NumberFieldIncrement />
        </NumberFieldGroup>
      </NumberField>
    </Field>
  );
}

function JobResultBadge({ code }: { code: number }) {
  if (code === 0) return <Badge variant="success">Succeeded</Badge>;
  if (code === -1) return <Badge variant="warning">Stopped</Badge>;
  return <Badge variant="error">Failed</Badge>;
}

export function PipelinePage(): React.ReactElement {
  const job = useJob();
  const { data: stats } = useApi<Stats>("/api/stats");
  const [form, setFormState] = React.useState<Form>(savedForm);
  const setForm = (patch: Partial<Form>) =>
    setFormState((f) => {
      savedForm = { ...f, ...patch };
      return savedForm;
    });

  const state = job.state;
  const running = !!state?.running;
  const agents = [{ label: "All agents", value: "all" }, ...(stats?.agents ?? []).map((a) => ({ label: `Agent ${a.agent}`, value: a.agent }))];

  const start = () => {
    const steps = STEPS.map((s) => s.key).filter((k) => form.steps.includes(k));
    if (!steps.length) {
      toastManager.add({ title: "Pick at least one step", type: "warning" });
      return;
    }
    const { steps: _, ...args } = form;
    job.start(steps, args);
  };

  return (
    <>
      <PageHeader
        actions={
          <Button disabled={running} onClick={() => job.start(["check"])} variant="outline">
            <StethoscopeIcon aria-hidden="true" />
            Check setup
          </Button>
        }
        description="Run any part of the pipeline with filters. One job runs at a time."
        title="Pipeline"
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Steps</CardTitle>
          <CardDescription>Each step only processes calls that still need it, unless “Redo” is on.</CardDescription>
        </CardHeader>
        <CardPanel className="flex flex-col gap-6">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {STEPS.map((step, i) => (
              <Label
                className="flex items-start gap-2.5 rounded-lg border p-3 hover:bg-accent/50 has-data-checked:border-primary/48 has-data-checked:bg-accent/50"
                key={step.key}
              >
                <Checkbox
                  checked={form.steps.includes(step.key)}
                  onCheckedChange={(on) =>
                    setForm({ steps: on ? [...form.steps, step.key] : form.steps.filter((s) => s !== step.key) })
                  }
                />
                <div className="flex flex-col gap-1">
                  <p>
                    <span className="text-muted-foreground tabular-nums">{i + 1}.</span> {step.label}
                  </p>
                  <p className="font-normal text-muted-foreground text-xs">{step.description}</p>
                </div>
              </Label>
            ))}
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field>
              <FieldLabel>From date</FieldLabel>
              <Input onChange={(e) => setForm({ since: e.target.value })} type="date" value={form.since} />
            </Field>
            <Field>
              <FieldLabel>Until date</FieldLabel>
              <Input onChange={(e) => setForm({ until: e.target.value })} type="date" value={form.until} />
            </Field>
            <Field>
              <FieldLabel>Agent</FieldLabel>
              <Select
                items={agents}
                onValueChange={(v) => setForm({ agent: v === "all" ? "" : (v as string) })}
                value={form.agent || "all"}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectPopup>
                  {agents.map((a) => (
                    <SelectItem key={a.value} value={a.value}>
                      {a.label}
                    </SelectItem>
                  ))}
                </SelectPopup>
              </Select>
            </Field>
            <NumberInput
              label="Minimum length (seconds)"
              min={0}
              onChange={(v) => setForm({ min_duration: v })}
              value={form.min_duration}
            />
            <NumberInput
              label="Max calls"
              min={1}
              onChange={(v) => setForm({ limit: v })}
              placeholder="All"
              value={form.limit}
            />
            <NumberInput
              label="Parallel workers"
              max={8}
              min={1}
              onChange={(v) => setForm({ workers: v })}
              value={form.workers}
            />
          </div>

          <div className="flex flex-col gap-3">
            <Field>
              <Label>
                <Switch checked={form.redo} onCheckedChange={(redo) => setForm({ redo })} />
                Redo calls that were already transcribed or analyzed
              </Label>
            </Field>
            <Field>
              <Label>
                <Switch checked={form.team_only} onCheckedChange={(team_only) => setForm({ team_only })} />
                Team report only
              </Label>
              <FieldDescription className="ps-11">Skip the per-agent reports in the Report step.</FieldDescription>
            </Field>
          </div>
        </CardPanel>
        <CardFooter className="justify-end gap-2 border-t">
          {running && (
            <Button onClick={job.stop} variant="destructive-outline">
              <SquareIcon aria-hidden="true" />
              Stop
            </Button>
          )}
          <Button disabled={running} onClick={start}>
            <PlayIcon aria-hidden="true" />
            Start job
          </Button>
        </CardFooter>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            {running ? <Spinner className="size-4" /> : state?.started_at && <CircleCheckIcon aria-hidden="true" className="size-4 text-muted-foreground" />}
            {state?.label ? state.label : "Log"}
          </CardTitle>
          <CardDescription>
            {running
              ? `Running since ${fmtDateTime(state?.started_at)}`
              : state?.finished_at
                ? `Finished ${fmtRelative(state.finished_at)}`
                : "Output of the current or last job appears here."}
          </CardDescription>
        </CardHeader>
        <CardPanel>
          <JobLog lines={job.lines} />
        </CardPanel>
      </Card>

      {!!state?.history.length && (
        <CardFrame>
          <CardFrameHeader>
            <CardFrameTitle>Recent jobs</CardFrameTitle>
          </CardFrameHeader>
          <Table variant="card">
            <TableHeader>
              <TableRow>
                <TableHead>Job</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Finished</TableHead>
                <TableHead>Result</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {state.history.map((h) => (
                <TableRow key={h.started_at}>
                  <TableCell className="max-w-md truncate font-medium">{h.label}</TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">{fmtDateTime(h.started_at)}</TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">{fmtDateTime(h.finished_at)}</TableCell>
                  <TableCell>
                    <JobResultBadge code={h.exit_code} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardFrame>
      )}
    </>
  );
}
