import { CircleCheckIcon, MonitorSmartphoneIcon, PlayIcon, SquareIcon, StethoscopeIcon } from "lucide-react";
import * as React from "react";
import { JobLog } from "@/components/job-log";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertAction, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { t, type TKey } from "@/lib/i18n";
import { STEP_LABELS, useJob } from "@/lib/jobs";
import { href } from "@/lib/router";
import { liveAgents, RUNS_ON_LABELS, STEP_NAMES, useWorkers, WORKER_STEPS } from "@/lib/workers";
import type { Stats } from "@/lib/types";

const STEPS: { description: TKey; key: string }[] = [
  { description: "pipeline.step.sync", key: "sync" },
  { description: "pipeline.step.download", key: "download" },
  { description: "pipeline.step.voice", key: "voice" },
  { description: "pipeline.step.transcribe", key: "transcribe" },
  { description: "pipeline.step.analyze", key: "analyze" },
  { description: "pipeline.step.report", key: "report" },
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

/** Says where transcription and analysis will run, when that isn't simply this server. */
function ProcessingNotice() {
  const { state } = useWorkers();
  if (!state) return null;
  const steps = WORKER_STEPS.filter((s) => state.runs_on[s] !== "host");
  if (!steps.length) return null;
  const online = liveAgents(state.workers).length;
  return (
    <Alert variant={online ? "info" : "warning"}>
      <MonitorSmartphoneIcon aria-hidden="true" />
      <AlertTitle>
        {steps.map((s) => `${STEP_NAMES[s]}: ${RUNS_ON_LABELS[state.runs_on[s]].toLocaleLowerCase()}`).join(" · ")}
      </AlertTitle>
      <AlertDescription>
        {online
          ? t("pipeline.agentsOnline", { count: online })
          : steps.some((s) => state.runs_on[s] === "agent")
            ? t("pipeline.noAgentQueued")
            : t("pipeline.noAgentHost")}
      </AlertDescription>
      <AlertAction>
        <Button render={<a href={href("agents")} />} size="sm" variant="outline">
          {t("board.agents")}
        </Button>
      </AlertAction>
    </Alert>
  );
}

function JobResultBadge({ code }: { code: number }) {
  if (code === 0) return <Badge variant="success">{t("shell.job.succeeded")}</Badge>;
  if (code === -1) return <Badge variant="warning">{t("shell.job.stopped")}</Badge>;
  return <Badge variant="error">{t("shell.job.failed")}</Badge>;
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
  const agents = [
    { label: t("pipeline.allAgents"), value: "all" },
    ...(stats?.agents ?? []).map((a) => ({ label: t("shell.agentExt", { ext: a.agent }), value: a.agent })),
  ];

  const start = () => {
    const steps = STEPS.map((s) => s.key).filter((k) => form.steps.includes(k));
    if (!steps.length) {
      toastManager.add({ title: t("pipeline.pickStep"), type: "warning" });
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
            {t("pipeline.checkSetup")}
          </Button>
        }
        description={t("pipeline.description")}
        title={t("nav.pipeline")}
      />

      <ProcessingNotice />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("pipeline.steps")}</CardTitle>
          <CardDescription>{t("pipeline.stepsHint")}</CardDescription>
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
                    <span className="text-muted-foreground tabular-nums">{i + 1}.</span> {STEP_LABELS[step.key]}
                  </p>
                  <p className="font-normal text-muted-foreground text-xs">{t(step.description)}</p>
                </div>
              </Label>
            ))}
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field>
              <FieldLabel>{t("pipeline.fromDate")}</FieldLabel>
              <Input onChange={(e) => setForm({ since: e.target.value })} type="date" value={form.since} />
            </Field>
            <Field>
              <FieldLabel>{t("pipeline.untilDate")}</FieldLabel>
              <Input onChange={(e) => setForm({ until: e.target.value })} type="date" value={form.until} />
            </Field>
            <Field>
              <FieldLabel>{t("shell.agent")}</FieldLabel>
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
              label={t("pipeline.minLength")}
              min={0}
              onChange={(v) => setForm({ min_duration: v })}
              value={form.min_duration}
            />
            <NumberInput
              label={t("pipeline.maxCalls")}
              min={1}
              onChange={(v) => setForm({ limit: v })}
              placeholder={t("pipeline.all")}
              value={form.limit}
            />
            <NumberInput
              label={t("pipeline.workers")}
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
                {t("pipeline.redo")}
              </Label>
            </Field>
            <Field>
              <Label>
                <Switch checked={form.team_only} onCheckedChange={(team_only) => setForm({ team_only })} />
                {t("pipeline.teamOnly")}
              </Label>
              <FieldDescription className="ps-11">{t("pipeline.teamOnlyHint")}</FieldDescription>
            </Field>
          </div>
        </CardPanel>
        <CardFooter className="justify-end gap-2 border-t">
          {running && (
            <Button onClick={job.stop} variant="destructive-outline">
              <SquareIcon aria-hidden="true" />
              {t("shell.job.stop")}
            </Button>
          )}
          <Button disabled={running} onClick={start}>
            <PlayIcon aria-hidden="true" className="rtl:-scale-x-100" />
            {t("pipeline.startJob")}
          </Button>
        </CardFooter>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            {running ? <Spinner className="size-4" /> : state?.started_at && <CircleCheckIcon aria-hidden="true" className="size-4 text-muted-foreground" />}
            {state?.label ? state.label : t("pipeline.log")}
          </CardTitle>
          <CardDescription>
            {running
              ? t("shell.job.runningSince", { time: fmtDateTime(state?.started_at) })
              : state?.finished_at
                ? t("shell.job.finishedAgo", { time: fmtRelative(state.finished_at) })
                : t("shell.job.empty")}
          </CardDescription>
        </CardHeader>
        <CardPanel>
          <JobLog lines={job.lines} />
        </CardPanel>
      </Card>

      {!!state?.history.length && (
        <CardFrame>
          <CardFrameHeader>
            <CardFrameTitle>{t("pipeline.recentJobs")}</CardFrameTitle>
          </CardFrameHeader>
          <Table variant="card">
            <TableHeader>
              <TableRow>
                <TableHead>{t("pipeline.job")}</TableHead>
                <TableHead>{t("pipeline.started")}</TableHead>
                <TableHead>{t("pipeline.finished")}</TableHead>
                <TableHead>{t("pipeline.result")}</TableHead>
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
