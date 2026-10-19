import {
  CpuIcon,
  DownloadIcon,
  EyeIcon,
  EyeOffIcon,
  LogInIcon,
  MonitorSmartphoneIcon,
  RefreshCwIcon,
  StethoscopeIcon,
} from "lucide-react";
import * as React from "react";
import { JobLog } from "@/components/job-log";
import { WhatsAppActions } from "@/components/whatsapp-actions";
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
import { fmtTime } from "@/lib/format";
import { useGoVoice } from "@/lib/govoice";
import { getLocale, labels, t, type TKey } from "@/lib/i18n";
import { useJob, useOnJobFinished } from "@/lib/jobs";
import { settingsHelp as arHelp } from "@/locales/ar/settings-help";
import { settingsHelp as frHelp } from "@/locales/fr/settings-help";
import { href } from "@/lib/router";
import { RUNS_ON_LABELS, STEP_NAMES, useWorkers, WORKER_STEPS } from "@/lib/workers";
import type { SettingField, WhisperModel } from "@/lib/types";

const SELECT_OPTIONS: Record<string, string[]> = {
  ANALYSIS_BACKEND: ["claude", "cursor", "auto"],
  ANALYZE_RUNS_ON: ["host", "agent", "auto"],
  TRANSCRIBE_RUNS_ON: ["host", "agent", "auto"],
  VOICE_MODEL: [
    "superb/wav2vec2-base-superb-er",
    "Aniemore/wav2vec2-emotion-v1-crosslingual",
    "Lajavaness/wav2vec2-lg-xlsr-fr-speech-emotion-recognition",
  ],
  VOICE_RUNS_ON: ["host", "agent", "auto"],
  CLAUDE_BACKEND: ["subscription", "api"],
  TRANSCRIBE_PROVIDER: ["local", "elevenlabs", "openai"],
  WHISPER_DEVICE: ["auto", "cuda", "cpu"],
  WHISPER_MODEL: ["large-v3-turbo", "large-v3", "tunisian-large-v3", "arabic-dialectal-turbo", "medium", "small"],
};
const SELECT_LABELS: Record<string, Record<string, string>> = {
  ANALYZE_RUNS_ON: RUNS_ON_LABELS,
  TRANSCRIBE_RUNS_ON: RUNS_ON_LABELS,
  VOICE_RUNS_ON: RUNS_ON_LABELS,
  ANALYSIS_BACKEND: labels({
    auto: "settings.opt.analysisAuto",
    claude: "settings.opt.claude",
    cursor: "settings.opt.cursor",
  }),
  CLAUDE_BACKEND: labels({
    api: "settings.opt.claudeApi",
    subscription: "settings.opt.claudeSubscription",
  }),
  VOICE_MODEL: labels({
    "Aniemore/wav2vec2-emotion-v1-crosslingual": "settings.opt.voiceAniemore",
    "Lajavaness/wav2vec2-lg-xlsr-fr-speech-emotion-recognition": "settings.opt.voiceLajavaness",
    "superb/wav2vec2-base-superb-er": "settings.opt.voiceSuperb",
  }),
  WHISPER_MODEL: labels({
    "arabic-dialectal-turbo": "settings.opt.whisperArabic",
    "large-v3": "settings.opt.whisperLarge",
    "large-v3-turbo": "settings.opt.whisperTurbo",
    "tunisian-large-v3": "settings.opt.whisperTunisian",
  }),
};

// Section names as the server sends them (the "# --- Name ---" headings in .env.example).
const SECTION_LABELS: Record<string, TKey> = {
  Analysis: "settings.section.analysis",
  "Call desk": "settings.section.callDesk",
  CRM: "settings.section.crm",
  "CRM (Twenty)": "settings.section.crmTwenty",
  General: "settings.section.general",
  "GoVoice (VoIP manager)": "settings.section.govoice",
  "Ongoing mode": "settings.section.ongoing",
  "Phone system": "settings.section.phoneSystem",
  "Remote agents": "nav.agents",
  Security: "settings.section.security",
  "Sharing & hosting": "settings.section.sharing",
  Softphone: "settings.section.softphone",
  "Speech-to-text": "settings.section.speechToText",
  "Voice analysis": "workers.step.voice",
  WhatsApp: "settings.section.whatsapp",
};
const sectionLabel = (section: string) => (SECTION_LABELS[section] ? t(SECTION_LABELS[section]) : section);

/** A setting's help: translated from src/locales/<lang>/settings-help.ts, else the English comment in .env.example. */
function helpText(field: SettingField): string {
  const locale = getLocale();
  const help = locale === "fr" ? frHelp : locale === "ar" ? arHelp : null;
  return help?.[field.key] ?? field.help;
}

/** Models that must be downloaded and converted once before use (Tunisian Whisper models, the voice emotion model):
 * says whether the selected one is installed on this server, and offers to install it. */
function ModelNote({
  endpoint,
  name,
  onInstall,
  saved,
  when,
}: {
  endpoint: string;
  name: string;
  onInstall: () => void;
  saved: boolean;
  /** When it would otherwise be installed by itself, e.g. "at the first transcription". */
  when: string;
}) {
  const job = useJob();
  const { data: models, reload } = useApi<WhisperModel[]>(endpoint);
  useOnJobFinished(reload);
  const model = models?.find((m) => m.name === name);
  if (!model) return null;
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted/50 px-3 py-2 text-sm">
      <span className="text-muted-foreground">
        {model.installed ? (
          <>
            <Badge variant="success">{t("settings.installed")}</Badge> {model.repo}
          </>
        ) : (
          t("settings.notInstalled", { repo: model.repo, size: model.size_gb, when })
        )}
      </span>
      {!model.installed && (
        <Button disabled={!!job.state?.running} onClick={onInstall} size="sm" variant="outline">
          <DownloadIcon aria-hidden="true" />
          {saved ? t("settings.installNow") : t("settings.saveInstall")}
        </Button>
      )}
    </div>
  );
}
const BOOLEAN_KEYS = new Set(["GOVOICE_VERIFY_SSL", "AUTO_PROCESS", "SHARE_ON_LAN", "COOKIE_SECURE", "VOICE_ANALYSIS", "DESK_EARNED_BREAK"]);

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
        <Button aria-label={shown ? t("settings.hideValue") : t("settings.showValue")} onClick={() => setShown((s) => !s)} size="icon-xs" variant="ghost">
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

/** The agents connected right now, shown above the settings that choose between this server and agents. */
function AgentsSummary() {
  const { state } = useWorkers();
  if (!state) return <Skeleton className="h-16 rounded-xl" />;
  const { workers } = state;
  const online = workers.filter((w) => w.online && w.enabled).length;
  return (
    <div className="flex flex-col gap-3 rounded-xl border bg-muted/32 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 font-medium text-sm">
          <MonitorSmartphoneIcon aria-hidden="true" className="size-4 text-muted-foreground" />
          {workers.length === 0 ? t("settings.noAgents") : t("settings.agentsOnlineOf", { count: workers.length, online })}
        </div>
        <Button render={<a href={href("agents")} />} size="sm" variant="outline">
          {workers.length === 0 ? t("settings.addAgent") : t("settings.manageAgents")}
        </Button>
      </div>
      {workers.length > 0 && (
        <ul className="flex flex-col gap-2">
          {workers.map((w) => (
            <li className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm" key={w.id}>
              <span className="flex min-w-0 items-center gap-2">
                <span
                  aria-hidden="true"
                  className={`size-2 shrink-0 rounded-full ${w.online ? (w.enabled ? "bg-success" : "bg-warning") : "bg-muted-foreground/40"}`}
                />
                <span className="truncate font-medium" dir="auto">
                  {w.name}
                </span>
              </span>
              <span className="text-muted-foreground text-xs">
                {!w.online
                  ? t("settings.worker.offline")
                  : w.enabled
                    ? w.running.length
                      ? t("settings.worker.working", { count: w.running.length })
                      : t("settings.worker.idle")
                    : t("settings.worker.paused")}
              </span>
              {w.info.gpu !== undefined && (
                <Badge variant="outline">
                  <CpuIcon aria-hidden="true" />
                  {w.info.gpu ? "GPU" : "CPU"}
                </Badge>
              )}
              {WORKER_STEPS.map(
                (step) =>
                  w.info.capabilities?.[step] && (
                    <Badge key={step} variant={w.ready[step] ? "success" : "warning"}>
                      {STEP_NAMES[step]}
                      {w.ready[step] ? "" : ` · ${t("settings.notReady")}`}
                    </Badge>
                  ),
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
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
      <Badge variant="success">{t("settings.connected")}</Badge>
    ) : status?.connected === false ? (
      <Badge variant="error">{t("phone.status.failed")}</Badge>
    ) : status ? (
      <Badge variant="warning">{t("settings.unreachable")}</Badge>
    ) : (
      <Badge variant="outline">{t("settings.checking")}</Badge>
    );
  return (
    <Card>
      <CardPanel className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex items-center gap-2 font-medium">
            {t("settings.govoiceAccount")} {badge}
          </div>
          <p className="text-muted-foreground text-sm">
            {status?.message ?? t("settings.checkingSession")}
            {status?.checked_at && ` · ${t("settings.checkedAt", { time: fmtTime(status.checked_at) })}`}.{" "}
            {t("settings.govoiceHint")}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button loading={checking} onClick={check} variant="ghost">
            <RefreshCwIcon aria-hidden="true" />
            {t("settings.test")}
          </Button>
          <Button onClick={() => promptLogin()} variant={status?.connected === false ? "default" : "outline"}>
            <LogInIcon aria-hidden="true" className="rtl:-scale-x-100" />
            {status?.connected ? t("settings.logInAgain") : t("govoice.logIn")}
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
      toastManager.add({ description: t("settings.usedByNextJob"), title: t("settings.saved"), type: "success" });
      return true;
    } catch (err) {
      toastManager.add({ description: (err as Error).message, title: t("settings.couldntSave"), type: "error" });
      return false;
    } finally {
      setSaving(false);
    }
  };

  const saveAndInstall = async (command: "install-model" | "install-voice-model") => {
    if (dirty && !(await save())) return;
    await job.start([command]);
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
            {dirty ? t("settings.saveCheck") : t("pipeline.checkSetup")}
          </Button>
        }
        description={t("settings.description")}
        title={t("nav.settings")}
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
                <CardTitle className="text-base">{sectionLabel(section)}</CardTitle>
              </CardHeader>
              <CardPanel className="flex flex-col">
                {section === "Remote agents" && (
                  <>
                    <AgentsSummary />
                    <Separator className="my-4" />
                  </>
                )}
                {fields
                  .filter((f) => f.section === section)
                  .map((f, i) => (
                    <React.Fragment key={f.key}>
                      {i > 0 && <Separator className="my-4" />}
                      <Field className="grid gap-x-8 gap-y-2 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] md:items-start">
                        <div className="flex flex-col gap-1.5">
                          <FieldLabel className="font-mono text-xs" dir="ltr">
                            {f.key}
                            {values[f.key] !== saved[f.key] && (
                              <span aria-label={t("settings.changed")} className="size-1.5 rounded-full bg-warning" />
                            )}
                          </FieldLabel>
                          {f.help && <FieldDescription className="text-xs">{helpText(f)}</FieldDescription>}
                        </div>
                        <div className="flex min-w-0 flex-col gap-2">
                          <SettingControl
                            field={f}
                            onChange={(v) => setValues((prev) => ({ ...prev, [f.key]: v }))}
                            value={values[f.key] ?? ""}
                          />
                          {f.key === "WHISPER_MODEL" && (
                            <ModelNote
                              endpoint="/api/whisper-models"
                              name={values[f.key] ?? ""}
                              onInstall={() => saveAndInstall("install-model")}
                              saved={!dirty}
                              when={t("settings.whenTranscription")}
                            />
                          )}
                          {f.key === "VOICE_MODEL" && (
                            <ModelNote
                              endpoint="/api/voice-models"
                              name={values[f.key] || f.default}
                              onInstall={() => saveAndInstall("install-voice-model")}
                              saved={!dirty}
                              when={t("settings.whenVoice")}
                            />
                          )}
                        </div>
                      </Field>
                    </React.Fragment>
                  ))}
                {section === "WhatsApp" && (
                  <>
                    <Separator className="my-4" />
                    <WhatsAppActions refreshKey={saving} />
                  </>
                )}
              </CardPanel>
            </Card>
          ))}
        </div>
      )}

      {dirty && (
        <div className="pointer-events-none sticky bottom-4 z-10 -mt-20 flex justify-center">
          <Card className="pointer-events-auto flex-row items-center gap-3 rounded-xl px-4 py-2.5 shadow-lg/5">
            <Badge variant="warning">
              {t("settings.unsavedCount", { count: dirtyKeys.length })}
            </Badge>
            <Button onClick={() => setValues(saved ?? {})} size="sm" variant="ghost">
              {t("common.discard")}
            </Button>
            <Button loading={saving} onClick={save} size="sm">
              {t("settings.saveChanges")}
            </Button>
          </Card>
        </div>
      )}

      <Dialog onOpenChange={setCheckOpen} open={checkOpen}>
        <DialogPopup className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {job.state?.running && <Spinner className="size-4" />}
              {t("jobs.step.check")}
            </DialogTitle>
            <DialogDescription>{t("settings.checkHint")}</DialogDescription>
          </DialogHeader>
          <DialogPanel>
            <JobLog empty={t("shell.job.starting")} lines={job.lines} />
          </DialogPanel>
          <DialogFooter>
            <DialogClose render={<Button variant="ghost" />}>{t("common.close")}</DialogClose>
          </DialogFooter>
        </DialogPopup>
      </Dialog>
    </>
  );
}
