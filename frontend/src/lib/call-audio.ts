// Cleans the softphone's audio in the browser, with no server or outside service. The agent's microphone goes
// through noise suppression (RNNoise for Standard, GTCRN for Strong) and a voice gate (voice-gate.worklet.js) before
// JsSIP sends it, so the customer hears the agent without the keyboard, the fans or colleagues talking between the
// agent's sentences. The customer's audio can get the same noise suppression before it plays. Each agent's settings
// stay in their browser.
import {
  GtcrnWorkletNode,
  loadGtcrn,
  loadRnnoise,
  RnnoiseWorkletNode,
} from "@sapphi-red/web-noise-suppressor";
import gtcrnWasmUrl from "@sapphi-red/web-noise-suppressor/gtcrn.wasm?url";
import gtcrnWorkletUrl from "@sapphi-red/web-noise-suppressor/gtcrnWorklet.js?url";
import rnnoiseWasmUrl from "@sapphi-red/web-noise-suppressor/rnnoise.wasm?url";
import rnnoiseSimdWasmUrl from "@sapphi-red/web-noise-suppressor/rnnoise_simd.wasm?url";
import rnnoiseWorkletUrl from "@sapphi-red/web-noise-suppressor/rnnoiseWorklet.js?url";
import gateWorkletUrl from "./voice-gate.worklet.js?url&no-inline";

/** off: only the browser's own processing; standard: RNNoise (light); strong: GTCRN (cleaner, more CPU). */
export type NoiseMode = "off" | "standard" | "strong";

export type AudioSettings = {
  noise: NoiseMode;
  /** Lower the line while the agent isn't speaking (removes background voices between sentences). */
  gate: boolean;
  /** Level (dBFS) the agent's voice must reach to open the gate. Lower = more sensitive. */
  gateDb: number;
  /** Noise suppression on the customer's audio too. */
  cleanIncoming: boolean;
};

/** Reported by the voice gate a few times a second: the level after noise suppression and whether it lets it through. */
export type MicLevel = { level: number; open: boolean };

export const DEFAULT_AUDIO: AudioSettings = { cleanIncoming: false, gate: true, gateDb: -35, noise: "standard" };
export const GATE_RANGE = { max: -20, min: -65 } as const;

const STORAGE_KEY = "softphone-audio";

export function loadAudioSettings(): AudioSettings {
  try {
    return { ...DEFAULT_AUDIO, ...JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") };
  } catch {
    return DEFAULT_AUDIO;
  }
}

export function saveAudioSettings(settings: AudioSettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

// The browser's own clean-up, asked for explicitly. voiceIsolation is Chrome's built-in voice focus where the
// platform has it; browsers that don't know a constraint ignore it.
const MIC_CONSTRAINTS = {
  autoGainControl: true,
  channelCount: 1,
  echoCancellation: true,
  noiseSuppression: true,
  voiceIsolation: true,
} as MediaTrackConstraints;

type Denoiser = AudioWorkletNode & { destroy(): void };

// The models load once per page (a few hundred KB, served with the app) and are shared by every call.
let rnnoiseBinary: Promise<ArrayBuffer> | null = null;
let gtcrnBinary: Promise<ArrayBuffer> | null = null;

function binary(mode: Exclude<NoiseMode, "off">): Promise<ArrayBuffer> {
  if (mode === "standard") {
    rnnoiseBinary ??= loadRnnoise({ simdUrl: rnnoiseSimdWasmUrl, url: rnnoiseWasmUrl }).catch((err) => {
      rnnoiseBinary = null;
      throw err;
    });
    return rnnoiseBinary;
  }
  gtcrnBinary ??= loadGtcrn({ url: gtcrnWasmUrl }).catch((err) => {
    gtcrnBinary = null;
    throw err;
  });
  return gtcrnBinary;
}

/** Fetch the model the settings use ahead of the first call, so dialing doesn't wait for it. */
export function preloadCallAudio(settings: AudioSettings): void {
  const modes = new Set<NoiseMode>([settings.noise, settings.cleanIncoming ? "standard" : "off"]);
  for (const mode of modes) if (mode !== "off") binary(mode).catch(() => {});
}

const loadedModules = new WeakMap<AudioContext, Map<string, Promise<void>>>();

function addModule(ctx: AudioContext, url: string): Promise<void> {
  let modules = loadedModules.get(ctx);
  if (!modules) loadedModules.set(ctx, (modules = new Map()));
  let loading = modules.get(url);
  if (!loading) modules.set(url, (loading = ctx.audioWorklet.addModule(url)));
  return loading;
}

async function makeDenoiser(ctx: AudioContext, mode: Exclude<NoiseMode, "off">): Promise<Denoiser> {
  const [wasmBinary] = await Promise.all([
    binary(mode),
    addModule(ctx, mode === "standard" ? rnnoiseWorkletUrl : gtcrnWorkletUrl),
  ]);
  return mode === "standard"
    ? new RnnoiseWorkletNode(ctx, { maxChannels: 1, wasmBinary })
    : new GtcrnWorkletNode(ctx, { maxChannels: 1, wasmBinary });
}

/**
 * One call's audio (or a microphone test): the cleaned microphone stream to send, the optional clean-up of the
 * customer's audio, and the level meter. Settings apply live, without renegotiating the call. close() when done.
 */
export class CallAudio {
  /** What to send: the cleaned microphone, or the raw one when the browser can't run the processing. */
  readonly stream: MediaStream;
  private readonly mic: MediaStream;
  private readonly ctx: AudioContext | null;
  private source: MediaStreamAudioSourceNode | null = null;
  private out: MediaStreamAudioDestinationNode | null = null;
  private gate: AudioWorkletNode | null = null;
  private denoiser: Denoiser | null = null;
  private denoiserMode: NoiseMode = "off";
  private remote: { stream: MediaStream; element: HTMLAudioElement } | null = null;
  private remoteChain: { source: MediaStreamAudioSourceNode; denoiser: Denoiser } | null = null;
  private monitoring = false;
  private settings: AudioSettings;
  private version = 0;
  private closed = false;
  private readonly listeners = new Set<(level: MicLevel) => void>();

  private constructor(mic: MediaStream, ctx: AudioContext | null, settings: AudioSettings) {
    this.mic = mic;
    this.ctx = ctx;
    this.settings = settings;
    if (!ctx) {
      this.stream = mic;
      return;
    }
    this.source = ctx.createMediaStreamSource(mic);
    const out = ctx.createMediaStreamDestination();
    out.channelCount = 1;
    this.stream = out.stream;
    this.out = out;
  }

  /** Open the microphone. Call it straight from the click (dial / answer): the audio engine needs that gesture. */
  static async open(settings: AudioSettings): Promise<CallAudio> {
    let ctx: AudioContext | null = null;
    try {
      ctx = new AudioContext({ latencyHint: "interactive", sampleRate: 48000 });
    } catch (err) {
      console.warn("Softphone audio: no Web Audio, sending the microphone as is", err);
    }
    let mic: MediaStream;
    try {
      mic = await navigator.mediaDevices.getUserMedia({ audio: MIC_CONSTRAINTS, video: false });
    } catch (err) {
      void ctx?.close();
      throw err;
    }
    const audio = new CallAudio(mic, ctx, settings);
    if (!ctx) return audio;
    void ctx.resume();
    await audio.apply(settings);
    if (audio.processing) return audio;
    // The gate didn't start (worklets blocked or failing): send the microphone as is rather than silence.
    void ctx.close();
    return new CallAudio(mic, null, settings);
  }

  get current(): AudioSettings {
    return this.settings;
  }

  /** Change the settings in the middle of a call (or a test). */
  async apply(settings: AudioSettings): Promise<void> {
    this.settings = settings;
    const ctx = this.ctx;
    if (!ctx || !this.source || !this.out || this.closed) return;
    const version = ++this.version;
    try {
      if (!this.gate) {
        await addModule(ctx, gateWorkletUrl);
        if (this.closed || this.gate) return;
        const gate = new AudioWorkletNode(ctx, "call-analyzer-voice-gate", {
          channelCount: 1,
          channelCountMode: "explicit",
          numberOfOutputs: 1,
          outputChannelCount: [1],
        });
        gate.port.onmessage = (e: MessageEvent<MicLevel>) => {
          for (const listener of this.listeners) listener(e.data);
        };
        gate.connect(this.out);
        if (this.monitoring) gate.connect(ctx.destination);
        this.source.connect(gate);
        this.gate = gate;
      }
      this.gate.port.postMessage({ enabled: settings.gate, thresholdDb: settings.gateDb });

      if (settings.noise !== this.denoiserMode) {
        const next = settings.noise === "off" ? null : await makeDenoiser(ctx, settings.noise);
        if (this.closed || version !== this.version) {
          next?.destroy();
          return; // newer settings arrived meanwhile and will wire their own
        }
        this.source.disconnect();
        this.denoiser?.disconnect();
        this.denoiser?.destroy();
        if (next) this.source.connect(next).connect(this.gate);
        else this.source.connect(this.gate);
        this.denoiser = next;
        this.denoiserMode = settings.noise;
      }
      await this.applyRemote();
    } catch (err) {
      // A model that won't load must not break the call: the microphone keeps going through what's wired.
      console.warn("Softphone audio: couldn't apply the noise settings", err);
    }
  }

  /** The customer's audio: played through the noise suppression when cleanIncoming is on, else by the element. */
  attachRemote(stream: MediaStream, element: HTMLAudioElement): void {
    this.remote = { element, stream };
    // The element keeps playing the stream (Chrome only feeds a remote WebRTC stream to Web Audio while an element
    // plays it); applyRemote mutes it when the cleaned copy plays instead.
    element.srcObject = stream;
    void this.applyRemote().catch((err) => console.warn("Softphone audio: customer clean-up failed", err));
  }

  private async applyRemote(): Promise<void> {
    const ctx = this.ctx;
    const remote = this.remote;
    if (!ctx || !remote || this.closed) return;
    if (this.settings.cleanIncoming && !this.remoteChain) {
      const denoiser = await makeDenoiser(ctx, "standard");
      if (this.closed || this.remote !== remote || this.remoteChain || !this.settings.cleanIncoming) {
        denoiser.destroy();
        return;
      }
      const source = ctx.createMediaStreamSource(remote.stream);
      source.connect(denoiser).connect(ctx.destination);
      this.remoteChain = { denoiser, source };
      remote.element.muted = true;
    } else if (!this.settings.cleanIncoming && this.remoteChain) {
      this.dropRemoteChain();
    }
  }

  private dropRemoteChain(): void {
    if (!this.remoteChain) return;
    this.remoteChain.source.disconnect();
    this.remoteChain.denoiser.disconnect();
    this.remoteChain.denoiser.destroy();
    this.remoteChain = null;
    if (this.remote) this.remote.element.muted = false;
  }

  /** Play the cleaned microphone back to the agent (microphone test; headphones, or it feeds back). */
  setMonitor(on: boolean): void {
    this.monitoring = on;
    if (!this.ctx || !this.gate) return;
    if (on) this.gate.connect(this.ctx.destination);
    else {
      this.gate.disconnect();
      if (this.out) this.gate.connect(this.out);
    }
  }

  onLevel(listener: (level: MicLevel) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** True when the microphone goes through the clean-up (false: the browser couldn't run it). */
  get processing(): boolean {
    return this.gate !== null;
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.listeners.clear();
    this.dropRemoteChain();
    this.denoiser?.destroy();
    for (const track of this.mic.getTracks()) track.stop();
    for (const track of this.stream.getTracks()) track.stop();
    void this.ctx?.close();
  }
}
