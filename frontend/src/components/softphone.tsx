// The floating phone (bottom corner, every page): a dialer when idle, the call card while ringing or on a call.
import {
  ArrowLeftIcon,
  AudioLinesIcon,
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
import { type PhoneStatus, useSoftphone } from "@/lib/softphone";
import { cn } from "@/lib/utils";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

const STATUS: Record<PhoneStatus, { label: string; dot: string }> = {
  connecting: { dot: "bg-warning", label: "Connecting to GoVoice…" },
  elsewhere: { dot: "bg-muted-foreground", label: "The phone is open in another tab" },
  failed: { dot: "bg-destructive", label: "Not connected" },
  off: { dot: "bg-muted-foreground", label: "Starting…" },
  registered: { dot: "bg-success", label: "Ready" },
  unsupported: { dot: "bg-destructive", label: "Open the app over HTTPS to use the phone" },
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
  const status = STATUS[sp.status];
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
                  aria-label={`Phone: ${status.label}`}
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
        <TooltipPopup side="left">{status.label}</TooltipPopup>
      </Tooltip>
      <PopoverPopup align="end" className="w-72" side="top" sideOffset={8}>
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 text-sm">
            {sound ? (
              <>
                <Button aria-label="Back to the dialer" onClick={() => setSound(false)} size="icon-sm" variant="ghost">
                  <ArrowLeftIcon aria-hidden="true" />
                </Button>
                <span className="font-medium">Sound</span>
              </>
            ) : (
              <>
                <span aria-hidden="true" className={cn("size-2 rounded-full", status.dot)} />
                <span className="font-medium">Extension {extension}</span>
                <span className="ms-auto text-muted-foreground">{sp.status === "registered" ? "Ready" : ""}</span>
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <Button aria-label="Sound settings" onClick={() => setSound(true)} size="icon-sm" variant="ghost" />
                    }
                  >
                    <AudioLinesIcon aria-hidden="true" />
                  </TooltipTrigger>
                  <TooltipPopup>Sound settings</TooltipPopup>
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
                  aria-label="Number to call"
                  autoFocus
                  className="text-lg tabular-nums"
                  dir="ltr"
                  inputMode="tel"
                  onChange={(e) => setNumber(e.target.value)}
                  placeholder="Number"
                  size="lg"
                  value={number}
                />
                <Button
                  aria-label="Delete last digit"
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
                Call
              </Button>
            </>
          )}
        </div>
      </PopoverPopup>
    </Popover>
  );
}

function CallCard() {
  const sp = useSoftphone();
  const [keypad, setKeypad] = React.useState(false);
  const [tones, setTones] = React.useState("");
  const [sound, setSound] = React.useState(false);
  const call = sp.active;
  const seconds = useSeconds(call?.answeredAt ?? null);
  if (!call) return null;
  const ringing = call.state === "ringing";
  const label = ringing
    ? "Incoming call"
    : call.state === "calling"
      ? "Calling…"
      : call.held
        ? `On hold · ${fmtDuration(seconds)}`
        : fmtDuration(seconds);
  return (
    <div
      aria-live="polite"
      className="fixed end-4 bottom-4 z-40 flex w-76 flex-col gap-4 rounded-2xl border bg-popover p-4 text-popover-foreground shadow-lg"
      role="region"
      aria-label="Call"
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
            {call.name ? `${call.name} · ` : ""}
            {label}
          </div>
        </div>
      </div>
      {keypad && !ringing && (
        <div className="flex flex-col gap-2">
          <div className="h-6 truncate text-center font-mono text-lg tracking-widest" dir="ltr">
            {tones}
          </div>
          <Keypad
            onKey={(key) => {
              sp.sendDtmf(key);
              setTones((t) => (t + key).slice(-16));
            }}
          />
        </div>
      )}
      {sound && !ringing && <AudioSettings className="rounded-xl border p-3" />}
      {ringing ? (
        <div className="grid grid-cols-2 gap-2">
          <Button onClick={sp.hangup} size="lg" variant="destructive">
            <PhoneOffIcon aria-hidden="true" />
            Decline
          </Button>
          <Button className="bg-success hover:bg-success/90" onClick={sp.answer} size="lg">
            <PhoneIcon aria-hidden="true" />
            Answer
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <Toggle aria-label="Mute" onPressedChange={sp.toggleMute} pressed={call.muted} variant="outline">
            {call.muted ? <MicOffIcon aria-hidden="true" /> : <MicIcon aria-hidden="true" />}
          </Toggle>
          <Toggle
            aria-label="Hold"
            disabled={call.state !== "active"}
            onPressedChange={sp.toggleHold}
            pressed={call.held}
            variant="outline"
          >
            {call.held ? <PlayIcon aria-hidden="true" /> : <PauseIcon aria-hidden="true" />}
          </Toggle>
          <Toggle aria-label="Keypad" onPressedChange={setKeypad} pressed={keypad} variant="outline">
            <GripIcon aria-hidden="true" />
          </Toggle>
          <Toggle aria-label="Sound settings" onPressedChange={setSound} pressed={sound} variant="outline">
            <AudioLinesIcon aria-hidden="true" />
          </Toggle>
          <Button className="ms-auto" onClick={sp.hangup} variant="destructive">
            <PhoneOffIcon aria-hidden="true" />
            Hang up
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
