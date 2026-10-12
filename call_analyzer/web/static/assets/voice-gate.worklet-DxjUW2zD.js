// Voice gate (AudioWorklet, plain JS so the browser loads it as is): lowers the agent's line to a quiet floor
// while their level stays under the threshold, so colleagues talking in the room don't reach the customer between
// the agent's sentences. The audio runs ~10 ms behind the level detector, so the gate is already open when a word
// starts and its first syllable isn't cut. Posts { level, open } a few times a second for the level meter.
const LOOKAHEAD = 512; // samples (~10.7 ms at 48 kHz)
const FLOOR = 0.05; // gain while closed (-26 dB): quiet, but the line doesn't sound dead
const HOLD_SECONDS = 0.35; // stay open through the short pauses inside a sentence
const CLOSE_MARGIN_DB = 6; // close a few dB under the open threshold so a level near it doesn't flutter
const SMOOTH_SECONDS = 0.025; // the level is averaged over ~25 ms, so a single loud syllable from the room doesn't open it
const REPORT_SECONDS = 0.06;

class VoiceGate extends AudioWorkletProcessor {
  constructor() {
    super();
    this.enabled = true;
    this.openDb = -35;
    this.open = false;
    this.quietFor = 0;
    this.gain = 1;
    this.delay = new Float32Array(LOOKAHEAD);
    this.pos = 0;
    this.attack = 1 - Math.exp(-1 / (0.004 * sampleRate));
    this.release = 1 - Math.exp(-1 / (0.12 * sampleRate));
    this.power = 0;
    this.smooth = 1 - Math.exp(-128 / (SMOOTH_SECONDS * sampleRate));
    this.peakDb = -100;
    this.sinceReport = 0;
    this.port.onmessage = (e) => {
      if (typeof e.data.enabled === "boolean") this.enabled = e.data.enabled;
      if (typeof e.data.thresholdDb === "number") this.openDb = e.data.thresholdDb;
    };
  }

  process(inputs, outputs) {
    const input = inputs[0] && inputs[0][0];
    const output = outputs[0];
    const n = output[0].length;
    let sum = 0;
    if (input) for (let i = 0; i < n; i++) sum += input[i] * input[i];
    this.power += (sum / n - this.power) * this.smooth;
    const db = 10 * Math.log10(this.power + 1e-12);

    if (db > this.openDb) {
      this.open = true;
      this.quietFor = 0;
    } else if (db < this.openDb - CLOSE_MARGIN_DB) {
      this.quietFor += n;
      if (this.quietFor > HOLD_SECONDS * sampleRate) this.open = false;
    }
    const target = !this.enabled || this.open ? 1 : FLOOR;

    const out = output[0];
    for (let i = 0; i < n; i++) {
      const delayed = this.delay[this.pos];
      this.delay[this.pos] = input ? input[i] : 0;
      this.pos = (this.pos + 1) % LOOKAHEAD;
      this.gain += (target - this.gain) * (target > this.gain ? this.attack : this.release);
      out[i] = delayed * this.gain;
    }
    for (let c = 1; c < output.length; c++) output[c].set(out);

    this.peakDb = Math.max(this.peakDb, db);
    this.sinceReport += n;
    if (this.sinceReport >= REPORT_SECONDS * sampleRate) {
      this.port.postMessage({ level: this.peakDb, open: !this.enabled || this.open });
      this.peakDb = -100;
      this.sinceReport = 0;
    }
    return true;
  }
}

registerProcessor("call-analyzer-voice-gate", VoiceGate);
