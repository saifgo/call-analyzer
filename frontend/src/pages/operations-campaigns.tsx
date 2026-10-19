import { ArchiveIcon, ArrowDownIcon, ArrowLeftIcon, ArrowUpIcon, CheckIcon, CircleAlertIcon, CopyIcon, LanguagesIcon, PencilIcon, PhoneIncomingIcon, PlusIcon, Trash2Icon, XIcon } from "lucide-react";
import * as React from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { toastManager } from "@/components/ui/toast";
import { Toggle } from "@/components/ui/toggle";
import { api, useApi } from "@/lib/api";
import { dateTimeFormat, humanize } from "@/lib/format";
import { builtInText, CAMPAIGN_LANGS, type CampaignLang, campaignText } from "@/lib/campaign-text";
import { LOCALES, t, type TKey, tx } from "@/lib/i18n";
import { STAGE_VARIANT } from "@/lib/operations";
import type { OpCampaign, OpConfig, OpOutcome, OpQuestion, OpQuestionTr, OpQuestionType, OpStage } from "@/lib/types";

type Draft = Omit<OpCampaign, "id" | "position" | "hours" | "questions"> & { id: number | null; questions: DraftQuestion[] };
/** A question being edited: `saved` keys are kept (answers are stored under them), new ones follow the label.
 * Choices work the same way: the values in `savedOptions` are kept, new ones follow their label. */
type DraftQuestion = OpQuestion & { saved: boolean; savedOptions?: string[] };

const TYPE_LABELS: { value: OpQuestionType; label: TKey }[] = [
  { label: "campaigns.type.select", value: "select" },
  { label: "campaigns.type.multi", value: "multi" },
  { label: "campaigns.type.boolean", value: "boolean" },
  { label: "campaigns.type.number", value: "number" },
  { label: "campaigns.type.text", value: "text" },
  { label: "campaigns.type.textarea", value: "textarea" },
];
const weekdayFmt = dateTimeFormat({ weekday: "short" });
/** Monday to Sunday in the interface language (1 January 2024 was a Monday). */
const days = () => Array.from({ length: 7 }, (_, i) => weekdayFmt().format(new Date(2024, 0, 1 + i)));
const NONE = "__none";

/** The key the server makes from a label (campaigns.slug). */
function slug(text: string, fallback: string): string {
  let value = text.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40).replace(/_+$/, "");
  if (value && !/^[a-z]/.test(value)) value = `q_${value}`.slice(0, 40);
  return value || fallback;
}

function move<T>(list: T[], i: number, by: number): T[] {
  const j = i + by;
  if (j < 0 || j >= list.length) return list;
  const next = [...list];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}

/** A new choice's value, made from its label like the server does, and not already used by another choice. */
function choiceValue(label: string, i: number, options: [string, string][]): string {
  const taken = new Set(options.filter((_, j) => j !== i).map(([v]) => v));
  const base = slug(label, `o${i + 1}`);
  let value = base;
  for (let n = 2; taken.has(value); n++) value = `${base.slice(0, 36)}_${n}`;
  return value;
}

/** `tr` with `patch` applied to one language, empty texts removed (an empty field shows the default text). */
function patchTr<T extends object>(
  tr: Partial<Record<CampaignLang, T>> | undefined,
  lang: CampaignLang,
  patch: Partial<T>,
): Partial<Record<CampaignLang, T>> | undefined {
  const next: Record<string, unknown> = { ...tr?.[lang], ...patch };
  for (const [k, v] of Object.entries(next)) {
    if (v && typeof v === "object") {
      const kept = Object.fromEntries(Object.entries(v).filter(([, text]) => String(text).trim()));
      if (Object.keys(kept).length) next[k] = kept;
      else delete next[k];
    } else if (!String(v ?? "").trim()) delete next[k];
  }
  const all: Partial<Record<CampaignLang, T>> = { ...tr };
  if (Object.keys(next).length) all[lang] = next as T;
  else delete all[lang];
  return Object.keys(all).length ? all : undefined;
}

const langInfo = (lang: CampaignLang) => LOCALES.find((l) => l.value === lang) ?? { dir: "ltr" as const, label: lang };

/** The button opening a row's translations, with how many languages have one. */
function TranslationsToggle({ open, onToggle, count, label }: { open: boolean; onToggle: () => void; count: number; label: string }) {
  return (
    <Button
      aria-expanded={open}
      aria-label={t("campaigns.translateLabel", { label })}
      onClick={onToggle}
      size="xs"
      variant={open ? "secondary" : "ghost"}
    >
      <LanguagesIcon aria-hidden="true" />
      {t("campaigns.translations")}
      {count > 0 && <Badge variant="outline">{count}</Badge>}
    </Button>
  );
}

/** One input per text to translate, a column per language. The grey placeholder is what shows when it's left empty. */
function TranslationFields({
  rows,
  value,
  onChange,
}: {
  rows: { id: string; name: string; source: string }[];
  value: (lang: CampaignLang, id: string) => string;
  onChange: (lang: CampaignLang, id: string, text: string) => void;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-lg bg-muted/40 p-3">
      <p className="text-muted-foreground text-xs">{t("campaigns.translationsHint")}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {CAMPAIGN_LANGS.map((lang) => {
          const info = langInfo(lang);
          return (
            <div className="flex flex-col gap-1.5" dir={info.dir} key={lang} lang={lang}>
              <span className="font-medium text-xs">{info.label}</span>
              {rows.map((row) => (
                <Input
                  aria-label={`${row.name} · ${info.label}`}
                  key={row.id}
                  onChange={(e) => onChange(lang, row.id, e.target.value)}
                  placeholder={builtInText(row.source, lang) ?? row.source}
                  size="sm"
                  value={value(lang, row.id)}
                />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function toDraft(c: OpCampaign, copy = false): Draft {
  return {
    active: copy ? true : c.active,
    call_days: c.call_days,
    call_end: c.call_end,
    call_start: c.call_start,
    description: c.description,
    exhausted_stage: c.exhausted_stage,
    id: copy ? null : c.id,
    kind: copy ? "outbound" : c.kind,
    max_attempts: c.max_attempts,
    name: copy ? t("campaigns.copyName", { name: c.name }) : c.name,
    outcomes: c.outcomes.map((o) => ({ ...o })),
    questions: c.questions.map((q) => ({ ...q, saved: true, savedOptions: q.options?.map(([v]) => v) })),
    retry_minutes: c.retry_minutes,
    stages: [...c.stages],
  };
}

function StageSelect({ stages, value, onChange, placeholder }: { stages: OpStage[]; value: string | null; onChange: (v: string | null) => void; placeholder: string }) {
  const items = [{ label: placeholder, value: NONE }, ...stages.map((s) => ({ label: s.label, value: s.value }))];
  return (
    <Select items={items} onValueChange={(v) => onChange(v === NONE || !v ? null : String(v))} value={value ?? NONE}>
      <SelectTrigger size="sm">
        <SelectValue />
      </SelectTrigger>
      <SelectPopup>
        {items.map((item) => (
          <SelectItem key={item.value} value={item.value}>
            {item.label}
          </SelectItem>
        ))}
      </SelectPopup>
    </Select>
  );
}

function Chip({ pressed, onPressedChange, children }: { pressed: boolean; onPressedChange: (on: boolean) => void; children: React.ReactNode }) {
  return (
    <Toggle
      className="data-pressed:border-primary data-pressed:bg-primary/8 data-pressed:text-foreground dark:data-pressed:bg-primary/16"
      onPressedChange={onPressedChange}
      pressed={pressed}
      size="sm"
      variant="outline"
    >
      {pressed && <CheckIcon aria-hidden="true" />}
      {children}
    </Toggle>
  );
}

function RowButtons({ onUp, onDown, onRemove, label }: { onUp: () => void; onDown: () => void; onRemove: () => void; label: string }) {
  return (
    <div className="flex shrink-0 items-center">
      <Button aria-label={t("campaigns.moveUp", { label })} onClick={onUp} size="icon-sm" variant="ghost">
        <ArrowUpIcon aria-hidden="true" />
      </Button>
      <Button aria-label={t("campaigns.moveDown", { label })} onClick={onDown} size="icon-sm" variant="ghost">
        <ArrowDownIcon aria-hidden="true" />
      </Button>
      <Button aria-label={t("whatsapp.removeLabel", { label })} onClick={onRemove} size="icon-sm" variant="ghost">
        <Trash2Icon aria-hidden="true" />
      </Button>
    </div>
  );
}

// --- Outcomes --------------------------------------------------------------------------------------

function OutcomesEditor({ outcomes, stages, onChange }: { outcomes: OpOutcome[]; stages: OpStage[]; onChange: (o: OpOutcome[]) => void }) {
  const set = (i: number, patch: Partial<OpOutcome>) => onChange(outcomes.map((o, j) => (j === i ? { ...o, ...patch } : o)));
  const [translating, setTranslating] = React.useState<number | null>(null);
  const reorder = (next: OpOutcome[]) => {
    setTranslating(null);
    onChange(next);
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("campaigns.outcomesTitle")}</CardTitle>
        <CardDescription>
          {tx("campaigns.outcomesHint", {
            callback: <b>{t("campaigns.callback")}</b>,
            reached: <b>{t("ops.metric.reached")}</b>,
            win: <b>{t("campaigns.win")}</b>,
          })}
        </CardDescription>
      </CardHeader>
      <CardPanel className="flex flex-col gap-2">
        {outcomes.map((o, i) => (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border p-2" key={o.value || `new-${i}`}>
            <Input
              aria-label={t("campaigns.outcomeName")}
              className="min-w-48 flex-1"
              onChange={(e) => set(i, { label: e.target.value })}
              placeholder={t("campaigns.outcomePlaceholder")}
              value={o.label}
            />
            <div className="w-44">
              <StageSelect onChange={(stage) => set(i, { stage })} placeholder={t("campaigns.keepStage")} stages={stages} value={o.stage} />
            </div>
            <Label className="flex items-center gap-1.5 font-normal text-sm">
              <Checkbox checked={!!o.reached} onCheckedChange={(on) => set(i, { reached: !!on, success: on ? o.success : false })} />
              {t("ops.metric.reached")}
            </Label>
            <Label className="flex items-center gap-1.5 font-normal text-sm">
              <Checkbox checked={!!o.success} disabled={!o.reached} onCheckedChange={(on) => set(i, { success: !!on })} />
              {t("campaigns.win")}
            </Label>
            <Label className="flex items-center gap-1.5 font-normal text-sm">
              <Checkbox checked={!!o.callback} onCheckedChange={(on) => set(i, { callback: !!on })} />
              {t("campaigns.callback")}
            </Label>
            <TranslationsToggle
              count={Object.keys(o.tr ?? {}).length}
              label={o.label || t("campaigns.outcomeFallback")}
              onToggle={() => setTranslating(translating === i ? null : i)}
              open={translating === i}
            />
            <RowButtons
              label={o.label || t("campaigns.outcomeFallback")}
              onDown={() => reorder(move(outcomes, i, 1))}
              onRemove={() => reorder(outcomes.filter((_, j) => j !== i))}
              onUp={() => reorder(move(outcomes, i, -1))}
            />
            {translating === i && (
              <div className="basis-full">
                <TranslationFields
                  onChange={(lang, _id, text) => set(i, { tr: patchTr(o.tr, lang, { label: text }) })}
                  rows={[{ id: "label", name: t("campaigns.outcomeName"), source: o.label }]}
                  value={(lang) => o.tr?.[lang]?.label ?? ""}
                />
              </div>
            )}
          </div>
        ))}
        <Button
          className="self-start"
          onClick={() => onChange([...outcomes, { callback: false, label: "", reached: true, stage: null, success: false, value: "" }])}
          size="sm"
          variant="outline"
        >
          <PlusIcon aria-hidden="true" />
          {t("campaigns.addOutcome")}
        </Button>
      </CardPanel>
    </Card>
  );
}

// --- Questions -------------------------------------------------------------------------------------

function QuestionEditor({
  q,
  index,
  earlier,
  onChange,
  onMove,
  onRemove,
}: {
  q: DraftQuestion;
  index: number;
  earlier: DraftQuestion[];
  onChange: (q: DraftQuestion) => void;
  onMove: (by: number) => void;
  onRemove: () => void;
}) {
  const set = (patch: Partial<DraftQuestion>) => onChange({ ...q, ...patch });
  const choices = q.type === "select" || q.type === "multi";
  const [translating, setTranslating] = React.useState(false);
  const options = q.options ?? [];
  // A new choice's value follows its label: its translations move with it.
  const setChoice = (i: number, label: string) => {
    const old = options[i][0];
    const value = q.savedOptions?.includes(old) ? old : choiceValue(label, i, options);
    let tr = q.tr;
    if (old && value !== old && tr) {
      tr = { ...tr };
      for (const lang of CAMPAIGN_LANGS) {
        const opts = tr[lang]?.options;
        if (opts?.[old] !== undefined) {
          const { [old]: moved, ...rest } = opts;
          tr[lang] = { ...tr[lang], options: { ...rest, [value]: moved } };
        }
      }
    }
    set({ options: options.map((o, j) => (j === i ? [value, label] : o)), tr });
  };
  const trRows = [
    { id: "label", name: t("campaigns.question"), source: q.label },
    { id: "section", name: t("campaigns.section"), source: q.section },
    ...(q.help ? [{ id: "help", name: t("campaigns.helpText"), source: q.help }] : []),
    ...(q.type === "number" && q.unit ? [{ id: "unit", name: t("campaigns.unit"), source: q.unit }] : []),
    ...(choices
      ? options.filter(([v, label]) => v && label).map(([v, label]) => ({ id: `option:${v}`, name: t("campaigns.choice"), source: label }))
      : []),
  ];
  const trValue = (lang: CampaignLang, id: string) => {
    const tr = q.tr?.[lang];
    return (id.startsWith("option:") ? tr?.options?.[id.slice(7)] : tr?.[id as Exclude<keyof OpQuestionTr, "options">]) ?? "";
  };
  const setTr = (lang: CampaignLang, id: string, text: string) =>
    set({
      tr: patchTr<OpQuestionTr>(
        q.tr,
        lang,
        id.startsWith("option:") ? { options: { ...q.tr?.[lang]?.options, [id.slice(7)]: text } } : { [id]: text },
      ),
    });
  // Conditions can only use questions above that are saved (their keys and choices are final).
  const parents = earlier.filter((p) => p.saved && (p.type === "select" || p.type === "multi" || p.type === "boolean"));
  const [parentKey, parentValues] = Object.entries(q.show_if ?? {})[0] ?? [null, []];
  const parent = parents.find((p) => p.key === parentKey);
  const parentOptions: [string, string][] = parent
    ? parent.type === "boolean"
      ? [["true", t("common.yes")], ["false", t("common.no")]]
      : (parent.options ?? []).filter(([v]) => v)
    : [];
  const parentItems = [
    { label: t("campaigns.alwaysAsked"), value: NONE },
    ...parents.map((p) => ({ label: t("campaigns.onlyWhen", { label: p.label }), value: p.key })),
  ];
  const types = TYPE_LABELS.map((type) => ({ label: t(type.label), value: type.value }));
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-6 text-muted-foreground text-xs tabular-nums">{index + 1}.</span>
        <Input
          aria-label={t("campaigns.question")}
          className="min-w-56 flex-1"
          onChange={(e) => set({ key: q.saved ? q.key : slug(e.target.value, `q${index + 1}`), label: e.target.value })}
          placeholder={t("campaigns.questionPlaceholder")}
          value={q.label}
        />
        <div className="w-44">
          <Select
            items={types}
            onValueChange={(v) => set({ options: v === "select" || v === "multi" ? (q.options ?? []) : undefined, type: v as OpQuestionType })}
            value={q.type}
          >
            <SelectTrigger size="sm">
              <SelectValue />
            </SelectTrigger>
            <SelectPopup>
              {types.map((type) => (
                <SelectItem key={type.value} value={type.value}>
                  {type.label}
                </SelectItem>
              ))}
            </SelectPopup>
          </Select>
        </div>
        <TranslationsToggle
          count={Object.keys(q.tr ?? {}).length}
          label={q.label || t("campaigns.questionFallback")}
          onToggle={() => setTranslating((on) => !on)}
          open={translating}
        />
        <RowButtons label={q.label || t("campaigns.questionFallback")} onDown={() => onMove(1)} onRemove={onRemove} onUp={() => onMove(-1)} />
      </div>

      {choices && (
        <div className="flex flex-col gap-1.5 ps-8">
          {(q.options ?? []).map(([value, label], i) => (
            <div className="flex items-center gap-1.5" key={value || `new-${i}`}>
              <Input
                aria-label={t("campaigns.choice")}
                className="max-w-sm"
                onChange={(e) => setChoice(i, e.target.value)}
                placeholder={t("campaigns.choicePlaceholder")}
                size="sm"
                value={label}
              />
              <Button aria-label={t("campaigns.removeChoice")} onClick={() => set({ options: (q.options ?? []).filter((_, j) => j !== i) })} size="icon-sm" variant="ghost">
                <XIcon aria-hidden="true" />
              </Button>
            </div>
          ))}
          <Button className="self-start" onClick={() => set({ options: [...(q.options ?? []), ["", ""]] })} size="xs" variant="ghost">
            <PlusIcon aria-hidden="true" />
            {t("campaigns.addChoice")}
          </Button>
        </div>
      )}

      <div className="grid gap-2 ps-8 sm:grid-cols-2 lg:grid-cols-4">
        <Input
          aria-label={t("campaigns.section")}
          onChange={(e) => set({ section: e.target.value })}
          placeholder={t("campaigns.section")}
          size="sm"
          value={q.section}
        />
        <Input
          aria-label={t("campaigns.helpText")}
          onChange={(e) => set({ help: e.target.value || undefined })}
          placeholder={t("campaigns.helpPlaceholder")}
          size="sm"
          value={q.help ?? ""}
        />
        {q.type === "number" && (
          <Input
            aria-label={t("campaigns.unit")}
            onChange={(e) => set({ unit: e.target.value || undefined })}
            placeholder={t("campaigns.unitPlaceholder")}
            size="sm"
            value={q.unit ?? ""}
          />
        )}
        <Input
          aria-label={t("campaigns.crmField")}
          dir="ltr"
          onChange={(e) => set({ crm: e.target.value.trim() || undefined })}
          placeholder={t("campaigns.crmFieldPlaceholder")}
          size="sm"
          value={q.crm ?? ""}
        />
      </div>

      {parents.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 ps-8">
          <div className="w-72">
            <Select
              items={parentItems}
              onValueChange={(v) => set({ show_if: v === NONE || !v ? undefined : { [String(v)]: [] } })}
              value={parentKey ?? NONE}
            >
              <SelectTrigger size="sm">
                <SelectValue />
              </SelectTrigger>
              <SelectPopup>
                {parentItems.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectPopup>
            </Select>
          </div>
          {parent &&
            parentOptions.map(([value, label]) => (
              <Chip
                key={value}
                onPressedChange={(on) =>
                  set({ show_if: { [parent.key]: on ? [...parentValues, value] : parentValues.filter((v) => v !== value) } })
                }
                pressed={parentValues.includes(value)}
              >
                {label}
              </Chip>
            ))}
        </div>
      )}

      {translating && (
        <div className="ps-8">
          <TranslationFields onChange={setTr} rows={trRows} value={trValue} />
        </div>
      )}
    </div>
  );
}

function QuestionsEditor({ questions, onChange }: { questions: DraftQuestion[]; onChange: (q: DraftQuestion[]) => void }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("campaigns.questions")}</CardTitle>
        <CardDescription>{t("campaigns.questionsHint")}</CardDescription>
      </CardHeader>
      <CardPanel className="flex flex-col gap-2">
        {questions.length === 0 && <p className="text-muted-foreground text-sm">{t("campaigns.noQuestions")}</p>}
        {questions.map((q, i) => (
          <QuestionEditor
            earlier={questions.slice(0, i)}
            index={i}
            key={q.saved ? q.key : `new-${i}`}
            onChange={(next) => onChange(questions.map((x, j) => (j === i ? next : x)))}
            onMove={(by) => onChange(move(questions, i, by))}
            onRemove={() => onChange(questions.filter((_, j) => j !== i))}
            q={q}
          />
        ))}
        <Button
          className="self-start"
          onClick={() =>
            onChange([
              ...questions,
              { key: "", label: "", saved: false, section: questions.at(-1)?.section ?? t("campaigns.questions"), type: "text" },
            ])
          }
          size="sm"
          variant="outline"
        >
          <PlusIcon aria-hidden="true" />
          {t("campaigns.addQuestion")}
        </Button>
      </CardPanel>
    </Card>
  );
}

// --- The campaign ----------------------------------------------------------------------------------

function CampaignEditor({ initial, config, onDone }: { initial: Draft; config: OpConfig; onDone: () => void }) {
  const [draft, setDraft] = React.useState(initial);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const set = (patch: Partial<typeof draft>) => setDraft((d) => ({ ...d, ...patch }));
  const callDays = draft.call_days ?? [1, 2, 3, 4, 5, 6, 7];
  const inbound = draft.kind === "inbound";

  const save = async () => {
    setSaving(true);
    setError(null);
    const body = {
      ...draft,
      // New questions without a key yet get one made from their label by the server.
      questions: draft.questions.map(({ saved, ...q }) => ({ ...q, key: saved ? q.key : "", savedOptions: undefined })),
    };
    try {
      await api(draft.id === null ? "/api/operations/campaigns" : `/api/operations/campaigns/${draft.id}`, {
        body,
        method: draft.id === null ? "POST" : "PUT",
      });
      toastManager.add({ title: t("campaigns.saved"), type: "success" });
      onDone();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button onClick={onDone} size="sm" variant="ghost">
          <ArrowLeftIcon aria-hidden="true" className="rtl:rotate-180" />
          {t("desk.allCampaigns")}
        </Button>
        <Button loading={saving} onClick={save}>
          {t("campaigns.save")}
        </Button>
      </div>
      {error && (
        <Alert variant="error">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>{t("common.notSaved")}</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t("board.campaign")}</CardTitle>
        </CardHeader>
        <CardPanel className="grid gap-4 md:grid-cols-2">
          <Field>
            <FieldLabel>{t("campaigns.name")}</FieldLabel>
            <Input maxLength={80} onChange={(e) => set({ name: e.target.value })} value={draft.name} />
          </Field>
          {inbound ? (
            <p className="self-end text-muted-foreground text-sm">{t("inbound.campaignHint")}</p>
          ) : (
            <Label className="flex items-center gap-3 self-end font-medium">
              <Switch checked={draft.active} onCheckedChange={(on) => set({ active: on })} />
              {draft.active ? t("campaigns.running") : t("campaigns.paused")}
            </Label>
          )}
          <Field className="md:col-span-2">
            <FieldLabel>{t("campaigns.description")}</FieldLabel>
            <Textarea className="min-h-16" maxLength={500} onChange={(e) => set({ description: e.target.value })} value={draft.description ?? ""} />
          </Field>
          {!inbound && (
          <Field className="md:col-span-2">
            <FieldLabel>{t("campaigns.queue")}</FieldLabel>
            <div className="flex flex-wrap gap-1.5">
              {config.stages.map((s) => (
                <Chip
                  key={s.value}
                  onPressedChange={(on) => set({ stages: on ? [...draft.stages, s.value] : draft.stages.filter((v) => v !== s.value) })}
                  pressed={draft.stages.includes(s.value)}
                >
                  {s.label}
                </Chip>
              ))}
            </div>
            <FieldDescription>{t("campaigns.queueHint")}</FieldDescription>
          </Field>
          )}
        </CardPanel>
      </Card>

      {!inbound && (
      <Card>
        <CardHeader>
          <CardTitle>{t("campaigns.rules")}</CardTitle>
          <CardDescription>{t("campaigns.rulesHint")}</CardDescription>
        </CardHeader>
        <CardPanel className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Field>
            <FieldLabel>{t("campaigns.maxAttempts")}</FieldLabel>
            <Input
              min={0}
              max={50}
              onChange={(e) => set({ max_attempts: Number(e.target.value) || 0 })}
              type="number"
              value={draft.max_attempts}
            />
            <FieldDescription>{t("campaigns.maxAttemptsHint")}</FieldDescription>
          </Field>
          <Field>
            <FieldLabel>{t("campaigns.retryMinutes")}</FieldLabel>
            <Input min={0} onChange={(e) => set({ retry_minutes: Number(e.target.value) || 0 })} type="number" value={draft.retry_minutes} />
            <FieldDescription>{t("campaigns.retryHint")}</FieldDescription>
          </Field>
          <Field className="lg:col-span-2">
            <FieldLabel>{t("campaigns.exhaustedStage")}</FieldLabel>
            <StageSelect onChange={(exhausted_stage) => set({ exhausted_stage })} placeholder={t("campaigns.keepStage")} stages={config.stages} value={draft.exhausted_stage} />
          </Field>
          <Field>
            <FieldLabel>{t("campaigns.callingFrom")}</FieldLabel>
            <Input onChange={(e) => set({ call_start: e.target.value || null })} type="time" value={draft.call_start ?? ""} />
          </Field>
          <Field>
            <FieldLabel>{t("campaigns.until")}</FieldLabel>
            <Input onChange={(e) => set({ call_end: e.target.value || null })} type="time" value={draft.call_end ?? ""} />
            <FieldDescription>{t("campaigns.anyTime")}</FieldDescription>
          </Field>
          <Field className="lg:col-span-2">
            <FieldLabel>{t("campaigns.on")}</FieldLabel>
            <div className="flex flex-wrap gap-1.5">
              {days().map((label, i) => (
                <Chip
                  key={label}
                  onPressedChange={(on) => {
                    const next = on ? [...callDays, i + 1].sort() : callDays.filter((d) => d !== i + 1);
                    set({ call_days: next.length === 7 ? null : next });
                  }}
                  pressed={callDays.includes(i + 1)}
                >
                  {label}
                </Chip>
              ))}
            </div>
            <FieldDescription>{t("campaigns.callbacksAnyTime")}</FieldDescription>
          </Field>
        </CardPanel>
      </Card>
      )}

      <OutcomesEditor onChange={(outcomes) => set({ outcomes })} outcomes={draft.outcomes} stages={config.stages} />
      <QuestionsEditor onChange={(questions) => set({ questions })} questions={draft.questions} />

      <div className="flex justify-end">
        <Button loading={saving} onClick={save}>
          {t("campaigns.save")}
        </Button>
      </div>
    </div>
  );
}

/** Admins' list of call desk campaigns, and the editor. */
export function OperationsCampaigns(): React.ReactElement {
  const { data: config, error, reload } = useApi<OpConfig>("/api/operations/config");
  const [editing, setEditing] = React.useState<(Draft) | null>(null);

  if (error && !config) {
    return (
      <Alert variant="error">
        <CircleAlertIcon aria-hidden="true" />
        <AlertTitle>{t("campaigns.loadFailed")}</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  if (!config) return <Skeleton className="h-64 rounded-2xl" />;
  if (editing) {
    return (
      <CampaignEditor
        config={config}
        initial={editing}
        onDone={() => {
          setEditing(null);
          reload();
        }}
      />
    );
  }

  const stageLabel = (v: string) => config.stages.find((s) => s.value === v)?.label ?? humanize(v);
  const remove = async (c: OpCampaign) => {
    if (!window.confirm(t("campaigns.confirmRemove", { name: c.name }))) return;
    try {
      const res = await api<{ result: string }>(`/api/operations/campaigns/${c.id}`, { method: "DELETE" });
      toastManager.add({ title: res.result === "archived" ? t("campaigns.archived") : t("campaigns.deleted"), type: "success" });
      reload();
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: t("campaigns.removeFailed"), type: "error" });
    }
  };

  return (
    <>
      <div className="flex justify-end">
        <Button onClick={() => setEditing(toDraft(config.campaigns.find((c) => c.kind !== "inbound") ?? config.campaigns[0], true))}>
          <PlusIcon aria-hidden="true" />
          {t("campaigns.new")}
        </Button>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {config.campaigns.map((c) => (
          <Card className={c.active ? undefined : "opacity-70"} key={c.id}>
            <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-2">
              <div className="flex flex-col gap-1">
                <CardTitle className="flex items-center gap-2">
                  {campaignText(c.name)}
                  {c.kind === "inbound" && (
                    <Badge variant="success">
                      <PhoneIncomingIcon aria-hidden="true" />
                      {t("inbound.badge")}
                    </Badge>
                  )}
                  {!c.active && (
                    <Badge variant="secondary">
                      <ArchiveIcon aria-hidden="true" />
                      {t("ops.state.paused")}
                    </Badge>
                  )}
                </CardTitle>
                {c.description && <CardDescription>{campaignText(c.description)}</CardDescription>}
              </div>
              <div className="flex items-center gap-1">
                <Button onClick={() => setEditing(toDraft(c))} size="sm" variant="outline">
                  <PencilIcon aria-hidden="true" />
                  {t("common.edit")}
                </Button>
                {c.kind !== "inbound" && (
                  <>
                    <Button aria-label={t("campaigns.copy", { name: campaignText(c.name) })} onClick={() => setEditing(toDraft(c, true))} size="icon-sm" variant="ghost">
                      <CopyIcon aria-hidden="true" />
                    </Button>
                    <Button aria-label={t("whatsapp.removeLabel", { label: campaignText(c.name) })} onClick={() => remove(c)} size="icon-sm" variant="ghost">
                      <Trash2Icon aria-hidden="true" />
                    </Button>
                  </>
                )}
              </div>
            </CardHeader>
            <CardPanel className="flex flex-col gap-2 text-sm">
              {c.kind === "inbound" ? (
                <span className="text-muted-foreground">{t("inbound.campaignHint")}</span>
              ) : (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-muted-foreground">{t("campaigns.queueColon")}</span>
                {c.stages.map((s) => (
                  <Badge key={s} variant={STAGE_VARIANT[s] ?? "secondary"}>
                    {stageLabel(s)}
                  </Badge>
                ))}
              </div>
              )}
              <span className="text-muted-foreground">
                {t("campaigns.summary", {
                  hours: c.hours,
                  outcomes: c.outcomes.length,
                  questions: c.questions.length,
                  wins: c.outcomes.filter((o) => o.success).length,
                })}
                {c.max_attempts ? ` · ${t("campaigns.tries", { minutes: c.retry_minutes, tries: c.max_attempts })}` : ""}
              </span>
            </CardPanel>
          </Card>
        ))}
      </div>
    </>
  );
}
