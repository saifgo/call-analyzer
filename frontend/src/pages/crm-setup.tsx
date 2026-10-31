import { ArrowDownIcon, ArrowUpIcon, CircleAlertIcon, DownloadIcon, LockIcon, PlusIcon, Trash2Icon, XIcon } from "lucide-react";
import * as React from "react";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardDescription, CardFooter, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { toastManager } from "@/components/ui/toast";
import { Tooltip, TooltipPopup, TooltipTrigger } from "@/components/ui/tooltip";
import { api, useApi } from "@/lib/api";
import { fmtRelative } from "@/lib/format";
import { joinList, t, type TKey } from "@/lib/i18n";
import { href } from "@/lib/router";
import type { CrmField, CrmFieldType, CrmImport, CrmSetup, CrmStage } from "@/lib/types";
import { ChoiceSelect } from "@/pages/contacts";

function move<T>(list: T[], i: number, by: number): T[] {
  const j = i + by;
  if (j < 0 || j >= list.length) return list;
  const next = [...list];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}

/** Up, down and remove; remove explains itself when it can't be used. */
function RowButtons({
  label,
  onMove,
  onRemove,
  cantRemove,
}: {
  label: string;
  onMove: (by: number) => void;
  onRemove: () => void;
  cantRemove?: string | null;
}) {
  const remove = (
    <Button aria-label={t("whatsapp.removeLabel", { label })} disabled={!!cantRemove} onClick={onRemove} size="icon-sm" variant="ghost">
      <Trash2Icon aria-hidden="true" />
    </Button>
  );
  return (
    <div className="flex shrink-0 items-center">
      <Button aria-label={t("campaigns.moveUp", { label })} onClick={() => onMove(-1)} size="icon-sm" variant="ghost">
        <ArrowUpIcon aria-hidden="true" />
      </Button>
      <Button aria-label={t("campaigns.moveDown", { label })} onClick={() => onMove(1)} size="icon-sm" variant="ghost">
        <ArrowDownIcon aria-hidden="true" />
      </Button>
      {cantRemove ? (
        <Tooltip>
          <TooltipTrigger render={<span />}>{remove}</TooltipTrigger>
          <TooltipPopup className="max-w-xs">{cantRemove}</TooltipPopup>
        </Tooltip>
      ) : (
        remove
      )}
    </div>
  );
}

/** Save / discard for an editor; the server's refusal shows above it. */
function SaveBar({ dirty, saving, error, onSave, onDiscard }: {
  dirty: boolean;
  saving: boolean;
  error: string | null;
  onSave: () => void;
  onDiscard: () => void;
}) {
  return (
    <CardFooter className="flex flex-col items-stretch gap-3">
      {error && (
        <Alert variant="error">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>{t("common.couldntSave")}</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="flex flex-wrap items-center justify-end gap-2">
        {dirty && <span className="me-auto text-muted-foreground text-sm">{t("common.unsavedChanges")}</span>}
        <Button disabled={!dirty || saving} onClick={onDiscard} variant="ghost">
          {t("common.discard")}
        </Button>
        <Button disabled={!dirty} loading={saving} onClick={onSave}>
          {t("common.save")}
        </Button>
      </div>
    </CardFooter>
  );
}

/** Runs a PUT that returns the whole setup, with the saving/error state an editor shows. */
function useSave(path: string, onSaved: (setup: CrmSetup) => void, done: TKey) {
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const save = async (body: unknown) => {
    setSaving(true);
    setError(null);
    try {
      onSaved(await api<CrmSetup>(path, { body, method: "PUT" }));
      toastManager.add({ title: t(done), type: "success" });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };
  return { error, save, saving, setError };
}

// --- Stages ----------------------------------------------------------------------------------------

type DraftStage = Pick<CrmStage, "label"> & Partial<Omit<CrmStage, "label">> & { id: string };
const draftStages = (stages: CrmStage[]): DraftStage[] => stages.map((s) => ({ ...s, id: s.value }));

function StagesEditor({ setup, onSaved }: { setup: CrmSetup; onSaved: (s: CrmSetup) => void }) {
  const [stages, setStages] = React.useState(() => draftStages(setup.stages));
  const { error, save, saving, setError } = useSave("/api/crm/stages", onSaved, "crm.stagesSaved");
  const dirty = JSON.stringify(stages.map((s) => [s.value, s.label])) !== JSON.stringify(setup.stages.map((s) => [s.value, s.label]));
  const set = (i: number, label: string) => setStages((list) => list.map((s, j) => (j === i ? { ...s, label } : s)));

  const cantRemove = (s: DraftStage) =>
    s.locked
      ? t("crm.stageLocked")
      : s.count
        ? t("crm.stageHasOpportunities", { count: s.count })
        : s.campaigns?.length
          ? t("crm.stageUsedBy", { campaigns: joinList(s.campaigns) })
          : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("crm.stagesTitle")}</CardTitle>
        <CardDescription>{t("crm.stagesHint")}</CardDescription>
      </CardHeader>
      <CardPanel className="flex flex-col gap-2">
        {stages.map((s, i) => (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border p-2" key={s.id}>
            <span className="w-6 text-center text-muted-foreground text-sm tabular-nums">{i + 1}</span>
            <Input
              aria-label={t("crm.stageName")}
              className="min-w-48 flex-1"
              dir="auto"
              onChange={(e) => set(i, e.target.value)}
              placeholder={t("crm.stagePlaceholder")}
              value={s.label}
            />
            {s.locked && (
              <Tooltip>
                <TooltipTrigger render={<span className="text-muted-foreground" />}>
                  <LockIcon aria-label={t("crm.locked")} className="size-4" />
                </TooltipTrigger>
                <TooltipPopup className="max-w-xs">{t("crm.stageLocked")}</TooltipPopup>
              </Tooltip>
            )}
            {s.value ? (
              <Badge render={<a href={href("contacts", null, { stage: s.value })} />} variant="secondary">
                {t("crm.nOpportunities", { count: s.count ?? 0 })}
              </Badge>
            ) : (
              <Badge variant="info">{t("crm.newStage")}</Badge>
            )}
            {!!s.campaigns?.length && (
              <Tooltip>
                <TooltipTrigger render={<Badge variant="outline" />}>{t("crm.nCampaigns", { count: s.campaigns.length })}</TooltipTrigger>
                <TooltipPopup className="max-w-xs">{joinList(s.campaigns)}</TooltipPopup>
              </Tooltip>
            )}
            <RowButtons
              cantRemove={cantRemove(s)}
              label={s.label || t("crm.stageFallback")}
              onMove={(by) => setStages((list) => move(list, i, by))}
              onRemove={() => setStages((list) => list.filter((_, j) => j !== i))}
            />
          </div>
        ))}
        <Button
          className="self-start"
          onClick={() => setStages((list) => [...list, { id: `new-${Date.now()}`, label: "" }])}
          size="sm"
          variant="outline"
        >
          <PlusIcon aria-hidden="true" />
          {t("crm.addStage")}
        </Button>
      </CardPanel>
      <SaveBar
        dirty={dirty}
        error={error}
        onDiscard={() => {
          setStages(draftStages(setup.stages));
          setError(null);
        }}
        onSave={() => save(stages.map((s) => ({ label: s.label.trim(), value: s.value ?? null })))}
        saving={saving}
      />
    </Card>
  );
}

// --- Fields ----------------------------------------------------------------------------------------

type DraftField = {
  id: string;
  key: string | null;
  label: string;
  type: CrmFieldType;
  options: [string, string][];
  campaigns: string[];
};
const draftFields = (fields: CrmField[]): DraftField[] =>
  fields.map((f) => ({ ...f, id: f.key, key: f.key, options: f.options ?? [] }));
const comparable = (fields: { key: string | null; label: string; type: string; options: [string, string][] | null }[]) =>
  JSON.stringify(fields.map((f) => [f.key, f.label, f.type, f.type === "choice" ? (f.options ?? []) : null]));

const TYPES: { label: TKey; value: CrmFieldType }[] = [
  { label: "crm.type.text", value: "text" },
  { label: "crm.type.number", value: "number" },
  { label: "crm.type.boolean", value: "boolean" },
  { label: "crm.type.choice", value: "choice" },
];

function ChoicesInput({ options, onChange }: { options: [string, string][]; onChange: (o: [string, string][]) => void }) {
  return (
    <div className="flex basis-full flex-col gap-2 ps-8">
      {options.map(([value, label], i) => (
        <div className="flex gap-2" key={value || `new-${i}`}>
          <Input
            aria-label={t("crm.choiceN", { n: i + 1 })}
            dir="auto"
            onChange={(e) => onChange(options.map((o, j) => (j === i ? [o[0], e.target.value] : o)))}
            placeholder={t("crm.choicePlaceholder")}
            size="sm"
            value={label}
          />
          <Button aria-label={t("whatsapp.removeLabel", { label: label || i + 1 })} onClick={() => onChange(options.filter((_, j) => j !== i))} size="icon-sm" variant="ghost">
            <XIcon aria-hidden="true" />
          </Button>
        </div>
      ))}
      <Button className="self-start" onClick={() => onChange([...options, ["", ""]])} size="xs" variant="outline">
        <PlusIcon aria-hidden="true" />
        {t("crm.addChoice")}
      </Button>
    </div>
  );
}

function FieldsEditor({ setup, onSaved }: { setup: CrmSetup; onSaved: (s: CrmSetup) => void }) {
  const [fields, setFields] = React.useState(() => draftFields(setup.fields));
  const { error, save, saving, setError } = useSave("/api/crm/fields", onSaved, "crm.fieldsSaved");
  const dirty = comparable(fields) !== comparable(setup.fields);
  const set = (i: number, patch: Partial<DraftField>) => setFields((list) => list.map((f, j) => (j === i ? { ...f, ...patch } : f)));
  const typeItems = TYPES.map((ty) => ({ label: t(ty.label), value: ty.value }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("crm.fieldsTitle")}</CardTitle>
        <CardDescription>{t("crm.fieldsHint")}</CardDescription>
        <CardAction>
          <Button
            onClick={() => setFields((list) => [...list, { campaigns: [], id: `new-${Date.now()}`, key: null, label: "", options: [], type: "text" }])}
            size="sm"
            variant="outline"
          >
            <PlusIcon aria-hidden="true" />
            {t("crm.addField")}
          </Button>
        </CardAction>
      </CardHeader>
      <CardPanel className="flex flex-col gap-2">
        <p className="text-muted-foreground text-xs">{t("crm.builtinFields")}</p>
        {fields.length === 0 && <p className="text-muted-foreground text-sm">{t("crm.noFields")}</p>}
        {fields.map((f, i) => (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border p-2" key={f.id}>
            <span className="w-6 text-center text-muted-foreground text-sm tabular-nums">{i + 1}</span>
            <Input
              aria-label={t("crm.fieldName")}
              className="min-w-48 flex-1"
              dir="auto"
              onChange={(e) => set(i, { label: e.target.value })}
              placeholder={t("crm.fieldPlaceholder")}
              value={f.label}
            />
            <ChoiceSelect
              className="w-36"
              items={typeItems}
              label={t("crm.fieldType")}
              onChange={(v) => set(i, { options: v === "choice" && !f.options.length ? [["", ""]] : f.options, type: v as CrmFieldType })}
              value={f.type}
            />
            {f.key ? (
              <Badge className="font-mono" variant="outline">
                {f.key}
              </Badge>
            ) : (
              <Badge variant="info">{t("crm.newField")}</Badge>
            )}
            {f.campaigns.length > 0 && (
              <Tooltip>
                <TooltipTrigger render={<Badge variant="outline" />}>{t("crm.nCampaigns", { count: f.campaigns.length })}</TooltipTrigger>
                <TooltipPopup className="max-w-xs">{t("crm.fieldFilledBy", { campaigns: joinList(f.campaigns) })}</TooltipPopup>
              </Tooltip>
            )}
            <RowButtons
              cantRemove={f.campaigns.length ? t("crm.fieldFilledBy", { campaigns: joinList(f.campaigns) }) : null}
              label={f.label || t("crm.fieldFallback")}
              onMove={(by) => setFields((list) => move(list, i, by))}
              onRemove={() => setFields((list) => list.filter((_, j) => j !== i))}
            />
            {f.type === "choice" && <ChoicesInput onChange={(options) => set(i, { options })} options={f.options} />}
          </div>
        ))}
      </CardPanel>
      <SaveBar
        dirty={dirty}
        error={error}
        onDiscard={() => {
          setFields(draftFields(setup.fields));
          setError(null);
        }}
        onSave={() =>
          save(
            fields.map((f) => ({
              key: f.key,
              label: f.label.trim(),
              options: f.type === "choice" ? f.options.filter(([, label]) => label.trim()) : null,
              type: f.type,
            })),
          )
        }
        saving={saving}
      />
    </Card>
  );
}

// --- Import from Twenty ----------------------------------------------------------------------------

const IMPORT_POLL_MS = 1500;
const IMPORTED = ["people", "opportunities", "notes"] as const;

function ImportCounts({ counts }: { counts: Record<string, number> }) {
  const parts = (what: (typeof IMPORTED)[number]) =>
    (
      [
        ["added", "crm.importAdded"],
        ["updated", "crm.importUpdated"],
        ["unchanged", "crm.importUnchanged"],
        ["skipped", "crm.importSkipped"],
      ] as const
    )
      .filter(([kind]) => counts[`${what}_${kind}`])
      .map(([kind, key]) => t(key, { count: counts[`${what}_${kind}`] }));
  const extras = [
    counts.stages && t("crm.importStagesAdded", { count: counts.stages }),
    counts.fields && t("crm.importFieldsAdded", { count: counts.fields }),
    counts.values_skipped && t("crm.importValuesSkipped", { count: counts.values_skipped }),
  ].filter(Boolean);
  return (
    <div className="flex flex-col gap-2">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        {IMPORTED.map((what) => (
          <React.Fragment key={what}>
            <dt className="text-muted-foreground">{t(`crm.importStep.${what}`)}</dt>
            <dd className="tabular-nums">{parts(what).join(" · ") || t("crm.none")}</dd>
          </React.Fragment>
        ))}
      </dl>
      {extras.length > 0 && <p className="text-muted-foreground text-xs">{extras.join(" · ")}</p>}
    </div>
  );
}

/** Copies Twenty's records into the built-in CRM, whichever CRM is in use, and shows how far it got. */
function TwentyImportCard({ local, onImported }: { local: boolean; onImported: () => void }) {
  const { data, error, setData } = useApi<CrmImport>("/api/crm/import");
  const [starting, setStarting] = React.useState(false);
  const [startError, setStartError] = React.useState<string | null>(null);
  const running = !!data?.running;
  const wasRunning = React.useRef(running);

  React.useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      api<CrmImport>("/api/crm/import")
        .then(setData)
        .catch(() => {});
    }, IMPORT_POLL_MS);
    return () => window.clearInterval(timer);
  }, [running, setData]);

  React.useEffect(() => {
    if (wasRunning.current && !running) onImported();
    wasRunning.current = running;
  }, [running, onImported]);

  const start = async () => {
    setStarting(true);
    setStartError(null);
    try {
      setData(await api<CrmImport>("/api/crm/import", { method: "POST" }));
    } catch (err) {
      setStartError((err as Error).message);
    } finally {
      setStarting(false);
    }
  };

  const finished = !!data && !running && !!data.finished_at;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("crm.importTitle")}</CardTitle>
        <CardDescription>{t("crm.importHint")}</CardDescription>
        {data?.configured && (
          <CardAction>
            <Button disabled={running} loading={starting || running} onClick={start} size="sm" variant={finished ? "outline" : "default"}>
              <DownloadIcon aria-hidden="true" />
              {t(finished ? "crm.importAgain" : "crm.importStart")}
            </Button>
          </CardAction>
        )}
      </CardHeader>
      <CardPanel className="flex flex-col gap-3">
        {error && (
          <Alert variant="error">
            <CircleAlertIcon aria-hidden="true" />
            <AlertTitle>{t("crm.loadFailed")}</AlertTitle>
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        )}
        {!data ? (
          !error && <Skeleton className="h-16 rounded-lg" />
        ) : !data.configured ? (
          <Alert variant="info">
            <CircleAlertIcon aria-hidden="true" />
            <AlertDescription className="flex flex-wrap items-center gap-3">
              {t("crm.importNotConfigured")}
              <Button render={<a href={href("settings")} />} size="sm" variant="outline">
                {t("common.openSettings")}
              </Button>
            </AlertDescription>
          </Alert>
        ) : (
          <>
            <p className="text-muted-foreground text-xs" dir="ltr">
              {t("crm.importFrom", { url: data.base_url })}
            </p>
            {startError && (
              <Alert variant="error">
                <CircleAlertIcon aria-hidden="true" />
                <AlertTitle>{t("crm.importCouldntStart")}</AlertTitle>
                <AlertDescription>{startError}</AlertDescription>
              </Alert>
            )}
            {running && data.step && (
              <p className="flex items-center gap-2 text-sm">
                <Spinner />
                {t("crm.importRunning", { step: t(`crm.importStep.${data.step}`) })}
              </p>
            )}
            {finished && data.error && (
              <Alert variant="error">
                <CircleAlertIcon aria-hidden="true" />
                <AlertTitle>{t("crm.importFailed")}</AlertTitle>
                <AlertDescription>
                  {data.error} {t("crm.importFailedKept")}
                </AlertDescription>
              </Alert>
            )}
            {finished && !data.error && (
              <p className="text-success text-sm">{t("crm.importDone", { time: fmtRelative(data.finished_at) })}</p>
            )}
            {(running || finished) && <ImportCounts counts={data.counts} />}
            {!local && <p className="text-muted-foreground text-sm">{t("crm.importSwitchHint")}</p>}
          </>
        )}
      </CardPanel>
    </Card>
  );
}

/** The built-in CRM's pipeline stages and custom contact fields. */
export function CrmSetupPage(): React.ReactElement {
  const { data, error, reload, setData } = useApi<CrmSetup>("/api/crm/setup");
  return (
    <>
      <PageHeader description={t("crm.setupDescription")} title={t("nav.crmSetup")} />
      {error ? (
        <Alert variant="error">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>{t("crm.loadFailed")}</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      ) : !data ? (
        <div className="grid gap-6 xl:grid-cols-2">
          <Skeleton className="h-96 rounded-2xl" />
          <Skeleton className="h-96 rounded-2xl" />
        </div>
      ) : !data.local ? (
        <div className="flex flex-col gap-6">
          <Empty className="rounded-xl border md:py-16">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <LockIcon />
              </EmptyMedia>
              <EmptyTitle>{t("crm.notLocal", { crm: data.label })}</EmptyTitle>
              <EmptyDescription>{t("crm.notLocalHint")}</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button render={<a href={href("settings")} />} variant="outline">
                {t("common.openSettings")}
              </Button>
            </EmptyContent>
          </Empty>
          <TwentyImportCard local={false} onImported={reload} />
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          <TwentyImportCard local onImported={reload} />
          <div className="grid items-start gap-6 xl:grid-cols-2">
            {/* Each editor starts over from what was saved when its own part changes, and keeps its draft otherwise. */}
            <StagesEditor key={JSON.stringify(data.stages)} onSaved={setData} setup={data} />
            <FieldsEditor key={JSON.stringify(data.fields)} onSaved={setData} setup={data} />
          </div>
        </div>
      )}
    </>
  );
}
