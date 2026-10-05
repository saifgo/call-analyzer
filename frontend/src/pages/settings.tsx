import { DownloadIcon, EyeIcon, EyeOffIcon, LogInIcon, RefreshCwIcon, StethoscopeIcon } from "lucide-react";
import * as React from "react";
import { JobLog } from "@/components/job-log";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardPanel, CardTitle } from "@/components/ui/card";
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
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group";
import { Select, SelectItem, SelectPopup, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { toastManager } from "@/components/ui/toast";
import { api, useApi } from "@/lib/api";
import { useGoVoice } from "@/lib/govoice";
import { useJob, useOnJobFinished } from "@/lib/jobs";
import type { SettingField, WhisperModel } from "@/lib/types";

const SELECT_OPTIONS: Record<string, string[]> = {
  ANALYSIS_BACKEND: ["claude", "cursor", "auto"],
  CLAUDE_BACKEND: ["subscription", "api"],
  TRANSCRIBE_PROVIDER: ["local", "elevenlabs", "openai"],
  WHISPER_DEVICE: ["auto", "cuda", "cpu"],
  WHISPER_MODEL: ["large-v3-turbo", "large-v3", "tunisian-large-v3", "arabic-dialectal-turbo", "medium", "small"],
};
const SELECT_LABELS: Record<string, Record<string, string>> = {
  ANALYSIS_BACKEND: {
    auto: "Claude, then Cursor if unavailable",
    claude: "Claude",
    cursor: "Cursor",
  },
  CLAUDE_BACKEND: {
    api: "Claude API key",
    subscription: "Claude subscription",
  },
  WHISPER_MODEL: {
    "arabic-dialectal-turbo": "arabic-dialectal-turbo · Arabic dialects incl. Tunisian, faster",
    "large-v3": "large-v3 · most accurate standard model",
    "large-v3-turbo": "large-v3-turbo · fast, fits a 4 GB GPU",
    "tunisian-large-v3": "tunisian-large-v3 · Tunisian Derja + French, most accurate",
  },
};

/** Tunisian/dialect Whisper models must be downloaded and converted once before use. */
function WhisperModelNote({ name, saved, onInstall }: { name: string; saved: boolean; onInstall: () => void }) {
  const job = useJob();
  const { data: models, reload } = useApi<WhisperModel[]>("/api/whisper-models");
  useOnJobFinished(reload);
  const model = models?.find((m) => m.name === name);
  if (!model) return null;
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted/50 px-3 py-2 text-sm">
      <span className="text-muted-foreground">
        {model.installed ? (
          <>
            <Badge variant="success">Installed</Badge> {model.repo}
          </>
        ) : (
          <>
            Not installed yet: downloaded from {model.repo} and converted (~{model.size_gb} GB) at the first
            transcription, or now.
          </>
        )}
      </span>
      {!model.installed && (
        <Button disabled={!!job.state?.running} onClick={onInstall} size="sm" variant="outline">
          <DownloadIcon aria-hidden="true" />
          {saved ? "Install now" : "Save & install"}
        </Button>
      )}
    </div>
  );
}
const BOOLEAN_KEYS = new Set(["GOVOICE_VERIFY_SSL", "AUTO_PROCESS", "SHARE_ON_LAN", "COOKIE_SECURE"]);

function SecretInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [shown, setShown] = React.useState(false);
  return (
    <InputGroup>
      <InputGroupInput
        autoComplete="off"
        className="font-mono"
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        type={shown ? "text" : "password"}
        value={value}
      />
      <InputGroupAddon align="inline-end">
        <Button aria-label={shown ? "Hide value" : "Show value"} onClick={() => setShown((s) => !s)} size="icon-xs" variant="ghost">
          {shown ? <EyeOffIcon aria-hidden="true" /> : <EyeIcon aria-hidden="true" />}
        </Button>
      </InputGroupAddon>
    </InputGroup>
  );
}

function SettingControl({ field, value, onChange }: { field: SettingField; value: string; onChange: (v: string) => void }) {
  if (BOOLEAN_KEYS.has(field.key)) {
    const effective = (value || field.default).toLowerCase() === "true";
    return <Switch aria-label={field.key} checked={effective} onCheckedChange={(on) => onChange(on ? "true" : "false")} />;
  }
  const options = SELECT_OPTIONS[field.key];
  if (options) {
    const all = !value || options.includes(value) ? options : [value, ...options];
    const items = all.map((o) => ({ label: SELECT_LABELS[field.key]?.[o] ?? o, value: o }));
    return (
      <Select items={items} onValueChange={(v) => onChange(v as string)} value={value || field.default || options[0]}>
        <SelectTrigger aria-label={field.key}>
          <SelectValue />
        </SelectTrigger>
        <SelectPopup>
          {items.map((i) => (
            <SelectItem key={i.value} value={i.value}>
              {i.label}
            </SelectItem>
          ))}
        </SelectPopup>
      </Select>
    );
  }
  if (field.secret) return <SecretInput onChange={onChange} value={value} />;
  return (
    <Input
      aria-label={field.key}
      dir="auto"
      onChange={(e) => onChange(e.target.value)}
      placeholder={field.default}
      type="text"
      value={value}
    />
  );
}

function GoVoiceCard() {
  const { status, refresh, promptLogin } = useGoVoice();
  const [checking, setChecking] = React.useState(false);
  const check = async () => {
    setChecking(true);
    await refresh();
    setChecking(false);
  };
  const badge =
    status?.connected === true ? (
      <Badge variant="success">Connected</Badge>
    ) : status?.connected === false ? (
      <Badge variant="error">Not connected</Badge>
    ) : status ? (
      <Badge variant="warning">Unreachable</Badge>
    ) : (
      <Badge variant="outline">Checking…</Badge>
    );
  return (
    <Card>
      <CardPanel className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex items-center gap-2 font-medium">GoVoice account {badge}</div>
          <p className="text-muted-foreground text-sm">
            {status?.message ?? "Checking the saved session…"}
            {status?.checked_at && ` · checked ${new Date(status.checked_at).toLocaleTimeString()}`}. Log in to GoVoice
            and the session is saved here automatically; no need to copy cookies.
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button loading={checking} onClick={check} variant="ghost">
            <RefreshCwIcon aria-hidden="true" />
            Test
          </Button>
          <Button onClick={() => promptLogin()} variant={status?.connected === false ? "default" : "outline"}>
            <LogInIcon aria-hidden="true" />
            {status?.connected ? "Log in again" : "Log in to GoVoice"}
          </Button>
        </div>
      </CardPanel>
    </Card>
  );
}

export function SettingsPage(): React.ReactElement {
  const job = useJob();
  const { data: fields } = useApi<SettingField[]>("/api/settings");
  const [saved, setSaved] = React.useState<Record<string, string> | null>(null);
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [saving, setSaving] = React.useState(false);
  const [checkOpen, setCheckOpen] = React.useState(false);
  const { status: govoice } = useGoVoice();

  React.useEffect(() => {
    if (fields && !saved) {
      const v = Object.fromEntries(
        fields.map((f) => [f.key, f.value || (SELECT_OPTIONS[f.key] ? f.default : f.value)]),
      );
      setSaved(v);
      setValues(v);
    }
  }, [fields, saved]);

  // A GoVoice login (or the server keeping the session alive) updates GOVOICE_COOKIE in .env: show the new value.
  const cookieCheckedAt = govoice?.checked_at;
  React.useEffect(() => {
    if (!cookieCheckedAt || !saved) return;
    api<SettingField[]>("/api/settings").then((latest) => {
      const cookie = latest.find((f) => f.key === "GOVOICE_COOKIE")?.value ?? "";
      setSaved((prev) => (prev ? { ...prev, GOVOICE_COOKIE: cookie } : prev));
      setValues((prev) => (saved && prev.GOVOICE_COOKIE === saved.GOVOICE_COOKIE ? { ...prev, GOVOICE_COOKIE: cookie } : prev));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cookieCheckedAt]);

  const sections = React.useMemo(() => [...new Set((fields ?? []).map((f) => f.section))], [fields]);
  const dirtyKeys = saved ? Object.keys(values).filter((k) => values[k] !== saved[k]) : [];
  const dirty = dirtyKeys.length > 0;

  const save = async () => {
    setSaving(true);
    try {
      // Only send what changed, so values the server updated meanwhile (the GoVoice cookie) aren't overwritten.
      await api("/api/settings", { body: Object.fromEntries(dirtyKeys.map((k) => [k, values[k]])), method: "PUT" });
      setSaved(values);
      toastManager.add({ description: "Used by the next job.", title: "Settings saved", type: "success" });
      return true;
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: "Couldn't save settings", type: "error" });
      return false;
    } finally {
      setSaving(false);
    }
  };

  const saveAndInstall = async () => {
    if (dirty && !(await save())) return;
    await job.start(["install-model"]);
  };

  const saveAndCheck = async () => {
    if (dirty && !(await save())) return;
    if (await job.start(["check"])) setCheckOpen(true);
  };

  return (
    <>
      <PageHeader
        actions={
          <Button disabled={!!job.state?.running} onClick={saveAndCheck} variant="outline">
            <StethoscopeIcon aria-hidden="true" />
            {dirty ? "Save & check setup" : "Check setup"}
          </Button>
        }
        description="Saved to the .env file. Changes are used by the next job; sharing and port changes need a restart."
        title="Settings"
      />

      {!fields || !saved ? (
        <div className="flex flex-col gap-6">
          <Skeleton className="h-96 rounded-2xl" />
          <Skeleton className="h-72 rounded-2xl" />
        </div>
      ) : (
        <div className="flex flex-col gap-6 pb-20">
          <GoVoiceCard />
          {sections.map((section) => (
            <Card key={section}>
              <CardHeader>
                <CardTitle className="text-base">{section}</CardTitle>
              </CardHeader>
              <CardPanel className="flex flex-col">
                {fields
                  .filter((f) => f.section === section)
                  .map((f, i) => (
                    <React.Fragment key={f.key}>
                      {i > 0 && <Separator className="my-4" />}
                      <Field className="grid gap-x-8 gap-y-2 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] md:items-start">
                        <div className="flex flex-col gap-1.5">
                          <FieldLabel className="font-mono text-xs">
                            {f.key}
                            {values[f.key] !== saved[f.key] && (
                              <span aria-label="Changed" className="size-1.5 rounded-full bg-warning" />
                            )}
                          </FieldLabel>
                          {f.help && <FieldDescription className="text-xs">{f.help}</FieldDescription>}
                        </div>
                        <div className="flex min-w-0 flex-col gap-2">
                          <SettingControl
                            field={f}
                            onChange={(v) => setValues((prev) => ({ ...prev, [f.key]: v }))}
                            value={values[f.key] ?? ""}
                          />
                          {f.key === "WHISPER_MODEL" && (
                            <WhisperModelNote
                              name={values[f.key] ?? ""}
                              onInstall={saveAndInstall}
                              saved={!dirty}
                            />
                          )}
                        </div>
                      </Field>
                    </React.Fragment>
                  ))}
              </CardPanel>
            </Card>
          ))}
        </div>
      )}

      {dirty && (
        <div className="pointer-events-none sticky bottom-4 z-10 -mt-20 flex justify-center">
          <Card className="pointer-events-auto flex-row items-center gap-3 rounded-xl px-4 py-2.5 shadow-lg/5">
            <Badge variant="warning">
              {dirtyKeys.length} unsaved {dirtyKeys.length === 1 ? "change" : "changes"}
            </Badge>
            <Button onClick={() => setValues(saved ?? {})} size="sm" variant="ghost">
              Discard
            </Button>
            <Button loading={saving} onClick={save} size="sm">
              Save changes
            </Button>
          </Card>
        </div>
      )}

      <Dialog onOpenChange={setCheckOpen} open={checkOpen}>
        <DialogPopup className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {job.state?.running && <Spinner className="size-4" />}
              Setup check
            </DialogTitle>
            <DialogDescription>Verifies the GoVoice cookie, speech-to-text and the analysis backend with the saved settings.</DialogDescription>
          </DialogHeader>
          <DialogPanel>
            <JobLog empty="Starting…" lines={job.lines} />
          </DialogPanel>
          <DialogFooter>
            <DialogClose render={<Button variant="ghost" />}>Close</DialogClose>
          </DialogFooter>
        </DialogPopup>
      </Dialog>
    </>
  );
}
