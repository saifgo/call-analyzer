// The floating phone (bottom corner, every page): a dialer when idle, the call card while ringing or on a call.
import {
  ArrowLeftIcon,
  AudioLinesIcon,
  CalendarClockIcon,
  ExternalLinkIcon,
  HistoryIcon,
  PhoneMissedIcon,
  UserIcon,
  UserPlusIcon,
  DeleteIcon,
  GripIcon,
  MicIcon,
  MicOffIcon,
  PauseIcon,
  PhoneIcon,
  PhoneIncomingIcon,
  PhoneOffIcon,
  PlayIcon,
} from "lucide-react";
import * as React from "react";
import { AudioSettings } from "@/components/audio-settings";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverPopup, PopoverTrigger } from "@/components/ui/popover";
import { Toggle } from "@/components/ui/toggle";
import { Tooltip, TooltipPopup, TooltipTrigger } from "@/components/ui/tooltip";
import { Bidi } from "@/lib/bidi";
import { fmtDateTime, fmtRelative, shortName } from "@/lib/format";
import { type IncomingCall, useIncoming } from "@/lib/inbound";
import { href, useRoute } from "@/lib/router";
import { campaignText } from "@/lib/campaign-text";
import { type PhoneStatus, useSoftphone } from "@/lib/softphone";
import { cn } from "@/lib/utils";
import { type TKey, useT } from "@/lib/i18n";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

const STATUS: Record<PhoneStatus, { label: TKey; dot: string }> = {
  connecting: { dot: "bg-warning", label: "phone.status.connecting" },
  elsewhere: { dot: "bg-muted-foreground", label: "phone.status.elsewhere" },
  failed: { dot: "bg-destructive", label: "phone.status.failed" },
  off: { dot: "bg-muted-foreground", label: "shell.job.starting" },
  registered: { dot: "bg-success", label: "phone.status.ready" },
  unsupported: { dot: "bg-destructive", label: "phone.status.unsupported" },
};

function useSeconds(since: number | null): number {
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    if (since === null) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [since]);
  return since === null ? 0 : Math.max(0, Math.floor((now - since) / 1000));
}

function fmtDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  return `${m}:${String(seconds % 60).padStart(2, "0")}`;
}

function Keypad({ onKey }: { onKey: (key: string) => void }) {
  return (
    <div className="grid grid-cols-3 gap-1.5">
      {KEYS.map((key) => (
        <Button className="h-10 text-lg tabular-nums sm:h-9" key={key} onClick={() => onKey(key)} variant="ghost">
          {key}
        </Button>
      ))}
    </div>
  );
}

function Dialer() {
  const sp = useSoftphone();
  const [open, setOpen] = React.useState(false);
  const [number, setNumber] = React.useState("");
  const [sound, setSound] = React.useState(false);
  const { t } = useT();
  const status = { dot: STATUS[sp.status].dot, label: t(STATUS[sp.status].label) };
  const extension = sp.config?.enabled ? sp.config.extension : "";
  const dial = () => {
    if (sp.call(number)) {
      setNumber("");
      setOpen(false);
    }
  };
  return (
    <Popover
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setSound(false);
      }}
      open={open}
    >
      <Tooltip>
        <TooltipTrigger
          render={
            <PopoverTrigger
              render={
                <Button
                  aria-label={t("phone.ariaStatus", { status: status.label })}
                  className="fixed end-4 bottom-4 z-40 size-12 rounded-full shadow-lg sm:size-12"
                  size="icon-xl"
                />
              }
            />
          }
        >
          <PhoneIcon aria-hidden="true" />
          <span
            aria-hidden="true"
            className={cn("absolute end-0.5 top-0.5 size-3 rounded-full ring-2 ring-background", status.dot)}
          />
        </TooltipTrigger>
        <TooltipPopup side="inline-start">{status.label}</TooltipPopup>
      </Tooltip>
      <PopoverPopup align="end" className="w-72" side="top" sideOffset={8}>
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 text-sm">
            {sound ? (
              <>
                <Button aria-label={t("phone.backToDialer")} onClick={() => setSound(false)} size="icon-sm" variant="ghost">
                  <ArrowLeftIcon aria-hidden="true" className="rtl:rotate-180" />
                </Button>
                <span className="font-medium">{t("phone.sound")}</span>
              </>
            ) : (
              <>
                <span aria-hidden="true" className={cn("size-2 rounded-full", status.dot)} />
                <span className="font-medium">{t("phone.extension", { extension })}</span>
                <span className="ms-auto text-muted-foreground">{sp.status === "registered" ? t("phone.status.ready") : ""}</span>
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <Button aria-label={t("phone.soundSettings")} onClick={() => setSound(true)} size="icon-sm" variant="ghost" />
                    }
                  >
                    <AudioLinesIcon aria-hidden="true" />
                  </TooltipTrigger>
                  <TooltipPopup>{t("phone.soundSettings")}</TooltipPopup>
                </Tooltip>
              </>
            )}
          </div>
          {sound ? (
            <AudioSettings />
          ) : (
            <>
              {sp.status !== "registered" && (
                <p className="text-muted-foreground text-xs">{sp.error || status.label}</p>
              )}
              <form
                className="flex gap-1.5"
                onSubmit={(e) => {
                  e.preventDefault();
                  dial();
                }}
              >
                <Input
                  aria-label={t("phone.numberToCall")}
                  autoFocus
                  className="text-lg tabular-nums"
                  dir="ltr"
                  inputMode="tel"
                  onChange={(e) => setNumber(e.target.value)}
                  placeholder={t("phone.number")}
                  size="lg"
                  value={number}
                />
                <Button
                  aria-label={t("phone.deleteDigit")}
                  disabled={!number}
                  onClick={() => setNumber((n) => n.slice(0, -1))}
                  size="icon-lg"
                  variant="ghost"
                >
                  <DeleteIcon aria-hidden="true" />
                </Button>
              </form>
              <Keypad onKey={(key) => setNumber((n) => n + key)} />
              <Button className="bg-success hover:bg-success/90" disabled={!sp.ready || !number.trim()} onClick={dial} size="lg">
                <PhoneIcon aria-hidden="true" />
                {t("phone.call")}
              </Button>
            </>
          )}
        </div>
      </PopoverPopup>
    </Popover>
  );
}

function InfoRow({ icon: Icon, children, tone }: { icon: typeof UserIcon; children: React.ReactNode; tone?: "warning" }) {
  return (
    <li className={cn("flex items-start gap-1.5", tone === "warning" && "text-warning-foreground")}>
      <Icon aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
      <span className="min-w-0">{children}</span>
    </li>
  );
}

/** Who's calling: what the CRM and the desk know about them, so the agent picks up knowing. */
function CallerInfo({ incoming }: { incoming: IncomingCall }) {
  const { t } = useT();
  const route = useRoute();
  const caller = incoming.caller;
  if (!caller) return <p className="text-muted-foreground text-xs">{t("inbound.lookingUp")}</p>;
  const person = caller.people[0];
  const opportunity = person?.opportunities[0];
  const onDesk = route.page === "operations" && !route.query.get("tab");
  return (
    <div className="flex flex-col gap-2 rounded-xl bg-muted/50 p-3 text-sm">
      <ul className="flex flex-col gap-1 text-muted-foreground text-xs">
        {person ? (
          <InfoRow icon={UserIcon}>
            <Bidi as="span" className="font-medium text-foreground" text={person.name} />
            {person.city && ` · ${person.city}`}
            {opportunity?.owner && ` · ${t("inbound.owner", { name: opportunity.owner })}`}
          </InfoRow>
        ) : (
          <InfoRow icon={UserPlusIcon}>{caller.crm_error ? t("inbound.crmUnreachable") : t("inbound.notInCrm")}</InfoRow>
        )}
        {caller.last_call && (
          <InfoRow icon={HistoryIcon}>
            {t("inbound.lastCall", {
              agent: caller.last_call.agent_name,
              outcome: campaignText(caller.last_call.outcome_label),
              when: fmtRelative(caller.last_call.finished_at),
            })}
          </InfoRow>
        )}
        {caller.knows && <InfoRow icon={UserIcon}>{t("inbound.knows", { name: caller.knows.name })}</InfoRow>}
        {caller.callback && (
          <InfoRow icon={CalendarClockIcon}>
            {caller.callback.assign_to_name
              ? t("inbound.callbackFor", { name: caller.callback.assign_to_name, time: fmtDateTime(caller.callback.due_at) })
              : t("inbound.callbackAt", { time: fmtDateTime(caller.callback.due_at) })}
          </InfoRow>
        )}
        {caller.missed > 0 && (
          <InfoRow icon={PhoneMissedIcon} tone="warning">
            {t("inbound.calledBefore", { count: caller.missed })}
          </InfoRow>
        )}
      </ul>
      {incoming.op && !onDesk && (
        <Button render={<a href={href("operations")} />} size="sm" variant="outline">
          <ExternalLinkIcon aria-hidden="true" />
          {t("inbound.openOnDesk")}
        </Button>
      )}
    </div>
  );
}

function CallCard() {
  const sp = useSoftphone();
  const incoming = useIncoming();
  const [keypad, setKeypad] = React.useState(false);
  const [tones, setTones] = React.useState("");
  const [sound, setSound] = React.useState(false);
  const { t } = useT();
  const call = sp.active;
  const seconds = useSeconds(call?.answeredAt ?? null);
  if (!call) return null;
  const ringing = call.state === "ringing";
  const known = incoming?.callId === call.id ? incoming : null;
  const name = shortName(known?.caller?.people[0]?.name || call.name);
  const label = ringing
    ? t("phone.incoming")
    : call.state === "calling"
      ? t("phone.calling")
      : call.held
        ? t("phone.onHold", { time: fmtDuration(seconds) })
        : fmtDuration(seconds);
  return (
    <div
      aria-live="polite"
      className="fixed end-4 bottom-4 z-40 flex w-76 flex-col gap-4 rounded-2xl border bg-popover p-4 text-popover-foreground shadow-lg"
      role="region"
      aria-label={t("phone.call")}
    >
      <div className="flex items-center gap-3">
        <span
          className={cn(
            "flex size-10 shrink-0 items-center justify-center rounded-full bg-muted",
            ringing && "animate-pulse bg-success/16 text-success",
          )}
        >
          {ringing ? <PhoneIncomingIcon aria-hidden="true" className="size-5" /> : <PhoneIcon aria-hidden="true" className="size-5" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold text-lg tabular-nums" dir="ltr">
            {call.number}
          </div>
          <div className="truncate text-muted-foreground text-sm tabular-nums">
            {name ? `${name} · ` : ""}
            {label}
          </div>
        </div>
      </div>
      {known && <CallerInfo incoming={known} />}
      {keypad && !ringing && (
        <div className="flex flex-col gap-2">
          <div className="h-6 truncate text-center font-mono text-lg tracking-widest" dir="ltr">
            {tones}
          </div>
          <Keypad
            onKey={(key) => {
              sp.sendDtmf(key);
              setTones((prev) => (prev + key).slice(-16));
            }}
          />
        </div>
      )}
      {sound && !ringing && <AudioSettings className="rounded-xl border p-3" />}
      {ringing ? (
        <div className="grid grid-cols-2 gap-2">
          <Button onClick={sp.hangup} size="lg" variant="destructive">
            <PhoneOffIcon aria-hidden="true" />
            {t("phone.decline")}
          </Button>
          <Button className="bg-success hover:bg-success/90" onClick={sp.answer} size="lg">
            <PhoneIcon aria-hidden="true" />
            {t("phone.answer")}
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <Toggle aria-label={t("phone.mute")} onPressedChange={sp.toggleMute} pressed={call.muted} variant="outline">
            {call.muted ? <MicOffIcon aria-hidden="true" /> : <MicIcon aria-hidden="true" />}
          </Toggle>
          <Toggle
            aria-label={t("phone.hold")}
            disabled={call.state !== "active"}
            onPressedChange={sp.toggleHold}
            pressed={call.held}
            variant="outline"
          >
            {call.held ? <PlayIcon aria-hidden="true" /> : <PauseIcon aria-hidden="true" />}
          </Toggle>
          <Toggle aria-label={t("phone.keypad")} onPressedChange={setKeypad} pressed={keypad} variant="outline">
            <GripIcon aria-hidden="true" />
          </Toggle>
          <Toggle aria-label={t("phone.soundSettings")} onPressedChange={setSound} pressed={sound} variant="outline">
            <AudioLinesIcon aria-hidden="true" />
          </Toggle>
          <Button className="ms-auto" onClick={sp.hangup} variant="destructive">
            <PhoneOffIcon aria-hidden="true" />
            {t("phone.hangUp")}
          </Button>
        </div>
      )}
    </div>
  );
}

/** Nothing for accounts without a GoVoice extension. */
export function Softphone(): React.ReactElement | null {
  const sp = useSoftphone();
  if (!sp.config?.enabled) return null;
  return sp.active ? <CallCard /> : <Dialer />;
}
