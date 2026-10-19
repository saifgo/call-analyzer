import { ArrowDownIcon, ArrowUpIcon, CircleAlertIcon, PlusIcon, Trash2Icon } from "lucide-react";
import * as React from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardFrame, CardFrameHeader, CardFrameTitle, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toastManager } from "@/components/ui/toast";
import { labels, t } from "@/lib/i18n";
import { METRIC_LABELS } from "@/lib/operations";
import { api, useApi } from "@/lib/api";
import type { OpGoalMetric, OpTargets, OpTargetValues } from "@/lib/types";

const METRICS: OpGoalMetric[] = ["calls", "reached", "wins", "desk_minutes"];
const HINTS = labels<OpGoalMetric>({
  calls: "targets.hint.calls",
  desk_minutes: "targets.hint.deskMinutes",
  reached: "targets.hint.reached",
  wins: "targets.hint.wins",
});
const metricHeading = (m: OpGoalMetric) => (m === "desk_minutes" ? t("targets.deskHours") : METRIC_LABELS[m]);

/** Targets are edited as text: "" is no value (the team's, for an agent); desk time is typed in hours. */
type Values = Record<OpGoalMetric, string>;
type ReasonDraft = { id: number | null; label: string; limit_minutes: string; key: number };

function toText(metric: OpGoalMetric, value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  return metric === "desk_minutes" ? String(Math.round((value / 60) * 100) / 100) : String(value);
}

function fromText(metric: OpGoalMetric, text: string): number | null {
  if (text.trim() === "") return null;
  const n = Number(text.replace(",", "."));
  if (!Number.isFinite(n)) return Number.NaN;
  return metric === "desk_minutes" ? Math.round(n * 60) : Math.round(n);
}

function MetricInput({
  metric,
  value,
  placeholder,
  onChange,
}: {
  metric: OpGoalMetric;
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
}) {
  return (
    <Input
      aria-label={METRIC_LABELS[metric]}
      className="w-24"
      inputMode="decimal"
      min={0}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      size="sm"
      step={metric === "desk_minutes" ? 0.5 : 1}
      type="number"
      value={value}
    />
  );
}

let nextKey = 1;

export function OperationsTargets(): React.ReactElement {
  const { data, error, reload } = useApi<OpTargets>("/api/operations/targets");
  const [team, setTeam] = React.useState<Values | null>(null);
  const [agents, setAgents] = React.useState<Record<string, Values>>({});
  const [workday, setWorkday] = React.useState({ end: "17:00", start: "09:00" });
  const [reasons, setReasons] = React.useState<ReasonDraft[]>([]);
  const [saving, setSaving] = React.useState(false);
  const [saveError, setSaveError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!data) return;
    const values = (v: Partial<OpTargetValues> | undefined, zeroIsBlank: boolean): Values =>
      Object.fromEntries(
        METRICS.map((m) => [m, zeroIsBlank && !v?.[m] ? "" : toText(m, v?.[m])]),
      ) as Values;
    setTeam(values(data.team, true));
    setAgents(Object.fromEntries(data.users.map((u) => [u.username, values(data.agents[u.username], false)])));
    setWorkday(data.workday);
    setReasons(data.pause_reasons.map((r) => ({ id: r.id, key: nextKey++, label: r.label, limit_minutes: String(r.limit_minutes || "") })));
  }, [data]);

  if (error) {
    return (
      <Alert variant="error">
        <CircleAlertIcon aria-hidden="true" />
        <AlertTitle>{t("targets.loadFailed")}</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  if (!data || !team) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-40 rounded-2xl" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    );
  }

  const save = async () => {
    const parse = (v: Values, who: string) => {
      const out = {} as Record<OpGoalMetric, number | null>;
      for (const m of METRICS) {
        const n = fromText(m, v[m]);
        if (Number.isNaN(n) || (n !== null && n < 0)) throw new Error(t("targets.mustBePositive", { metric: METRIC_LABELS[m], who }));
        out[m] = n;
      }
      return out;
    };
    setSaveError(null);
    let body: unknown;
    try {
      body = {
        agents: Object.fromEntries(Object.entries(agents).map(([u, v]) => [u, parse(v, u)])),
        pause_reasons: reasons.map((r) => ({ id: r.id, label: r.label, limit_minutes: Number(r.limit_minutes) || 0 })),
        team: parse(team, t("targets.team")),
        workday,
      };
    } catch (err) {
      setSaveError((err as Error).message);
      return;
    }
    setSaving(true);
    try {
      await api("/api/operations/targets", { body, method: "PUT" });
      toastManager.add({ title: t("targets.saved"), type: "success" });
      reload();
    } catch (err) {
      setSaveError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const setReason = (key: number, patch: Partial<ReasonDraft>) =>
    setReasons((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const move = (index: number, by: number) =>
    setReasons((rs) => {
      const next = [...rs];
      const [item] = next.splice(index, 1);
      next.splice(index + by, 0, item);
      return next;
    });
  const agentUsers = data.users.filter((u) => u.role === "agent");
  const otherUsers = data.users.filter((u) => u.role !== "agent");

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button loading={saving} onClick={save}>
          {t("common.save")}
        </Button>
      </div>
      {saveError && (
        <Alert variant="error">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>{t("common.notSaved")}</AlertTitle>
          <AlertDescription>{saveError}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t("targets.teamTitle")}</CardTitle>
          <CardDescription>{t("targets.teamDescription")}</CardDescription>
        </CardHeader>
        <CardPanel className="grid gap-4 sm:grid-cols-2 lg:grid-cols-6">
          {METRICS.map((m) => (
            <Field key={m}>
              <FieldLabel>{metricHeading(m)}</FieldLabel>
              <MetricInput metric={m} onChange={(v) => setTeam({ ...team, [m]: v })} value={team[m]} />
              <FieldDescription>{HINTS[m]}</FieldDescription>
            </Field>
          ))}
          <Field>
            <FieldLabel>{t("targets.workdayStarts")}</FieldLabel>
            <Input onChange={(e) => setWorkday({ ...workday, start: e.target.value })} size="sm" type="time" value={workday.start} />
          </Field>
          <Field>
            <FieldLabel>{t("targets.workdayEnds")}</FieldLabel>
            <Input onChange={(e) => setWorkday({ ...workday, end: e.target.value })} size="sm" type="time" value={workday.end} />
            <FieldDescription>{t("targets.paceHint")}</FieldDescription>
          </Field>
        </CardPanel>
      </Card>

      <CardFrame>
        <CardFrameHeader>
          <CardFrameTitle>{t("targets.perAgent")}</CardFrameTitle>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead>{t("targets.account")}</TableHead>
              {METRICS.map((m) => (
                <TableHead key={m}>{metricHeading(m)}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {[...agentUsers, ...otherUsers].map((u) => (
              <TableRow key={u.username}>
                <TableCell>
                  <div className="flex flex-col">
                    <span className="font-medium">{u.name}</span>
                    <span className="text-muted-foreground text-xs">{u.role === "agent" ? u.username : `${u.username} · ${t("targets.adminTag")}`}</span>
                  </div>
                </TableCell>
                {METRICS.map((m) => (
                  <TableCell key={m}>
                    <MetricInput
                      metric={m}
                      onChange={(v) => setAgents((a) => ({ ...a, [u.username]: { ...a[u.username], [m]: v } }))}
                      placeholder={team[m] || "–"}
                      value={agents[u.username]?.[m] ?? ""}
                    />
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <p className="px-4 py-3 text-muted-foreground text-xs">{t("targets.perAgentHint")}</p>
      </CardFrame>

      <Card>
        <CardHeader>
          <CardTitle>{t("targets.pauseReasons")}</CardTitle>
          <CardDescription>{t("targets.pauseReasonsHint")}</CardDescription>
        </CardHeader>
        <CardPanel className="flex flex-col gap-2">
          {reasons.map((r, i) => (
            <div className="flex flex-wrap items-center gap-2" key={r.key}>
              <Input
                aria-label={t("targets.reason")}
                className="w-56"
                maxLength={40}
                onChange={(e) => setReason(r.key, { label: e.target.value })}
                placeholder={t("targets.reasonPlaceholder")}
                size="sm"
                value={r.label}
              />
              <Input
                aria-label={t("targets.limitMinutes")}
                className="w-28"
                min={0}
                onChange={(e) => setReason(r.key, { limit_minutes: e.target.value })}
                placeholder={t("targets.noLimit")}
                size="sm"
                type="number"
                value={r.limit_minutes}
              />
              <span className="text-muted-foreground text-xs">{t("targets.min")}</span>
              <Button aria-label={t("whatsapp.moveUp")} disabled={i === 0} onClick={() => move(i, -1)} size="icon-sm" variant="ghost">
                <ArrowUpIcon aria-hidden="true" />
              </Button>
              <Button aria-label={t("whatsapp.moveDown")} disabled={i === reasons.length - 1} onClick={() => move(i, 1)} size="icon-sm" variant="ghost">
                <ArrowDownIcon aria-hidden="true" />
              </Button>
              <Button
                aria-label={t("common.remove")}
                disabled={reasons.length === 1}
                onClick={() => setReasons((rs) => rs.filter((x) => x.key !== r.key))}
                size="icon-sm"
                variant="ghost"
              >
                <Trash2Icon aria-hidden="true" />
              </Button>
            </div>
          ))}
          <div>
            <Button
              onClick={() => setReasons((rs) => [...rs, { id: null, key: nextKey++, label: "", limit_minutes: "" } satisfies ReasonDraft])}
              size="sm"
              variant="outline"
            >
              <PlusIcon aria-hidden="true" />
              {t("targets.addReason")}
            </Button>
          </div>
        </CardPanel>
      </Card>
    </div>
  );
}
