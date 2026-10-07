"""Voice tone: what the recording itself sounds like, as opposed to what the transcript says.

The speech is cut at pauses (VAD) into windows of a few seconds. Each window gets
- an emotion from an audio classification model (VOICE_MODEL, a Hugging Face "audio-classification" model, run as
  ONNX: see voice_models.py), and
- acoustic measurements: loudness and pitch variation (monotone voices are flat, tense ones are loud and high).
This is the "voice" step of the pipeline (download, voice, transcribe, analyze). It runs on this server or on a remote
agent (VOICE_RUNS_ON, see dispatch.py); the result is stored on the call (calls.voice) and given to the analysis,
which turns it into the voice tone score. The model is converted once where torch is installed (the server) and
downloaded from there by agents, so they need no torch. Without the model only the acoustic measurements are made
(a remote agent then fails the task instead of sending those).


Phone recordings from GoVoice are mono, so windows cannot be assigned to the agent or the customer here; the
analysis does that from the transcript timestamps. A stereo recording with distinct channels is measured per channel.
"""
import json
import sys
import threading
from datetime import datetime
from pathlib import Path

import numpy as np

from .config import settings

SAMPLE_RATE = 16000
VERSION = 1
MIN_WINDOW_S = 1.0  # shorter pieces of speech ("ok", a cough) say nothing about tone
TARGET_WINDOWS = 120  # long calls get longer windows so the timeline stays readable
PITCH_FRAME, PITCH_HOP = 640, 320  # 40 ms / 20 ms
PITCH_LAGS = (SAMPLE_RATE // 400, SAMPLE_RATE // 70)  # 70-400 Hz
LONG_PAUSE_S = 4.0  # dead air the customer notices

# Labels differ between models (superb: neu/hap/ang/sad); the analysis and the UI use these names.
CANONICAL = {
    "neu": "neutral", "neutral": "neutral", "calm": "neutral",
    "hap": "happy", "happy": "happy", "happiness": "happy", "joy": "happy", "excited": "happy",
    "enthusiasm": "happy", "pleased": "happy",
    "relaxed": "neutral",
    "tension": "tense", "tense": "tense", "stress": "tense", "stressed": "tense",
    "ang": "angry", "angry": "angry", "anger": "angry",
    "sad": "sad", "sadness": "sad",
    "fea": "fear", "fear": "fear", "fearful": "fear", "anxious": "fear",
    "dis": "disgust", "disgust": "disgust",
    "sur": "surprise", "surprise": "surprise", "surprised": "surprise",
}

ANGRY = ("angry", "tense")  # what counts as the voice sounding angry or tense

_lock = threading.Lock()
_classifier: dict[tuple, object] = {}  # (model name, model folder) -> classifier, or None when it could not be loaded
_warned: set[str] = set()


def _warn(text: str):
    if text not in _warned:
        _warned.add(text)
        print(f"Voice analysis: {text}", file=sys.stderr)


def load_classifier(cfg, *, strict: bool = False):
    """The emotion classifier, loaded once per process: the ONNX model, converted here or downloaded from the server
    first (voice_models.install). When that isn't possible this returns None with a warning and the acoustic
    measurements are still made, or with `strict` (a remote agent) raises instead of sending degraded results."""
    from . import voice_models

    key = (cfg.voice_model, cfg.whisper_model_dir)
    with _lock:
        if key not in _classifier or (strict and _classifier[key] is None):
            try:
                folder = voice_models.install(cfg.voice_model, lambda text: print(f"Voice analysis: {text}"), cfg)
                _classifier[key] = voice_models.OnnxClassifier(folder)
            except Exception as exc:
                if strict:
                    raise
                _classifier[key] = None
                _warn(f"no emotion model, so only loudness and pitch are measured: {exc}")
        return _classifier[key]


def _emotions(clf, window: np.ndarray) -> dict[str, float]:
    scores: dict[str, float] = {}
    for item in clf({"raw": window, "sampling_rate": SAMPLE_RATE}):
        label = CANONICAL.get(item["label"].lower(), item["label"].lower())
        scores[label] = scores.get(label, 0.0) + float(item["score"])
    return {k: round(v, 3) for k, v in sorted(scores.items(), key=lambda kv: -kv[1])}


def _pitch(window: np.ndarray) -> float | None:
    """Spread of the voice's pitch in semitones (about 1-2 = monotone, 3-5 = lively), or None if too little of the
    window is voiced to tell. Autocorrelation on 40 ms frames: crude, but the same for every call."""
    if len(window) < PITCH_FRAME * 4:
        return None
    frames = np.lib.stride_tricks.sliding_window_view(window, PITCH_FRAME)[::PITCH_HOP]
    frames = (frames - frames.mean(axis=1, keepdims=True)) * np.hanning(PITCH_FRAME)
    spectrum = np.fft.rfft(frames, 2048, axis=1)
    corr = np.fft.irfft(spectrum * np.conj(spectrum), axis=1)
    energy = corr[:, 0]
    lo, hi = PITCH_LAGS
    band = corr[:, lo:hi]
    best = band.argmax(axis=1)
    peak = band[np.arange(len(band)), best] / np.maximum(energy, 1e-9)
    loud = energy > max(energy.max() * 0.02, 1e-9)  # skip the near-silent frames between words
    voiced = (peak > 0.4) & loud
    if voiced.sum() < 8:
        return None
    f0 = SAMPLE_RATE / (best[voiced] + lo)
    return float(np.std(12 * np.log2(f0 / np.median(f0))))


def _db(window: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(window ** 2)) + 1e-9))


def _mmss(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _tracks(path: Path) -> list[tuple[str, np.ndarray]]:
    """The recording as 16 kHz mono tracks: one per channel when the two channels hold different voices (a PBX that
    records each side separately), otherwise the single mix."""
    import av
    from faster_whisper import decode_audio

    with av.open(str(path)) as container:
        channels = container.streams.audio[0].channels
    if channels == 2:
        left, right = decode_audio(str(path), sampling_rate=SAMPLE_RATE, split_stereo=True)
        if not np.allclose(left, right, atol=1e-3):
            return [("channel_L", left), ("channel_R", right)]
    return [("mixed", decode_audio(str(path), sampling_rate=SAMPLE_RATE))]


def _speech_windows(audio: np.ndarray) -> list[tuple[float, float]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    longest = min(15.0, max(6.0, len(audio) / SAMPLE_RATE / TARGET_WINDOWS))
    spans = get_speech_timestamps(audio, VadOptions(
        min_silence_duration_ms=300, speech_pad_ms=100, min_speech_duration_ms=300, max_speech_duration_s=longest))
    windows = [(s["start"] / SAMPLE_RATE, s["end"] / SAMPLE_RATE) for s in spans]
    return [(a, b) for a, b in windows if b - a >= MIN_WINDOW_S]


def _summary(windows: list[dict], total_s: float, speech_spans: list[tuple[float, float]]) -> dict:
    speech_s = sum(w["end"] - w["start"] for w in windows)
    summary: dict = {"speech_seconds": round(speech_s, 1), "speech_share": round(speech_s / total_s, 2) if total_s else 0}
    gaps = [b[0] - a[1] for a, b in zip(speech_spans, speech_spans[1:])]
    gaps += [speech_spans[0][0]] if speech_spans else []
    summary["long_pauses"] = sum(g >= LONG_PAUSE_S for g in gaps)
    summary["longest_pause_s"] = round(max(gaps, default=0), 1)
    if len(windows) >= 2:
        summary["loudness_std_db"] = round(float(np.std([w["db"] for w in windows])), 1)
    spreads = [w["pitch_st"] for w in windows if w.get("pitch_st") is not None]
    if spreads:
        summary["pitch_variation_st"] = round(float(np.mean(spreads)), 1)
    with_emotion = [w for w in windows if w.get("emotion")]
    if with_emotion and speech_s:
        share: dict[str, float] = {}
        for w in with_emotion:
            for label, p in w["emotion"].items():
                share[label] = share.get(label, 0.0) + p * (w["end"] - w["start"])
        weight = sum(w["end"] - w["start"] for w in with_emotion)
        summary["emotion_share"] = {k: round(v / weight, 2) for k, v in sorted(share.items(), key=lambda kv: -kv[1])}
        summary["dominant"] = next(iter(summary["emotion_share"]))
        summary["angry_seconds"] = round(sum(w["end"] - w["start"] for w in with_emotion
                                             if sum(w["emotion"].get(label, 0) for label in ANGRY) >= 0.5), 1)
    return summary


def analyze_audio(path: Path, cfg=None, *, strict: bool = False) -> dict:
    """Measure one recording. The result is plain JSON (see the module docstring for what is in it). `strict`: fail when
    the emotion model isn't available instead of measuring loudness and pitch only."""
    cfg = cfg or settings
    clf = load_classifier(cfg, strict=strict)
    tracks = []
    duration = 0.0
    for label, audio in _tracks(path):
        duration = max(duration, len(audio) / SAMPLE_RATE)
        spans = _speech_windows(audio)
        windows = []
        for start, end in spans:
            piece = audio[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)]
            window = {"start": round(start, 1), "end": round(end, 1), "db": round(_db(piece), 1)}
            if (pitch := _pitch(piece)) is not None:
                window["pitch_st"] = round(pitch, 1)
            if clf:
                window["emotion"] = _emotions(clf, piece)
            windows.append(window)
        tracks.append({"label": label, "windows": windows,
                       "summary": _summary(windows, len(audio) / SAMPLE_RATE, spans)})
    return {"version": VERSION, "model": cfg.voice_model if clf else None, "duration": round(duration, 1),
            "separated": len(tracks) > 1, "tracks": tracks}


# --- Stored with the call, and shown to the analysis --------------------------------------------

def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure(conn, calls, *, redo: bool = False, cfg=None) -> int:
    """Measure the calls that have a downloaded recording and no voice data yet (all of them with redo), here on this
    machine: the host's side of the voice step. A call whose audio can't be read is skipped with a message: it never
    stops the pipeline."""
    cfg = cfg or settings
    if not cfg.voice_analysis:
        return 0
    todo = [c for c in calls if c["audio_path"] and Path(c["audio_path"]).exists() and (redo or not c["voice"])]
    if todo:
        print(f"Measuring the voice of {len(todo)} recordings...")
    done = 0
    for i, call in enumerate(todo, 1):
        try:
            data = analyze_audio(Path(call["audio_path"]), cfg)
        except Exception as exc:
            print(f"  [{i}/{len(todo)}] voice FAILED {call['filename']}: {exc}", file=sys.stderr)
            continue
        conn.execute("UPDATE calls SET voice=?, voice_at=? WHERE id=?", (json.dumps(data), _now(), call["id"]))
        conn.commit()
        done += 1
        print(f"  [{i}/{len(todo)}] voice {call['filename']}")
    return done


def of_call(call) -> dict | None:
    """The voice data of a call row or of the dict an agent receives; None when there isn't any."""
    try:
        raw = call["voice"]
    except (KeyError, IndexError):
        return None
    if not raw:
        return None
    return raw if isinstance(raw, dict) else json.loads(raw)


def describe(voice: dict) -> str:
    """The voice data as text for the analysis prompt: a summary per track, then one line per window."""
    if voice.get("model"):
        head = f"Emotion classifier: {voice['model']}"
    else:
        head = "No emotion classifier was available: only loudness and pitch were measured"
    lines = [head, "Windows are stretches of speech between pauses; db = loudness (relative, compare within this call), "
             "pitch_var = pitch spread in semitones (1-2 monotone, 3-5 lively)."]
    for track in voice["tracks"]:
        who = ("both speakers mixed (mono recording, not separated)" if track["label"] == "mixed"
               else f"{track['label']} only")
        s = track["summary"]
        facts = [f"speech {s.get('speech_seconds', 0)}s of {voice['duration']}s", f"{s.get('long_pauses', 0)} pauses "
                 f"over {LONG_PAUSE_S:g}s (longest {s.get('longest_pause_s', 0)}s)"]
        if "loudness_std_db" in s:
            facts.append(f"loudness varies {s['loudness_std_db']} dB")
        if "pitch_variation_st" in s:
            facts.append(f"pitch_var {s['pitch_variation_st']}")
        if "emotion_share" in s:
            share = ", ".join(f"{k} {int(v * 100)}%" for k, v in s["emotion_share"].items() if v >= 0.02)
            facts.append(f"emotion share: {share}; {s['angry_seconds']}s sounding angry")
        lines.append(f"\n[{track['label']}] {who}: " + "; ".join(facts))
        for w in track["windows"]:
            parts = [f"{w['db']:.0f}dB"]
            if "pitch_st" in w:
                parts.append(f"pitch_var {w['pitch_st']}")
            if w.get("emotion"):
                parts.append(", ".join(f"{k} {p:.2f}" for k, p in list(w["emotion"].items())[:2]))
            lines.append(f"{_mmss(w['start'])}-{_mmss(w['end'])}  " + " | ".join(parts))
    return "\n".join(lines)
