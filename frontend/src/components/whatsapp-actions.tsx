// Settings > WhatsApp: the call desk's quick actions, each an approved template sent in one click.
import { ArrowDownIcon, ArrowUpIcon, CircleAlertIcon, FileTextIcon, PencilIcon, PlusIcon, RefreshCwIcon, Trash2Icon } from "lucide-react";
import * as React from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogDescription, DialogFooter, DialogHeader, DialogPanel, DialogPopup, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Form } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { toastManager } from "@/components/ui/toast";
import { api, useApi } from "@/lib/api";
import { textDir } from "@/lib/bidi";
import type { WaAction, WaActions, WaTemplate } from "@/lib/types";

const FIXED = "text:";
const templateKey = (t: { template?: string; name?: string; language: string }) => `${t.template ?? t.name}|${t.language}`;

/** "body.1" → "Body {{1}}", "button.0.1" → "Button 1 link {{1}}". */
function variableLabel(v: string): string {
  const parts = v.split(".");
  if (parts[0] === "button") return `Button ${Number(parts[1]) + 1} link {{${parts[2]}}}`;
  return `${parts[0] === "header" ? "Title" : "Message"} {{${parts[1]}}}`;
}

/** `refreshKey`: reloaded when it changes, e.g. after the settings above are saved. */
export function WhatsAppActions({ refreshKey }: { refreshKey: unknown }) {
  const { data, reload } = useApi<WaActions>("/api/whatsapp/actions", [refreshKey]);
  const [editing, setEditing] = React.useState<WaAction | "new" | null>(null);

  if (!data) return <Skeleton className="h-24 rounded-xl" />;

  const move = async (index: number, by: number) => {
    const ids = data.actions.map((a) => a.id);
    [ids[index], ids[index + by]] = [ids[index + by], ids[index]];
    await api("/api/whatsapp/actions", { body: { ids }, method: "PUT" });
    reload();
  };
  const remove = async (a: WaAction) => {
    await api(`/api/whatsapp/actions/${a.id}`, { method: "DELETE" });
    toastManager.add({ title: `"${a.label}" removed`, type: "success" });
    reload();
  };

  return (
    <div className="flex flex-col gap-3 rounded-xl border bg-muted/32 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <span className="font-medium text-sm">Quick actions</span>
          <span className="text-muted-foreground text-xs">
            Buttons on the call desk that send the contact a WhatsApp message: the price list, how to make a deposit…
          </span>
        </div>
        <Button disabled={!data.configured} onClick={() => setEditing("new")} size="sm" variant="outline">
          <PlusIcon aria-hidden="true" />
          Add
        </Button>
      </div>
      {!data.configured ? (
        <p className="text-muted-foreground text-sm">Fill in the token, phone number ID and business account ID above and save.</p>
      ) : data.actions.length === 0 ? (
        <p className="text-muted-foreground text-sm">No quick action yet.</p>
      ) : (
        <ul className="flex flex-col divide-y rounded-lg border bg-background">
          {data.actions.map((a, i) => (
            <li className="flex items-center gap-2 px-3 py-2 text-sm" key={a.id}>
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="font-medium" dir="auto">
                  {a.label}
                </span>
                <span className="truncate text-muted-foreground text-xs">
                  {a.template} · {a.language}
                  {a.header_link && " · with a file"}
                </span>
              </span>
              <Button aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)} size="icon-xs" variant="ghost">
                <ArrowUpIcon aria-hidden="true" />
              </Button>
              <Button aria-label="Move down" disabled={i === data.actions.length - 1} onClick={() => move(i, 1)} size="icon-xs" variant="ghost">
                <ArrowDownIcon aria-hidden="true" />
              </Button>
              <Button aria-label={`Edit ${a.label}`} onClick={() => setEditing(a)} size="icon-xs" variant="ghost">
                <PencilIcon aria-hidden="true" />
              </Button>
              <Button aria-label={`Remove ${a.label}`} onClick={() => remove(a)} size="icon-xs" variant="ghost">
                <Trash2Icon aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <Dialog onOpenChange={(open) => !open && setEditing(null)} open={editing !== null}>
        <DialogPopup className="sm:max-w-xl">
          {editing !== null && (
            <ActionForm
              action={editing === "new" ? null : editing}
              onSaved={() => {
                setEditing(null);
                reload();
              }}
              sources={data.sources}
            />
          )}
        </DialogPopup>
      </Dialog>
    </div>
  );
}

function ActionForm({ action, sources, onSaved }: { action: WaAction | null; sources: Record<string, string>; onSaved: () => void }) {
  const { data, error: loadError, reload, loading } = useApi<{ configured: boolean; templates: WaTemplate[] }>(
    "/api/whatsapp/templates",
  );
  const [label, setLabel] = React.useState(action?.label ?? "");
  const [key, setKey] = React.useState(action ? templateKey(action) : "");
  const [params, setParams] = React.useState<Record<string, string>>(action?.params ?? {});
  const [link, setLink] = React.useState(action?.header_link ?? "");
  const [filename, setFilename] = React.useState(action?.header_filename ?? "");
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  const templates = data?.templates ?? [];
  const template = templates.find((t) => templateKey(t) === key);
  const media = template?.header_format && ["DOCUMENT", "IMAGE", "VIDEO"].includes(template.header_format);
  const sourceItems = [
    ...Object.entries(sources).map(([value, text]) => ({ label: text, value })),
    { label: "Fixed text", value: FIXED },
  ];
  const templateItems = templates.map((t) => ({ label: `${t.name} · ${t.language}`, value: templateKey(t) }));

  const pickTemplate = (value: string) => {
    setKey(value);
    const t = templates.find((x) => templateKey(x) === value);
    // The first variable is usually the customer's name.
    setParams(Object.fromEntries((t?.variables ?? []).map((v, i) => [v, params[v] ?? (i === 0 ? "contact_name" : FIXED)])));
  };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!template) return setError("Pick a template");
    setSaving(true);
    setError(null);
    const body = {
      header_filename: media && template.header_format === "DOCUMENT" ? filename : "",
      header_link: media ? link : "",
      label,
      language: template.language,
      params: Object.fromEntries(template.variables.map((v) => [v, params[v] ?? ""])),
      template: template.name,
    };
    try {
      await api(action ? `/api/whatsapp/actions/${action.id}` : "/api/whatsapp/actions", {
        body,
        method: action ? "PUT" : "POST",
      });
      toastManager.add({ title: action ? "Quick action saved" : "Quick action added", type: "success" });
      onSaved();
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  };

  return (
    <Form className="contents" onSubmit={submit}>
      <DialogHeader>
        <DialogTitle>{action ? `Edit "${action.label}"` : "New quick action"}</DialogTitle>
        <DialogDescription>
          WhatsApp only lets a business write first with a template Meta approved. Create templates in WhatsApp
          Manager; approved ones show up here.
        </DialogDescription>
      </DialogHeader>
      <DialogPanel className="flex flex-col gap-4">
        {(error || loadError) && (
          <Alert variant="error">
            <CircleAlertIcon aria-hidden="true" />
            <AlertDescription>{error ?? loadError?.message}</AlertDescription>
          </Alert>
        )}
        <Field>
          <FieldLabel>Button name</FieldLabel>
          <Input
            dir={textDir(label)}
            maxLength={60}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="e.g. Price list"
            required
            type="text"
            value={label}
          />
        </Field>
        <Field>
          <FieldLabel>Template</FieldLabel>
          <div className="flex w-full gap-2">
            {data ? (
              <Select items={templateItems} onValueChange={(v) => pickTemplate(v as string)} value={key || null}>
                <SelectTrigger className="min-w-0 flex-1">
                  <SelectValue placeholder={templates.length ? "Pick an approved template" : "No approved template"} />
                </SelectTrigger>
                <SelectPopup>
                  {templateItems.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectPopup>
              </Select>
            ) : (
              <Skeleton className="h-9 flex-1 rounded-lg" />
            )}
            <Button
              aria-label="Reload the templates"
              disabled={loading}
              onClick={() => api("/api/whatsapp/templates?refresh=true").then(reload)}
              size="icon"
              type="button"
              variant="outline"
            >
              <RefreshCwIcon aria-hidden="true" />
            </Button>
          </div>
          {action && data && !template && (
            <FieldDescription className="text-warning-foreground">
              {action.template} ({action.language}) isn't approved anymore: pick another one.
            </FieldDescription>
          )}
        </Field>

        {template && (
          <div className="flex flex-col gap-1.5 rounded-lg border bg-muted/40 p-3 text-sm">
            <span className="flex items-center gap-2 text-muted-foreground text-xs">
              {template.category && <Badge variant="outline">{template.category.toLowerCase()}</Badge>}
              {media && (
                <span className="flex items-center gap-1">
                  <FileTextIcon aria-hidden="true" className="size-3.5" />
                  Sends a {template.header_format?.toLowerCase()}
                </span>
              )}
            </span>
            {template.header_text && <p className="font-semibold">{template.header_text}</p>}
            <p className="whitespace-pre-line" dir="auto">
              {template.body}
            </p>
            {template.footer && <p className="text-muted-foreground text-xs">{template.footer}</p>}
            {template.buttons.length > 0 && (
              <p className="text-muted-foreground text-xs">Buttons: {template.buttons.map((b) => b.text).join(", ")}</p>
            )}
          </div>
        )}

        {template && media && (
          <div className="grid gap-4 sm:grid-cols-[3fr_2fr]">
            <Field>
              <FieldLabel>File link</FieldLabel>
              <Input dir="ltr" onChange={(e) => setLink(e.target.value)} placeholder="https://…/prices.pdf" required type="url" value={link} />
              <FieldDescription>A public https link WhatsApp downloads the file from.</FieldDescription>
            </Field>
            {template.header_format === "DOCUMENT" && (
              <Field>
                <FieldLabel>File name</FieldLabel>
                <Input onChange={(e) => setFilename(e.target.value)} placeholder="Prices.pdf" type="text" value={filename} />
              </Field>
            )}
          </div>
        )}

        {template?.variables.map((v) => {
          const value = params[v] ?? FIXED;
          const fixed = value.startsWith(FIXED);
          return (
            <Field key={v}>
              <FieldLabel>{variableLabel(v)}</FieldLabel>
              <div className="flex w-full flex-wrap gap-2">
                <Select
                  items={sourceItems}
                  onValueChange={(s) => setParams((p) => ({ ...p, [v]: s as string }))}
                  value={fixed ? FIXED : value}
                >
                  <SelectTrigger className="w-48">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectPopup>
                    {sourceItems.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectPopup>
                </Select>
                {fixed && (
                  <Input
                    aria-label={`${variableLabel(v)} text`}
                    className="min-w-40 flex-1"
                    dir={textDir(value.slice(FIXED.length))}
                    onChange={(e) => setParams((p) => ({ ...p, [v]: FIXED + e.target.value }))}
                    required
                    type="text"
                    value={value.slice(FIXED.length)}
                  />
                )}
              </div>
            </Field>
          );
        })}
      </DialogPanel>
      <DialogFooter>
        <DialogClose render={<Button variant="ghost" />}>Cancel</DialogClose>
        <Button disabled={!template} loading={saving} type="submit">
          {action ? "Save" : "Add quick action"}
        </Button>
      </DialogFooter>
    </Form>
  );
}
