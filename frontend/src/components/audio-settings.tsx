// The softphone's sound settings (noise reduction, the voice gate against background voices, cleaning the customer's
// audio) with a live level meter: during a call it shows the call's microphone, otherwise a microphone test.
import { HeadphonesIcon, MicIcon } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { toastManager } from "@/components/ui/toast";
import { CallAudio, GATE_RANGE, type MicLevel, type NoiseMode } from "@/lib/call-audio";
import { useSoftphone } from "@/lib/softphone";
import { cn } from "@/lib/utils";

const NOISE: { value: NoiseMode; label: string; hint: string }[] = [
  { hint: "Only the browser's own noise reduction.", label: "Off", value: "off" },
  { hint: "Removes keyboards, fans, street noise and most chatter. Light on the PC.", label: "Standard", value: "standard" },
  { hint: "Cleaner voice, removes more background voices. Uses more of the PC.", label: "Strong", value: "strong" },
];

const METER_FLOOR = -70; // dB at the meter's left edge

function meterPercent(db: number): number {
  return Math.min(100, Math.max(0, ((db - METER_FLOOR) / -METER_FLOOR) * 100));
}

function useLevel(audio: CallAudio | null): MicLevel | null {
  const [level, setLevel] = React.useState<MicLevel | null>(null);
  React.useEffect(() => audio?.onLevel(setLevel), [audio]);
  return level;
}

/** The voice level after noise reduction, the gate threshold, and whether the gate lets the voice through. */
function LevelMeter({ audio, threshold, gate }: { audio: CallAudio; threshold: number; gate: boolean }) {
  const level = useLevel(audio);
  const open = level?.open ?? false;
  return (
    <div className="flex flex-col gap-1">
      <div aria-hidden="true" className="relative h-2 overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-75",
            open ? "bg-success" : "bg-muted-foreground/48",
          )}
          style={{ width: `${level ? meterPercent(level.level) : 0}%` }}
        />
        {gate && (
          <div className="absolute inset-y-0 w-0.5 bg-foreground" style={{ left: `${meterPercent(threshold)}%` }} />
        )}
      </div>
      <p aria-live="off" className="text-muted-foreground text-xs">
        {!audio.processing
          ? "This browser can't clean the microphone: it's sent as is."
          : !gate
            ? "Your microphone level"
            : open
              ? "Your voice goes through"
              : "Line lowered: speak to open it"}
      </p>
    </div>
  );
}

/** Opens the microphone with the current settings while it's on (no call), so the agent can tune them. */
function MicTest() {
  const sp = useSoftphone();
  const [test, setTest] = React.useState<CallAudio | null>(null);
  const [starting, setStarting] = React.useState(false);
  const [monitor, setMonitor] = React.useState(false);
  const testRef = React.useRef<CallAudio | null>(null);

  React.useEffect(() => () => testRef.current?.close(), []);
  React.useEffect(() => {
    void test?.apply(sp.audio);
  }, [sp.audio, test]);

  const stop = () => {
    testRef.current?.close();
    testRef.current = null;
    setTest(null);
    setMonitor(false);
  };
  const start = async () => {
    setStarting(true);
    try {
      const audio = await CallAudio.open(sp.audio);
      testRef.current = audio;
      setTest(audio);
    } catch (err) {
      toastManager.add({ description: String(err), title: "The microphone didn't start", type: "error" });
    } finally {
      setStarting(false);
    }
  };

  if (!test)
    return (
      <Button disabled={starting} onClick={start} size="sm" variant="outline">
        <MicIcon aria-hidden="true" />
        Test my microphone
      </Button>
    );
  return (
    <div className="flex flex-col gap-2">
      <LevelMeter audio={test} key="test" gate={sp.audio.gate} threshold={sp.audio.gateDb} />
      <div className="flex items-center gap-2">
        <Toggle
          aria-label="Hear yourself"
          onPressedChange={(on) => {
            test.setMonitor(on);
            setMonitor(on);
          }}
          pressed={monitor}
          size="sm"
          variant="outline"
        >
          <HeadphonesIcon aria-hidden="true" />
          Hear myself
        </Toggle>
        <Button className="ms-auto" onClick={stop} size="sm" variant="ghost">
          Stop test
        </Button>
      </div>
      {monitor && <p className="text-muted-foreground text-xs">Use headphones, or the speakers feed back into the microphone.</p>}
    </div>
  );
}

export function AudioSettings({ className }: { className?: string }) {
  const sp = useSoftphone();
  const { audio, setAudio } = sp;
  const id = React.useId();
  const noise = NOISE.find((n) => n.value === audio.noise) ?? NOISE[1];
  return (
    <div className={cn("flex flex-col gap-4 text-sm", className)}>
      <div className="flex flex-col gap-2">
        <span className="font-medium">Noise reduction</span>
        <ToggleGroup
          aria-label="Noise reduction"
          className="w-full"
          onValueChange={(v) => {
            if (v[0]) setAudio({ noise: v[0] as NoiseMode });
          }}
          size="sm"
          value={[audio.noise]}
          variant="outline"
        >
          {NOISE.map((n) => (
            <ToggleGroupItem className="flex-1" key={n.value} value={n.value}>
              {n.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <p className="text-muted-foreground text-xs">{noise.hint}</p>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <Label className="flex-1" htmlFor={`${id}-gate`}>
            Cut background voices
          </Label>
          <Switch checked={audio.gate} id={`${id}-gate`} onCheckedChange={(on) => setAudio({ gate: on })} />
        </div>
        <p className="text-muted-foreground text-xs">
          Lowers your line while you're not speaking, so colleagues near you aren't heard between your sentences.
        </p>
        {audio.gate && (
          <div className="flex flex-col gap-1.5">
            <div className="flex justify-between text-muted-foreground text-xs">
              <span>More sensitive</span>
              <span>Stricter</span>
            </div>
            <Slider
              aria-label="Voice gate threshold"
              max={GATE_RANGE.max}
              min={GATE_RANGE.min}
              onValueChange={(v) => setAudio({ gateDb: Array.isArray(v) ? v[0] : v })}
              step={1}
              value={audio.gateDb}
            />
            <p className="text-muted-foreground text-xs">
              Speak normally: the bar should turn green on your voice and stay grey when only the room is heard.
            </p>
          </div>
        )}
      </div>

      {sp.callAudio ? (
        <LevelMeter audio={sp.callAudio} key="call" gate={audio.gate} threshold={audio.gateDb} />
      ) : (
        <MicTest />
      )}

      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Label className="flex-1" htmlFor={`${id}-incoming`}>
            Clean the customer's audio
          </Label>
          <Switch
            checked={audio.cleanIncoming}
            id={`${id}-incoming`}
            onCheckedChange={(on) => setAudio({ cleanIncoming: on })}
          />
        </div>
        <p className="text-muted-foreground text-xs">
          Removes noise around the customer (street, car). Best with a headset.
        </p>
      </div>
    </div>
  );
}
