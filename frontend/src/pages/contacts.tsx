import {
  ArrowLeftIcon,
  CircleAlertIcon,
  ContactRoundIcon,
  EllipsisIcon,
  MailIcon,
  PencilIcon,
  PhoneIcon,
  PlusIcon,
  SearchIcon,
  Trash2Icon,
  UserPlusIcon,
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
  CardAction,
  CardDescription,
  CardFrame,
  CardFrameFooter,
  CardFrameHeader,
  CardHeader,
  CardPanel,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Label } from "@/components/ui/label";
import { Menu, MenuItem, MenuPopup, MenuSeparator, MenuTrigger } from "@/components/ui/menu";
import { Pagination, PaginationContent, PaginationItem, PaginationNext, PaginationPrevious } from "@/components/ui/pagination";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { toastManager } from "@/components/ui/toast";
import { Tooltip, TooltipPopup, TooltipTrigger } from "@/components/ui/tooltip";
import { api, useApi } from "@/lib/api";
import { Bidi } from "@/lib/bidi";
import { fmtDate, fmtDateTime, fmtRelative } from "@/lib/format";
import { t, type TKey } from "@/lib/i18n";
import { href, navigate, type Route } from "@/lib/router";
import type {
  CrmContact,
  CrmContactDetail,
  CrmContactOpportunity,
  CrmContacts,
  CrmField,
  CrmFieldValue,
  CrmSetup,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;
const NONE = "__none";

type Item = { label: string; value: string };

/** A Select over plain {label, value} items. */
export function ChoiceSelect({
  items,
  value,
  onChange,
  label,
  size,
  className,
  disabled,
}: {
  items: Item[];
  value: string;
  onChange: (value: string) => void;
  label: string;
  size?: "sm" | "default";
  className?: string;
  disabled?: boolean;
}) {
  return (
    <Select disabled={disabled} items={items} onValueChange={(v) => onChange(v as string)} value={value}>
      <SelectTrigger aria-label={label} className={className} size={size}>
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

function stageLabel(setup: CrmSetup | undefined, value: string | null) {
  return setup?.stages.find((s) => s.value === value)?.label ?? value ?? "–";
}

/** How a custom field's value reads: yes/no, a choice's label, or the value as typed. */
function fieldText(field: CrmField, value: CrmFieldValue | undefined): string | null {
  if (value === undefined || value === null || value === "") return null;
  if (field.type === "boolean") return value === true || value === "true" ? t("crm.yes") : t("crm.no");
  if (field.type === "choice") return field.options?.find(([v]) => v === String(value))?.[1] ?? String(value);
  return String(value);
}

/** CRM notes are markdown-lite: one paragraph per line, **bold**. */
function NoteText({ text }: { text: string }) {
  return (
    <div className="flex flex-col gap-1 text-sm">
      {text.split("\n").filter((line) => line.trim()).map((line, i) => (
        <p dir="auto" key={i}>
          {line.split(/(\*\*[^*]+\*\*)/g).map((part, j) =>
            part.startsWith("**") && part.endsWith("**") ? <strong key={j}>{part.slice(2, -2)}</strong> : part,
          )}
        </p>
      ))}
    </div>
  );
}

/** The built-in CRM isn't the one in use (or couldn't be reached): what to do instead. */
function NotLocal({ setup, error }: { setup: CrmSetup | undefined; error: Error | undefined }) {
  if (error) {
    return (
      <Alert variant="error">
        <CircleAlertIcon aria-hidden="true" />
        <AlertTitle>{t("crm.loadFailed")}</AlertTitle>
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    );
  }
  return (
    <Empty className="rounded-xl border md:py-16">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <ContactRoundIcon />
        </EmptyMedia>
        <EmptyTitle>{t("crm.notLocal", { crm: setup?.label })}</EmptyTitle>
        <EmptyDescription>{t("crm.notLocalHint")}</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button render={<a href={href("settings")} />} variant="outline">
          {t("common.openSettings")}
        </Button>
      </EmptyContent>
    </Empty>
  );
}

// --- Contact form ----------------------------------------------------------------------------------

/** One custom field's input, by type. Values are kept as text; the server checks and converts them. */
function CustomFieldInput({ field, value, onChange }: { field: CrmField; value: string; onChange: (v: string) => void }) {
  if (field.type === "boolean" || field.type === "choice") {
    const items = [
      { label: t("crm.notSet"), value: NONE },
      ...(field.type === "boolean"
        ? [
            { label: t("crm.yes"), value: "true" },
            { label: t("crm.no"), value: "false" },
          ]
        : (field.options ?? []).map(([v, label]) => ({ label, value: v }))),
    ];
    return <ChoiceSelect items={items} label={field.label} onChange={(v) => onChange(v === NONE ? "" : v)} value={value || NONE} />;
  }
  return (
    <Input
      dir="auto"
      inputMode={field.type === "number" ? "decimal" : undefined}
      onChange={(e) => onChange(e.target.value)}
      pattern={field.type === "number" ? "-?[0-9]+([.,][0-9]+)?" : undefined}
      type="text"
      value={value}
    />
  );
}

function PhonesInput({ phones, onChange }: { phones: string[]; onChange: (phones: string[]) => void }) {
  const rows = phones.length ? phones : [""];
  return (
    <div className="flex flex-col gap-2">
      {rows.map((phone, i) => (
        <div className="flex gap-2" key={i}>
          <Input
            aria-label={t("crm.phoneN", { n: i + 1 })}
            dir="ltr"
            inputMode="tel"
            onChange={(e) => onChange(rows.map((p, j) => (j === i ? e.target.value : p)))}
            placeholder={i === 0 ? "+216 22 602 716" : undefined}
            type="tel"
            value={phone}
          />
          {rows.length > 1 && (
            <Button
              aria-label={t("crm.removePhone", { phone: phone || i + 1 })}
              onClick={() => onChange(rows.filter((_, j) => j !== i))}
              size="icon"
              variant="ghost"
            >
              <XIcon aria-hidden="true" />
            </Button>
          )}
        </div>
      ))}
      <Button className="self-start" onClick={() => onChange([...rows, ""])} size="sm" variant="outline">
        <PlusIcon aria-hidden="true" />
        {t("crm.addPhone")}
      </Button>
    </div>
  );
}

const BUILTIN: { key: "email" | "job_title" | "company" | "city"; label: TKey }[] = [
  { key: "email", label: "crm.email" },
  { key: "company", label: "crm.company" },
  { key: "job_title", label: "crm.jobTitle" },
  { key: "city", label: "crm.city" },
];

/** Add a contact (contact = null) or edit one. */
function ContactDialog({
  contact,
  setup,
  open,
  onOpenChange,
  onSaved,
}: {
  contact: CrmContact | null;
  setup: CrmSetup;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (id: string) => void;
}) {
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogPopup className="sm:max-w-xl">
        <ContactForm contact={contact} onDone={() => onOpenChange(false)} onSaved={onSaved} setup={setup} />
      </DialogPopup>
    </Dialog>
  );
}

function ContactForm({
  contact,
  setup,
  onDone,
  onSaved,
}: {
  contact: CrmContact | null;
  setup: CrmSetup;
  onDone: () => void;
  onSaved: (id: string) => void;
}) {
  const editing = contact !== null;
  const [name, setName] = React.useState(contact?.name ?? "");
  const [builtin, setBuiltin] = React.useState<Record<string, string>>(
    Object.fromEntries(BUILTIN.map((b) => [b.key, contact?.[b.key] ?? ""])),
  );
  const [phones, setPhones] = React.useState<string[]>(contact?.phones ?? [""]);
  const [custom, setCustom] = React.useState<Record<string, string>>(
    Object.fromEntries(setup.fields.map((f) => [f.key, String(contact?.fields[f.key] ?? "")])),
  );
  const [withLead, setWithLead] = React.useState(true);
  const [stage, setStage] = React.useState(setup.stages[0]?.value ?? "");
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const body = { ...builtin, fields: custom, name: name.trim(), phones: phones.map((p) => p.trim()).filter(Boolean) };
    try {
      let id = contact?.id;
      if (editing) {
        await api(`/api/crm/contacts/${encodeURIComponent(contact.id)}`, { body, method: "PATCH" });
      } else {
        id = (await api<{ id: string }>("/api/crm/contacts", { body, method: "POST" })).id;
        if (withLead && stage) {
          await api(`/api/crm/contacts/${encodeURIComponent(id)}/opportunities`, {
            body: { name: t("crm.defaultLeadName", { name: name.trim() }), stage },
            method: "POST",
          });
        }
      }
      toastManager.add({ title: editing ? t("crm.contactSaved") : t("crm.contactAdded", { name: name.trim() }), type: "success" });
      onSaved(id as string);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const stageItems = setup.stages.map((s) => ({ label: s.label, value: s.value }));
  return (
    <Form className="contents" onSubmit={onSubmit}>
      <DialogHeader>
        <DialogTitle>{editing ? t("crm.editContact", { name: contact.name }) : t("crm.addContact")}</DialogTitle>
        <DialogDescription>{editing ? t("crm.editContactHint") : t("crm.addContactHint")}</DialogDescription>
      </DialogHeader>
      <DialogPanel className="flex flex-col gap-5">
        {error && (
          <Alert variant="error">
            <CircleAlertIcon aria-hidden="true" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <Field>
          <FieldLabel>{t("crm.name")}</FieldLabel>
          <Input autoFocus dir="auto" onChange={(e) => setName(e.target.value)} required type="text" value={name} />
        </Field>
        <div className="flex flex-col gap-2">
          <span className="font-medium text-sm">{t("crm.phones")}</span>
          <p className="text-muted-foreground text-xs">{t("crm.phonesHint")}</p>
          <PhonesInput onChange={setPhones} phones={phones} />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          {BUILTIN.map((b) => (
            <Field key={b.key}>
              <FieldLabel>{t(b.label)}</FieldLabel>
              <Input
                dir={b.key === "email" ? "ltr" : "auto"}
                onChange={(e) => setBuiltin((v) => ({ ...v, [b.key]: e.target.value }))}
                type={b.key === "email" ? "email" : "text"}
                value={builtin[b.key]}
              />
            </Field>
          ))}
        </div>
        {setup.fields.length > 0 && (
          <div className="flex flex-col gap-3">
            <span className="font-medium text-sm">{t("crm.customFields")}</span>
            <div className="grid gap-4 sm:grid-cols-2">
              {setup.fields.map((f) => (
                <Field key={f.key}>
                  <FieldLabel>{f.label}</FieldLabel>
                  <CustomFieldInput field={f} onChange={(v) => setCustom((c) => ({ ...c, [f.key]: v }))} value={custom[f.key] ?? ""} />
                </Field>
              ))}
            </div>
          </div>
        )}
        {!editing && (
          <div className="flex flex-col gap-3 rounded-lg border p-3">
            <Label className="font-normal">
              <Checkbox checked={withLead} onCheckedChange={(on) => setWithLead(!!on)} />
              {t("crm.addLeadToo")}
            </Label>
            {withLead && (
              <Field>
                <FieldLabel>{t("crm.stage")}</FieldLabel>
                <ChoiceSelect items={stageItems} label={t("crm.stage")} onChange={setStage} value={stage} />
                <FieldDescription>{t("crm.addLeadTooHint")}</FieldDescription>
              </Field>
            )}
          </div>
        )}
      </DialogPanel>
      <DialogFooter>
        <DialogClose render={<Button variant="ghost" />}>{t("common.cancel")}</DialogClose>
        <Button loading={saving} type="submit">
          {editing ? t("common.save") : t("crm.addContact")}
        </Button>
      </DialogFooter>
    </Form>
  );
}

// --- Opportunity form ------------------------------------------------------------------------------

function OpportunityDialog({
  personId,
  personName,
  opportunity,
  setup,
  open,
  onOpenChange,
  onSaved,
}: {
  personId: string;
  personName: string;
  opportunity: CrmContactOpportunity | null;
  setup: CrmSetup;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogPopup className="sm:max-w-lg">
        <OpportunityForm
          onDone={() => onOpenChange(false)}
          onSaved={onSaved}
          opportunity={opportunity}
          personId={personId}
          personName={personName}
          setup={setup}
        />
      </DialogPopup>
    </Dialog>
  );
}

function OpportunityForm({
  personId,
  personName,
  opportunity,
  setup,
  onDone,
  onSaved,
}: {
  personId: string;
  personName: string;
  opportunity: CrmContactOpportunity | null;
  setup: CrmSetup;
  onDone: () => void;
  onSaved: () => void;
}) {
  const editing = opportunity !== null;
  const [name, setName] = React.useState(opportunity?.name ?? t("crm.defaultLeadName", { name: personName }));
  const [stage, setStage] = React.useState(opportunity?.stage ?? setup.stages[0]?.value ?? "");
  const [owner, setOwner] = React.useState(opportunity?.owner_id ?? NONE);
  const [amount, setAmount] = React.useState(opportunity?.amount == null ? "" : String(opportunity.amount));
  const [currency, setCurrency] = React.useState(opportunity?.currency ?? "TND");
  const [closeDate, setCloseDate] = React.useState(opportunity?.close_date?.slice(0, 10) ?? "");
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  const ownerItems = [
    { label: t("crm.noOwner"), value: NONE },
    ...setup.members.map((m) => ({ label: m.name, value: m.id })),
  ];
  if (!ownerItems.some((i) => i.value === owner)) ownerItems.push({ label: opportunity?.owner ?? owner, value: owner });

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const number = amount.trim() ? Number(amount.replace(",", ".")) : null;
    if (number !== null && Number.isNaN(number)) {
      setError(t("crm.amountNotNumber"));
      return;
    }
    setSaving(true);
    setError(null);
    const body = {
      amount: number,
      close_date: closeDate || null,
      currency: number === null ? null : currency.trim() || null,
      name: name.trim(),
      owner: owner === NONE ? null : owner,
      stage,
    };
    try {
      if (editing) {
        await api(`/api/crm/opportunities/${encodeURIComponent(opportunity.id)}`, { body, method: "PATCH" });
      } else {
        await api(`/api/crm/contacts/${encodeURIComponent(personId)}/opportunities`, { body, method: "POST" });
      }
      toastManager.add({ title: editing ? t("crm.opportunitySaved") : t("crm.opportunityAdded"), type: "success" });
      onSaved();
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Form className="contents" onSubmit={onSubmit}>
      <DialogHeader>
        <DialogTitle>{editing ? t("crm.editOpportunity") : t("crm.addOpportunity")}</DialogTitle>
        <DialogDescription>{t("crm.opportunityHint", { name: personName })}</DialogDescription>
      </DialogHeader>
      <DialogPanel className="flex flex-col gap-5">
        {error && (
          <Alert variant="error">
            <CircleAlertIcon aria-hidden="true" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <Field>
          <FieldLabel>{t("crm.opportunityName")}</FieldLabel>
          <Input dir="auto" onChange={(e) => setName(e.target.value)} required type="text" value={name} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field>
            <FieldLabel>{t("crm.stage")}</FieldLabel>
            <ChoiceSelect
              items={setup.stages.map((s) => ({ label: s.label, value: s.value }))}
              label={t("crm.stage")}
              onChange={setStage}
              value={stage}
            />
          </Field>
          <Field>
            <FieldLabel>{t("leads.owner")}</FieldLabel>
            <ChoiceSelect items={ownerItems} label={t("leads.owner")} onChange={setOwner} value={owner} />
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field className="sm:col-span-2">
            <FieldLabel>{t("crm.amount")}</FieldLabel>
            <Input inputMode="decimal" onChange={(e) => setAmount(e.target.value)} type="text" value={amount} />
          </Field>
          <Field>
            <FieldLabel>{t("crm.currency")}</FieldLabel>
            <Input maxLength={8} onChange={(e) => setCurrency(e.target.value.toUpperCase())} type="text" value={currency} />
          </Field>
        </div>
        <Field>
          <FieldLabel>{t("crm.closeDate")}</FieldLabel>
          <Input onChange={(e) => setCloseDate(e.target.value)} type="date" value={closeDate} />
        </Field>
      </DialogPanel>
      <DialogFooter>
        <DialogClose render={<Button variant="ghost" />}>{t("common.cancel")}</DialogClose>
        <Button loading={saving} type="submit">
          {editing ? t("common.save") : t("crm.addOpportunity")}
        </Button>
      </DialogFooter>
    </Form>
  );
}

/** Confirm, then DELETE `path`. */
function ConfirmDelete({
  open,
  title,
  description,
  action,
  path,
  onOpenChange,
  onDeleted,
}: {
  open: boolean;
  title: string;
  description: string;
  action: string;
  path: string;
  onOpenChange: (open: boolean) => void;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const remove = async () => {
    setBusy(true);
    try {
      await api(path, { method: "DELETE" });
      onOpenChange(false);
      onDeleted();
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: t("crm.deleteFailed"), type: "error" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <AlertDialog onOpenChange={onOpenChange} open={open}>
      <AlertDialogPopup>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogClose render={<Button variant="ghost" />}>{t("common.cancel")}</AlertDialogClose>
          <Button loading={busy} onClick={remove} variant="destructive">
            {action}
          </Button>
        </AlertDialogFooter>
      </AlertDialogPopup>
    </AlertDialog>
  );
}

// --- One contact -----------------------------------------------------------------------------------

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

function OpportunityRow({
  opportunity,
  setup,
  highlighted,
  onEdit,
  onDelete,
  onChanged,
}: {
  opportunity: CrmContactOpportunity;
  setup: CrmSetup;
  highlighted: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onChanged: () => void;
}) {
  const [saving, setSaving] = React.useState(false);
  const moveTo = async (stage: string) => {
    setSaving(true);
    try {
      await api(`/api/crm/opportunities/${encodeURIComponent(opportunity.id)}`, { body: { stage }, method: "PATCH" });
      toastManager.add({ title: t("crm.movedTo", { stage: stageLabel(setup, stage) }), type: "success" });
      onChanged();
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: t("common.couldntSave"), type: "error" });
    } finally {
      setSaving(false);
    }
  };
  const amount =
    opportunity.amount != null
      ? `${opportunity.amount.toLocaleString()}${opportunity.currency ? ` ${opportunity.currency}` : ""}`
      : null;
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border p-3",
        highlighted && "border-ring ring-[3px] ring-ring/24",
      )}
    >
      <div className="flex min-w-48 flex-1 flex-col gap-0.5">
        <Bidi className="font-medium text-sm" text={opportunity.name} />
        <span className="text-muted-foreground text-xs">
          {[opportunity.owner ?? t("crm.noOwner"), amount, opportunity.close_date && t("crm.closesOn", { date: fmtDate(opportunity.close_date) })]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>
      <ChoiceSelect
        className="w-44"
        disabled={saving}
        items={setup.stages.map((s) => ({ label: s.label, value: s.value }))}
        label={t("crm.stageOf", { name: opportunity.name })}
        onChange={moveTo}
        size="sm"
        value={opportunity.stage ?? ""}
      />
      <Tooltip>
        <TooltipTrigger render={<span className="text-muted-foreground text-xs tabular-nums" />}>
          {t("crm.updated", { time: fmtRelative(opportunity.updated_at) })}
        </TooltipTrigger>
        <TooltipPopup>{fmtDateTime(opportunity.updated_at)}</TooltipPopup>
      </Tooltip>
      <Menu>
        <MenuTrigger render={<Button aria-label={t("crm.actionsFor", { name: opportunity.name })} size="icon-sm" variant="ghost" />}>
          <EllipsisIcon aria-hidden="true" />
        </MenuTrigger>
        <MenuPopup align="end">
          <MenuItem onClick={onEdit}>
            <PencilIcon aria-hidden="true" />
            {t("common.edit")}
          </MenuItem>
          <MenuSeparator />
          <MenuItem onClick={onDelete} variant="destructive">
            <Trash2Icon aria-hidden="true" />
            {t("common.delete")}
          </MenuItem>
        </MenuPopup>
      </Menu>
    </div>
  );
}

function NoteComposer({ contact, onAdded }: { contact: CrmContactDetail; onAdded: (c: CrmContactDetail) => void }) {
  const [text, setText] = React.useState("");
  const [about, setAbout] = React.useState(NONE);
  const [saving, setSaving] = React.useState(false);
  const items = [
    { label: t("crm.aboutContact"), value: NONE },
    ...contact.opportunities.map((o) => ({ label: o.name, value: o.id })),
  ];
  const add = async () => {
    setSaving(true);
    try {
      const updated = await api<CrmContactDetail>(`/api/crm/contacts/${encodeURIComponent(contact.id)}/notes`, {
        body: { opportunity_id: about === NONE ? null : about, text },
        method: "POST",
      });
      setText("");
      onAdded(updated);
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: t("common.couldntSave"), type: "error" });
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="flex flex-col gap-2">
      <Textarea
        aria-label={t("crm.newNote")}
        dir="auto"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && text.trim()) add();
        }}
        placeholder={t("crm.notePlaceholder")}
        value={text}
      />
      <div className="flex flex-wrap items-center justify-end gap-2">
        {contact.opportunities.length > 0 && (
          <ChoiceSelect className="w-auto" items={items} label={t("crm.noteAbout")} onChange={setAbout} size="sm" value={about} />
        )}
        <Button disabled={!text.trim()} loading={saving} onClick={add} size="sm">
          {t("crm.addNote")}
        </Button>
      </div>
    </div>
  );
}

function ContactDetail({ id, highlight, setup }: { id: string; highlight: string | null; setup: CrmSetup }) {
  const path = `/api/crm/contacts/${encodeURIComponent(id)}`;
  const { data: contact, error, reload, setData } = useApi<CrmContactDetail>(path);
  const [editing, setEditing] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [opportunity, setOpportunity] = React.useState<CrmContactOpportunity | null>(null);
  const [opportunityOpen, setOpportunityOpen] = React.useState(false);
  const [removing, setRemoving] = React.useState<CrmContactOpportunity | null>(null);
  const [removingNote, setRemovingNote] = React.useState<string | null>(null);

  const back = (
    <Button render={<a href={href("contacts")} />} variant="ghost">
      <ArrowLeftIcon aria-hidden="true" className="rtl:rotate-180" />
      {t("crm.allContacts")}
    </Button>
  );

  if (error) {
    return (
      <>
        <div>{back}</div>
        <Alert variant="error">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>{t("crm.contactLoadFailed")}</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      </>
    );
  }
  if (!contact) {
    return (
      <div className="grid gap-6 lg:grid-cols-3">
        <Skeleton className="h-64 rounded-2xl lg:col-span-2" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    );
  }

  const subtitle = [contact.job_title, contact.company, contact.city].filter(Boolean).join(" · ");
  const noteFor = (oppId: string | null) => contact.opportunities.find((o) => o.id === oppId)?.name;
  return (
    <>
      <PageHeader
        actions={
          <>
            {back}
            {contact.phones[0] && (
              <Button render={<a href={`tel:${contact.phones[0].replace(/\s/g, "")}`} />} variant="outline">
                <PhoneIcon aria-hidden="true" />
                {t("crm.call")}
              </Button>
            )}
            <Button onClick={() => setEditing(true)} variant="outline">
              <PencilIcon aria-hidden="true" />
              {t("common.edit")}
            </Button>
            <Button onClick={() => setDeleting(true)} variant="destructive-outline">
              <Trash2Icon aria-hidden="true" />
              {t("common.delete")}
            </Button>
          </>
        }
        description={subtitle || t("crm.addedOn", { date: fmtDate(contact.created_at) })}
        title={contact.name}
      />

      <div className="grid items-start gap-6 lg:grid-cols-3">
        <div className="flex flex-col gap-6 lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>{t("crm.opportunities")}</CardTitle>
              <CardDescription>{t("crm.opportunitiesHint")}</CardDescription>
              <CardAction>
                <Button
                  onClick={() => {
                    setOpportunity(null);
                    setOpportunityOpen(true);
                  }}
                  size="sm"
                  variant="outline"
                >
                  <PlusIcon aria-hidden="true" />
                  {t("crm.addOpportunity")}
                </Button>
              </CardAction>
            </CardHeader>
            <CardPanel className="flex flex-col gap-2">
              {contact.opportunities.length === 0 ? (
                <p className="text-muted-foreground text-sm">{t("crm.noOpportunities")}</p>
              ) : (
                contact.opportunities.map((o) => (
                  <OpportunityRow
                    highlighted={o.id === highlight}
                    key={o.id}
                    onChanged={reload}
                    onDelete={() => setRemoving(o)}
                    onEdit={() => {
                      setOpportunity(o);
                      setOpportunityOpen(true);
                    }}
                    opportunity={o}
                    setup={setup}
                  />
                ))
              )}
            </CardPanel>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("crm.notes")}</CardTitle>
              <CardDescription>{t("crm.notesHint")}</CardDescription>
            </CardHeader>
            <CardPanel className="flex flex-col gap-4">
              <NoteComposer contact={contact} onAdded={setData} />
              {contact.notes.length === 0 ? (
                <p className="text-muted-foreground text-sm">{t("crm.noNotes")}</p>
              ) : (
                <ul className="flex flex-col divide-y rounded-lg border">
                  {contact.notes.map((n) => (
                    <li className="group flex flex-col gap-1.5 p-3" key={n.id}>
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="font-medium text-sm" dir="auto">
                          {n.title}
                        </span>
                        {noteFor(n.opportunity_id) && <Badge variant="outline">{noteFor(n.opportunity_id)}</Badge>}
                        <Tooltip>
                          <TooltipTrigger render={<span className="text-muted-foreground text-xs" />}>
                            {[n.author, fmtRelative(n.created_at)].filter(Boolean).join(" · ")}
                          </TooltipTrigger>
                          <TooltipPopup>{fmtDateTime(n.created_at)}</TooltipPopup>
                        </Tooltip>
                        <Button
                          aria-label={t("crm.deleteNote")}
                          className="ms-auto opacity-0 focus-visible:opacity-100 group-hover:opacity-100"
                          onClick={() => setRemovingNote(n.id)}
                          size="icon-xs"
                          variant="ghost"
                        >
                          <Trash2Icon aria-hidden="true" />
                        </Button>
                      </div>
                      <NoteText text={n.text} />
                    </li>
                  ))}
                </ul>
              )}
            </CardPanel>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>{t("crm.details")}</CardTitle>
          </CardHeader>
          <CardPanel>
            <dl className="flex flex-col gap-4">
              <DetailRow label={t("crm.phones")}>
                {contact.phones.length ? (
                  <div className="flex flex-col gap-0.5">
                    {contact.phones.map((p) => (
                      <a className="font-medium tabular-nums hover:underline" dir="ltr" href={`tel:${p.replace(/\s/g, "")}`} key={p}>
                        {p}
                      </a>
                    ))}
                  </div>
                ) : (
                  <span className="text-muted-foreground">{t("leads.noNumber")}</span>
                )}
              </DetailRow>
              {contact.email && (
                <DetailRow label={t("crm.email")}>
                  <a className="inline-flex items-center gap-1.5 hover:underline" dir="ltr" href={`mailto:${contact.email}`}>
                    <MailIcon aria-hidden="true" className="size-3.5 text-muted-foreground" />
                    {contact.email}
                  </a>
                </DetailRow>
              )}
              {BUILTIN.filter((b) => b.key !== "email" && contact[b.key]).map((b) => (
                <DetailRow key={b.key} label={t(b.label)}>
                  <Bidi text={contact[b.key] as string} />
                </DetailRow>
              ))}
              {setup.fields.map((f) => {
                const text = fieldText(f, contact.fields[f.key]);
                return (
                  <DetailRow key={f.key} label={f.label}>
                    {text ? <Bidi text={text} /> : <span className="text-muted-foreground">–</span>}
                  </DetailRow>
                );
              })}
              <DetailRow label={t("crm.added")}>
                {fmtDateTime(contact.created_at)}
                {contact.source && <span className="text-muted-foreground"> · {t("crm.source", { source: contact.source })}</span>}
              </DetailRow>
              {contact.phones[0] && (
                <DetailRow label={t("leads.ourCalls")}>
                  <a className="hover:underline" href={href("calls", null, { q: contact.phones[0].replace(/\D/g, "").slice(-8) })}>
                    {t("crm.seeCalls")}
                  </a>
                </DetailRow>
              )}
            </dl>
          </CardPanel>
        </Card>
      </div>

      <ContactDialog
        contact={contact}
        onOpenChange={setEditing}
        onSaved={reload}
        open={editing}
        setup={setup}
      />
      <OpportunityDialog
        onOpenChange={setOpportunityOpen}
        onSaved={reload}
        open={opportunityOpen}
        opportunity={opportunity}
        personId={contact.id}
        personName={contact.name}
        setup={setup}
      />
      <ConfirmDelete
        action={t("crm.deleteContact")}
        description={t("crm.deleteContactHint", { count: contact.opportunities.length })}
        onDeleted={() => {
          toastManager.add({ title: t("crm.contactDeleted", { name: contact.name }), type: "success" });
          navigate(href("contacts"));
        }}
        onOpenChange={setDeleting}
        open={deleting}
        path={path}
        title={t("crm.deleteContactTitle", { name: contact.name })}
      />
      <ConfirmDelete
        action={t("crm.deleteOpportunity")}
        description={t("crm.deleteOpportunityHint")}
        onDeleted={reload}
        onOpenChange={(open) => !open && setRemoving(null)}
        open={!!removing}
        path={`/api/crm/opportunities/${encodeURIComponent(removing?.id ?? "")}`}
        title={t("crm.deleteOpportunityTitle", { name: removing?.name })}
      />
      <ConfirmDelete
        action={t("crm.deleteNote")}
        description={t("crm.deleteNoteHint")}
        onDeleted={reload}
        onOpenChange={(open) => !open && setRemovingNote(null)}
        open={!!removingNote}
        path={`/api/crm/notes/${encodeURIComponent(removingNote ?? "")}`}
        title={t("crm.deleteNoteTitle")}
      />
    </>
  );
}

// --- The list --------------------------------------------------------------------------------------

function ContactList({ route, setup }: { route: Route; setup: CrmSetup }) {
  const q = route.query.get("q") ?? "";
  const stage = route.query.get("stage") ?? "";
  const page = Math.max(1, Number(route.query.get("page")) || 1);
  const setQuery = (patch: { q?: string; stage?: string; page?: string }) =>
    navigate(href("contacts", null, { q, stage, ...patch }), { replace: true });

  const [search, setSearch] = React.useState(q);
  React.useEffect(() => setSearch(q), [q]);
  React.useEffect(() => {
    if (search === q) return;
    const timer = window.setTimeout(() => setQuery({ page: "", q: search }), 250);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String((page - 1) * PAGE_SIZE), q, stage });
  const { data, error, loading, reload } = useApi<CrmContacts>(`/api/crm/contacts?${params}`);
  const [adding, setAdding] = React.useState(false);

  const total = data?.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageHref = (n: number) => href("contacts", null, { page: n > 1 ? String(n) : "", q, stage });
  const hasFilters = !!(q || stage);
  const stageItems = [
    { label: t("crm.allStages"), value: "all" },
    ...setup.stages.map((s) => ({ label: `${s.label} (${s.count.toLocaleString()})`, value: s.value })),
  ];
  const addButton = (
    <Button onClick={() => setAdding(true)}>
      <UserPlusIcon aria-hidden="true" />
      {t("crm.addContact")}
    </Button>
  );

  return (
    <>
      <PageHeader actions={addButton} description={t("crm.contactsDescription")} title={t("nav.contacts")} />

      {error && (
        <Alert variant="error">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>{t("crm.loadFailed")}</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <InputGroup className="w-full sm:w-72">
          <InputGroupInput
            aria-label={t("crm.search")}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("crm.searchPlaceholder")}
            type="search"
            value={search}
          />
          <InputGroupAddon>
            <SearchIcon aria-hidden="true" />
          </InputGroupAddon>
        </InputGroup>
        <ChoiceSelect
          className="w-auto"
          items={stageItems}
          label={t("crm.stage")}
          onChange={(v) => setQuery({ page: "", stage: v === "all" ? "" : v })}
          value={stage || "all"}
        />
        {hasFilters && (
          <Button onClick={() => navigate(href("contacts"), { replace: true })} variant="ghost">
            <XIcon aria-hidden="true" />
            {t("common.reset")}
          </Button>
        )}
      </div>

      <CardFrame>
        <CardFrameHeader className="flex min-h-14 flex-row items-center py-3">
          <div className="text-muted-foreground text-sm">{data ? t("crm.contactCount", { count: total }) : t("crm.loading")}</div>
        </CardFrameHeader>
        <Table variant="card">
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-56">{t("crm.contact")}</TableHead>
              <TableHead>{t("phone.number")}</TableHead>
              <TableHead className="max-md:hidden">{t("crm.city")}</TableHead>
              <TableHead>{t("crm.opportunities")}</TableHead>
              <TableHead className="max-sm:hidden">{t("crm.added")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {!data && loading
              ? Array.from({ length: 8 }, (_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={5}>
                      <Skeleton className="h-5 w-full" />
                    </TableCell>
                  </TableRow>
                ))
              : data?.people.map((p) => (
                  <TableRow className="cursor-pointer align-top" key={p.id} onClick={() => navigate(href("contacts", p.id))}>
                    <TableCell className="whitespace-normal">
                      <a className="font-medium hover:underline" href={href("contacts", p.id)} onClick={(e) => e.stopPropagation()}>
                        <Bidi text={p.name} />
                      </a>
                      {(p.company || p.job_title) && (
                        <Bidi className="text-muted-foreground text-xs" text={[p.job_title, p.company].filter(Boolean).join(" · ")} />
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {p.phones.length ? (
                        <div className="flex flex-col gap-0.5">
                          {p.phones.map((phone) => (
                            <span className="tabular-nums" dir="ltr" key={phone}>
                              {phone}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-muted-foreground">{t("leads.noNumber")}</span>
                      )}
                    </TableCell>
                    <TableCell className="max-md:hidden">{p.city ? <Bidi text={p.city} /> : "–"}</TableCell>
                    <TableCell className="whitespace-normal">
                      {p.opportunities.length ? (
                        <div className="flex flex-wrap gap-1">
                          {p.opportunities.slice(0, 3).map((o) => (
                            <Badge key={o.id} variant={o.stage === stage ? "info" : "secondary"}>
                              {stageLabel(setup, o.stage)}
                            </Badge>
                          ))}
                          {p.opportunities.length > 3 && <Badge variant="outline">+{p.opportunities.length - 3}</Badge>}
                        </div>
                      ) : (
                        <span className="text-muted-foreground text-sm">{t("crm.none")}</span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap max-sm:hidden">
                      <Tooltip>
                        <TooltipTrigger render={<span />}>{fmtRelative(p.created_at)}</TooltipTrigger>
                        <TooltipPopup>{fmtDateTime(p.created_at)}</TooltipPopup>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
            {data && data.people.length === 0 && (
              <TableRow>
                <TableCell colSpan={5}>
                  <Empty className="md:py-12">
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <ContactRoundIcon />
                      </EmptyMedia>
                      <EmptyTitle>{hasFilters ? t("crm.noMatch") : t("crm.noContacts")}</EmptyTitle>
                      <EmptyDescription>{hasFilters ? t("common.tryDifferentFilter") : t("crm.noContactsHint")}</EmptyDescription>
                    </EmptyHeader>
                    {!hasFilters && <EmptyContent>{addButton}</EmptyContent>}
                  </Empty>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        {total > PAGE_SIZE && (
          <CardFrameFooter className="flex flex-wrap items-center justify-between gap-2 py-3">
            <p className="text-muted-foreground text-sm tabular-nums">
              {t("calls.range", { first: (page - 1) * PAGE_SIZE + 1, last: Math.min(page * PAGE_SIZE, total), total })}
            </p>
            <Pagination className="mx-0 w-auto">
              <PaginationContent>
                <PaginationItem>
                  <PaginationPrevious
                    aria-disabled={page <= 1}
                    className={page <= 1 ? "pointer-events-none opacity-64" : ""}
                    href={pageHref(page - 1)}
                  />
                </PaginationItem>
                <PaginationItem>
                  <span className="px-2 text-muted-foreground text-sm tabular-nums">{t("calls.pageOf", { last: lastPage, page })}</span>
                </PaginationItem>
                <PaginationItem>
                  <PaginationNext
                    aria-disabled={page >= lastPage}
                    className={page >= lastPage ? "pointer-events-none opacity-64" : ""}
                    href={pageHref(page + 1)}
                  />
                </PaginationItem>
              </PaginationContent>
            </Pagination>
          </CardFrameFooter>
        )}
      </CardFrame>

      <ContactDialog
        contact={null}
        onOpenChange={setAdding}
        onSaved={(id) => {
          reload();
          navigate(href("contacts", id));
        }}
        open={adding}
        setup={setup}
      />
    </>
  );
}

/** The built-in CRM's contacts: the list (#contacts) and one contact with their opportunities and notes (#contacts/<id>). */
export function ContactsPage({ route }: { route: Route }): React.ReactElement {
  const { data: setup, error } = useApi<CrmSetup>("/api/crm/setup", [route.param]);
  if (error || (setup && !setup.local)) {
    return (
      <>
        <PageHeader description={t("crm.contactsDescription")} title={t("nav.contacts")} />
        <NotLocal error={error} setup={setup} />
      </>
    );
  }
  if (!setup) return <Skeleton className="h-64 rounded-2xl" />;
  return route.param ? (
    <ContactDetail highlight={route.query.get("lead")} id={route.param} key={route.param} setup={setup} />
  ) : (
    <ContactList route={route} setup={setup} />
  );
}
