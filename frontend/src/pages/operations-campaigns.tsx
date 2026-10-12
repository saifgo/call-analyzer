import { ArchiveIcon, ArrowDownIcon, ArrowLeftIcon, ArrowUpIcon, CheckIcon, CircleAlertIcon, CopyIcon, PencilIcon, PlusIcon, Trash2Icon, XIcon } from "lucide-react";
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
import { humanize } from "@/lib/format";
import { STAGE_VARIANT } from "@/lib/operations";
import type { OpCampaign, OpConfig, OpOutcome, OpQuestion, OpQuestionType, OpStage } from "@/lib/types";

type Draft = Omit<OpCampaign, "id" | "position" | "hours" | "questions"> & { id: number | null; questions: DraftQuestion[] };
/** A question being edited: `saved` keys are kept (answers are stored under them), new ones follow the label. */
type DraftQuestion = OpQuestion & { saved: boolean };

const TYPES: { value: OpQuestionType; label: string }[] = [
  { label: "One choice", value: "select" },
  { label: "Several choices", value: "multi" },
  { label: "Yes / no", value: "boolean" },
  { label: "Number", value: "number" },
  { label: "Short text", value: "text" },
  { label: "Long text", value: "textarea" },
];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
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

function toDraft(c: OpCampaign, copy = false): Draft {
  return {
    active: copy ? true : c.active,
    call_days: c.call_days,
    call_end: c.call_end,
    call_start: c.call_start,
    description: c.description,
    exhausted_stage: c.exhausted_stage,
    id: copy ? null : c.id,
    max_attempts: c.max_attempts,
    name: copy ? `${c.name} (copy)` : c.name,
    outcomes: c.outcomes.map((o) => ({ ...o })),
    questions: c.questions.map((q) => ({ ...q, saved: true })),
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
      <Button aria-label={`Move ${label} up`} onClick={onUp} size="icon-sm" variant="ghost">
        <ArrowUpIcon aria-hidden="true" />
      </Button>
      <Button aria-label={`Move ${label} down`} onClick={onDown} size="icon-sm" variant="ghost">
        <ArrowDownIcon aria-hidden="true" />
      </Button>
      <Button aria-label={`Remove ${label}`} onClick={onRemove} size="icon-sm" variant="ghost">
        <Trash2Icon aria-hidden="true" />
      </Button>
    </div>
  );
}

// --- Outcomes --------------------------------------------------------------------------------------

function OutcomesEditor({ outcomes, stages, onChange }: { outcomes: OpOutcome[]; stages: OpStage[]; onChange: (o: OpOutcome[]) => void }) {
  const set = (i: number, patch: Partial<OpOutcome>) => onChange(outcomes.map((o, j) => (j === i ? { ...o, ...patch } : o)));
  return (
    <Card>
      <CardHeader>
        <CardTitle>How a call can end</CardTitle>
        <CardDescription>
          The buttons agents close a call with. <b>Reached</b>: they spoke with the contact. <b>Win</b>: what the KPIs count as a
          conversion. <b>Callback</b>: booking one is suggested (for unanswered calls, at the campaign's retry time).
        </CardDescription>
      </CardHeader>
      <CardPanel className="flex flex-col gap-2">
        {outcomes.map((o, i) => (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border p-2" key={o.value || `new-${i}`}>
            <Input
              aria-label="Outcome name"
              className="min-w-48 flex-1"
              onChange={(e) => set(i, { label: e.target.value })}
              placeholder="e.g. Account created"
              value={o.label}
            />
            <div className="w-44">
              <StageSelect onChange={(stage) => set(i, { stage })} placeholder="Keep the stage" stages={stages} value={o.stage} />
            </div>
            <Label className="flex items-center gap-1.5 font-normal text-sm">
              <Checkbox checked={!!o.reached} onCheckedChange={(on) => set(i, { reached: !!on, success: on ? o.success : false })} />
              Reached
            </Label>
            <Label className="flex items-center gap-1.5 font-normal text-sm">
              <Checkbox checked={!!o.success} disabled={!o.reached} onCheckedChange={(on) => set(i, { success: !!on })} />
              Win
            </Label>
            <Label className="flex items-center gap-1.5 font-normal text-sm">
              <Checkbox checked={!!o.callback} onCheckedChange={(on) => set(i, { callback: !!on })} />
              Callback
            </Label>
            <RowButtons
              label={o.label || "outcome"}
              onDown={() => onChange(move(outcomes, i, 1))}
              onRemove={() => onChange(outcomes.filter((_, j) => j !== i))}
              onUp={() => onChange(move(outcomes, i, -1))}
            />
          </div>
        ))}
        <Button
          className="self-start"
          onClick={() => onChange([...outcomes, { callback: false, label: "", reached: true, stage: null, success: false, value: "" }])}
          size="sm"
          variant="outline"
        >
          <PlusIcon aria-hidden="true" />
          Add an outcome
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
  // Conditions can only use questions above that are saved (their keys and choices are final).
  const parents = earlier.filter((p) => p.saved && (p.type === "select" || p.type === "multi" || p.type === "boolean"));
  const [parentKey, parentValues] = Object.entries(q.show_if ?? {})[0] ?? [null, []];
  const parent = parents.find((p) => p.key === parentKey);
  const parentOptions: [string, string][] = parent
    ? parent.type === "boolean"
      ? [["true", "Yes"], ["false", "No"]]
      : (parent.options ?? []).filter(([v]) => v)
    : [];
  const parentItems = [{ label: "Always asked", value: NONE }, ...parents.map((p) => ({ label: `Only when "${p.label}" is…`, value: p.key }))];
  return (
    <div className="flex flex-col gap-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-6 text-muted-foreground text-xs tabular-nums">{index + 1}.</span>
        <Input
          aria-label="Question"
          className="min-w-56 flex-1"
          onChange={(e) => set({ key: q.saved ? q.key : slug(e.target.value, `q${index + 1}`), label: e.target.value })}
          placeholder="The question, e.g. What kind of business?"
          value={q.label}
        />
        <div className="w-44">
          <Select
            items={TYPES}
            onValueChange={(v) => set({ options: v === "select" || v === "multi" ? (q.options ?? []) : undefined, type: v as OpQuestionType })}
            value={q.type}
          >
            <SelectTrigger size="sm">
              <SelectValue />
            </SelectTrigger>
            <SelectPopup>
              {TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectPopup>
          </Select>
        </div>
        <RowButtons label={q.label || "question"} onDown={() => onMove(1)} onRemove={onRemove} onUp={() => onMove(-1)} />
      </div>

      {choices && (
        <div className="flex flex-col gap-1.5 ps-8">
          {(q.options ?? []).map(([value, label], i) => (
            <div className="flex items-center gap-1.5" key={value || `new-${i}`}>
              <Input
                aria-label="Choice"
                className="max-w-sm"
                onChange={(e) => set({ options: (q.options ?? []).map((o, j) => (j === i ? [o[0], e.target.value] : o)) })}
                placeholder="A choice"
                size="sm"
                value={label}
              />
              <Button aria-label="Remove choice" onClick={() => set({ options: (q.options ?? []).filter((_, j) => j !== i) })} size="icon-sm" variant="ghost">
                <XIcon aria-hidden="true" />
              </Button>
            </div>
          ))}
          <Button className="self-start" onClick={() => set({ options: [...(q.options ?? []), ["", ""]] })} size="xs" variant="ghost">
            <PlusIcon aria-hidden="true" />
            Add a choice
          </Button>
        </div>
      )}

      <div className="grid gap-2 ps-8 sm:grid-cols-2 lg:grid-cols-4">
        <Input aria-label="Section" onChange={(e) => set({ section: e.target.value })} placeholder="Section" size="sm" value={q.section} />
        <Input aria-label="Help text" onChange={(e) => set({ help: e.target.value || undefined })} placeholder="Help for the agent (optional)" size="sm" value={q.help ?? ""} />
        {q.type === "number" && (
          <Input aria-label="Unit" onChange={(e) => set({ unit: e.target.value || undefined })} placeholder="Unit, e.g. DT / day" size="sm" value={q.unit ?? ""} />
        )}
        <Input
          aria-label="CRM field"
          dir="ltr"
          onChange={(e) => set({ crm: e.target.value.trim() || undefined })}
          placeholder="Copy to CRM: person.city"
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
    </div>
  );
}

function QuestionsEditor({ questions, onChange }: { questions: DraftQuestion[]; onChange: (q: DraftQuestion[]) => void }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Questions</CardTitle>
        <CardDescription>
          What agents ask during the call, grouped by section. Answers are saved with the call and in the CRM note; a CRM field
          (person.&lt;field&gt;) also copies the answer to the contact.
        </CardDescription>
      </CardHeader>
      <CardPanel className="flex flex-col gap-2">
        {questions.length === 0 && <p className="text-muted-foreground text-sm">No questions: agents only write a note.</p>}
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
              { key: "", label: "", saved: false, section: questions.at(-1)?.section ?? "Questions", type: "text" },
            ])
          }
          size="sm"
          variant="outline"
        >
          <PlusIcon aria-hidden="true" />
          Add a question
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
  const days = draft.call_days ?? [1, 2, 3, 4, 5, 6, 7];

  const save = async () => {
    setSaving(true);
    setError(null);
    const body = {
      ...draft,
      // New questions without a key yet get one made from their label by the server.
      questions: draft.questions.map(({ saved, ...q }) => ({ ...q, key: saved ? q.key : "" })),
    };
    try {
      await api(draft.id === null ? "/api/operations/campaigns" : `/api/operations/campaigns/${draft.id}`, {
        body,
        method: draft.id === null ? "POST" : "PUT",
      });
      toastManager.add({ title: "Campaign saved", type: "success" });
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
          <ArrowLeftIcon aria-hidden="true" />
          All campaigns
        </Button>
        <Button loading={saving} onClick={save}>
          Save campaign
        </Button>
      </div>
      {error && (
        <Alert variant="error">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>Not saved</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Campaign</CardTitle>
        </CardHeader>
        <CardPanel className="grid gap-4 md:grid-cols-2">
          <Field>
            <FieldLabel>Name</FieldLabel>
            <Input maxLength={80} onChange={(e) => set({ name: e.target.value })} value={draft.name} />
          </Field>
          <Label className="flex items-center gap-3 self-end font-medium">
            <Switch checked={draft.active} onCheckedChange={(on) => set({ active: on })} />
            {draft.active ? "Running: agents can pick it" : "Paused: hidden from agents"}
          </Label>
          <Field className="md:col-span-2">
            <FieldLabel>Description</FieldLabel>
            <Textarea className="min-h-16" maxLength={500} onChange={(e) => set({ description: e.target.value })} value={draft.description ?? ""} />
          </Field>
          <Field className="md:col-span-2">
            <FieldLabel>Queue</FieldLabel>
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
            <FieldDescription>The CRM opportunities at these stages, with a phone number, are called oldest first.</FieldDescription>
          </Field>
        </CardPanel>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Calling rules</CardTitle>
          <CardDescription>When the queue is served, and how long to keep trying a contact who doesn't answer.</CardDescription>
        </CardHeader>
        <CardPanel className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Field>
            <FieldLabel>Tries before giving up</FieldLabel>
            <Input
              min={0}
              max={50}
              onChange={(e) => set({ max_attempts: Number(e.target.value) || 0 })}
              type="number"
              value={draft.max_attempts}
            />
            <FieldDescription>Unanswered calls in a row; 0: no limit.</FieldDescription>
          </Field>
          <Field>
            <FieldLabel>Try again after (minutes)</FieldLabel>
            <Input min={0} onChange={(e) => set({ retry_minutes: Number(e.target.value) || 0 })} type="number" value={draft.retry_minutes} />
            <FieldDescription>Suggested callback after an unanswered call.</FieldDescription>
          </Field>
          <Field className="lg:col-span-2">
            <FieldLabel>Contacts who never answer move to</FieldLabel>
            <StageSelect onChange={(exhausted_stage) => set({ exhausted_stage })} placeholder="Keep the stage" stages={config.stages} value={draft.exhausted_stage} />
          </Field>
          <Field>
            <FieldLabel>Calling from</FieldLabel>
            <Input onChange={(e) => set({ call_start: e.target.value || null })} type="time" value={draft.call_start ?? ""} />
          </Field>
          <Field>
            <FieldLabel>Until</FieldLabel>
            <Input onChange={(e) => set({ call_end: e.target.value || null })} type="time" value={draft.call_end ?? ""} />
            <FieldDescription>Empty: any time.</FieldDescription>
          </Field>
          <Field className="lg:col-span-2">
            <FieldLabel>On</FieldLabel>
            <div className="flex flex-wrap gap-1.5">
              {DAYS.map((label, i) => (
                <Chip
                  key={label}
                  onPressedChange={(on) => {
                    const next = on ? [...days, i + 1].sort() : days.filter((d) => d !== i + 1);
                    set({ call_days: next.length === 7 ? null : next });
                  }}
                  pressed={days.includes(i + 1)}
                >
                  {label}
                </Chip>
              ))}
            </div>
            <FieldDescription>Callbacks that come due are served at any time.</FieldDescription>
          </Field>
        </CardPanel>
      </Card>

      <OutcomesEditor onChange={(outcomes) => set({ outcomes })} outcomes={draft.outcomes} stages={config.stages} />
      <QuestionsEditor onChange={(questions) => set({ questions })} questions={draft.questions} />

      <div className="flex justify-end">
        <Button loading={saving} onClick={save}>
          Save campaign
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
        <AlertTitle>Couldn't load the campaigns</AlertTitle>
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
    if (!window.confirm(`Remove "${c.name}"? A campaign with calls is archived instead, and its history kept.`)) return;
    try {
      const res = await api<{ result: string }>(`/api/operations/campaigns/${c.id}`, { method: "DELETE" });
      toastManager.add({ title: res.result === "archived" ? "Campaign archived" : "Campaign deleted", type: "success" });
      reload();
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't remove the campaign", type: "error" });
    }
  };

  return (
    <>
      <div className="flex justify-end">
        <Button onClick={() => setEditing(toDraft(config.campaigns[0], true))}>
          <PlusIcon aria-hidden="true" />
          New campaign
        </Button>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {config.campaigns.map((c) => (
          <Card className={c.active ? undefined : "opacity-70"} key={c.id}>
            <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-2">
              <div className="flex flex-col gap-1">
                <CardTitle className="flex items-center gap-2">
                  {c.name}
                  {!c.active && (
                    <Badge variant="secondary">
                      <ArchiveIcon aria-hidden="true" />
                      Paused
                    </Badge>
                  )}
                </CardTitle>
                {c.description && <CardDescription>{c.description}</CardDescription>}
              </div>
              <div className="flex items-center gap-1">
                <Button onClick={() => setEditing(toDraft(c))} size="sm" variant="outline">
                  <PencilIcon aria-hidden="true" />
                  Edit
                </Button>
                <Button aria-label={`Copy ${c.name}`} onClick={() => setEditing(toDraft(c, true))} size="icon-sm" variant="ghost">
                  <CopyIcon aria-hidden="true" />
                </Button>
                <Button aria-label={`Remove ${c.name}`} onClick={() => remove(c)} size="icon-sm" variant="ghost">
                  <Trash2Icon aria-hidden="true" />
                </Button>
              </div>
            </CardHeader>
            <CardPanel className="flex flex-col gap-2 text-sm">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-muted-foreground">Queue:</span>
                {c.stages.map((s) => (
                  <Badge key={s} variant={STAGE_VARIANT[s] ?? "secondary"}>
                    {stageLabel(s)}
                  </Badge>
                ))}
              </div>
              <span className="text-muted-foreground">
                {c.questions.length} questions · {c.outcomes.length} outcomes ({c.outcomes.filter((o) => o.success).length} wins) · called{" "}
                {c.hours}
                {c.max_attempts ? ` · up to ${c.max_attempts} tries, ${c.retry_minutes} min apart` : ""}
              </span>
            </CardPanel>
          </Card>
        ))}
      </div>
    </>
  );
}
