import { scoreVariant } from "@/components/call-badges";
import { Badge } from "@/components/ui/badge";
import { Meter, MeterIndicator, MeterLabel, MeterTrack } from "@/components/ui/meter";
import { Tooltip, TooltipPopup, TooltipTrigger } from "@/components/ui/tooltip";
import { Bidi } from "@/lib/bidi";
import { humanize } from "@/lib/format";
import type { VoiceData, VoiceTone } from "@/lib/types";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";

const SCORE_COLOR = { error: "bg-destructive", success: "bg-success", warning: "bg-warning" };

const EMOTION_COLOR: Record<string, string> = {
  angry: "bg-destructive",
  happy: "bg-success",
  neutral: "bg-muted-foreground/40",
  sad: "bg-info",
  tense: "bg-destructive",
};

const BAD_TONES = new Set(["tense_impatient", "irritated_angry", "frustrated", "angry"]);

function mmss(seconds: number) {
  const s = Math.floor(seconds);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function topEmotion(emotion: Record<string, number> | undefined) {
  const first = emotion && Object.entries(emotion)[0];
  return first ? { label: first[0], p: first[1] } : null;
}

/** One coloured block per stretch of speech, placed where it is in the call. */
function Timeline({ data, label }: { data: VoiceData; label: string }) {
  const track = data.tracks.find((t) => t.label === label);
  if (!track || !data.duration) return null;
  return (
    <div className="relative h-5 overflow-hidden rounded-md bg-muted/60">
      {track.windows.map((w) => {
        const top = topEmotion(w.emotion);
        const color = top ? (EMOTION_COLOR[top.label] ?? "bg-warning") : "bg-muted-foreground/40";
        return (
          <Tooltip key={w.start}>
            <TooltipTrigger
              render={
                <span
                  className={cn("absolute inset-y-0 opacity-80", color, top && top.p < 0.5 && "opacity-40")}
                  style={{ insetInlineStart: `${(w.start / data.duration) * 100}%`, width: `${((w.end - w.start) / data.duration) * 100}%` }}
                />
              }
            />
            <TooltipPopup>
              <span dir="ltr">
                {mmss(w.start)}–{mmss(w.end)}
              </span>
              {top && ` · ${humanize(top.label)} ${Math.round(top.p * 100)}%`} · {Math.round(w.db)} dB
              {w.pitch_st !== undefined && ` · ${t("voice.pitchSt", { st: w.pitch_st })}`}
            </TooltipPopup>
          </Tooltip>
        );
      })}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-muted-foreground text-xs">{label}</span>
      <span className="font-medium text-sm tabular-nums">{value}</span>
    </div>
  );
}

/** Voice tone score (from the analysis) and the audio measurements behind it. */
export function VoicePanel({ tone, data }: { tone: VoiceTone | null | undefined; data: VoiceData | null }) {
  if (!tone && !data) return null;
  return (
    <section className="flex flex-col gap-4">
      <h3 className="font-heading font-semibold text-sm">{t("voice.title")}</h3>
      {tone && (
        <div className="flex flex-col gap-3 rounded-xl border p-4">
          <Meter max={10} value={tone.score}>
            <div className="flex items-center justify-between gap-2">
              <MeterLabel className="font-normal">{t("voice.howAgentSounds")}</MeterLabel>
              <span className="font-medium text-sm tabular-nums">
                {tone.score}
                <span className="font-normal text-muted-foreground">/10</span>
              </span>
            </div>
            <MeterTrack className="rounded-full">
              <MeterIndicator className={cn("rounded-full", SCORE_COLOR[scoreVariant(tone.score)])} />
            </MeterTrack>
          </Meter>
          <div className="flex flex-wrap gap-1.5">
            <Badge variant={BAD_TONES.has(tone.agent_tone) ? "warning" : "secondary"}>{t("voice.agentTone", { tone: humanize(tone.agent_tone) })}</Badge>
            <Badge variant="outline">{t("voice.customerTone", { tone: humanize(tone.customer_tone) })}</Badge>
            {tone.confidence !== "high" && <Badge variant="outline">{t(tone.confidence === "low" ? "voice.confidenceLow" : "voice.confidenceMedium")}</Badge>}
          </div>
          <Bidi className="text-sm leading-relaxed" text={tone.evidence} />
          {tone.coaching_tip && <Bidi className="text-muted-foreground text-sm" text={tone.coaching_tip} />}
        </div>
      )}
      {data && (
        <div className="flex flex-col gap-3">
          {!tone && (
            <p className="text-muted-foreground text-sm">
              {t("voice.measuredAfter")}
            </p>
          )}
          {data.tracks.map((track) => {
            const s = track.summary;
            return (
              <div className="flex flex-col gap-2" key={track.label}>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                  <span className="font-medium">
                    {track.label === "mixed" ? t("voice.bothSpeakers") : humanize(track.label)}
                  </span>
                  <span className="text-muted-foreground">
                    {data.model ? t("voice.emotionModel", { model: data.model }) : t("voice.onlyLoudness")}
                  </span>
                </div>
                <Timeline data={data} label={track.label} />
                {s.emotion_share && (
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                    {Object.entries(s.emotion_share)
                      .filter(([, v]) => v >= 0.02)
                      .map(([label, v]) => (
                        <span className="flex items-center gap-1.5" key={label}>
                          <span aria-hidden="true" className={cn("size-2 rounded-full", EMOTION_COLOR[label] ?? "bg-warning")} />
                          {humanize(label)} <span className="text-muted-foreground tabular-nums">{Math.round(v * 100)}%</span>
                        </span>
                      ))}
                  </div>
                )}
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <Stat label={t("voice.speaking")} value={t("voice.ofTheCall", { pct: Math.round(s.speech_share * 100) })} />
                  <Stat
                    label={t("voice.longPauses")}
                    value={`${s.long_pauses}${s.long_pauses ? ` · ${t("voice.maxSeconds", { s: s.longest_pause_s })}` : ""}`}
                  />
                  {s.pitch_variation_st !== undefined && (
                    <Stat label={t("voice.pitchVariation")} value={t("voice.semitones", { st: s.pitch_variation_st })} />
                  )}
                  {s.loudness_std_db !== undefined && <Stat label={t("voice.loudnessVariation")} value={`${s.loudness_std_db} dB`} />}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
