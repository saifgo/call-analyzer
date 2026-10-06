"""Speech-to-text. Claude reads text, so each recording is transcribed first.

Default is local Whisper (faster-whisper): free, runs on this machine's GPU or CPU.
ElevenLabs / OpenAI are optional paid alternatives.
"""
import glob
import os
import re
import sys
import threading
from pathlib import Path

import requests

from .config import settings


def _fmt_ts(seconds: float) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


# --- Local Whisper ---------------------------------------------------------------------------

# (model, device setting, model folder) -> (WhisperModel, "GPU" or "CPU"). Only one model stays in memory: an
# agent can be switched to another model between two jobs, which then replaces the loaded one.
_models: dict[tuple, tuple] = {}
_batched: dict[tuple, object] = {}
_model_lock = threading.Lock()  # one GPU/CPU model, one transcription at a time


def _key(cfg) -> tuple:
    return (cfg.whisper_model, cfg.whisper_device, cfg.whisper_model_dir)


def _add_cuda_dlls():
    """Make the CUDA libraries (nvidia-cublas/cudnn) visible on Windows: the pip-installed ones, or the ones the
    GPU build of the installed agent ships next to its program."""
    roots = [os.path.join(sys.prefix, "Lib", "site-packages")]
    if getattr(sys, "frozen", False):
        roots = [getattr(sys, "_MEIPASS", ""), os.path.dirname(sys.executable)]
    for root in roots:
        for d in glob.glob(os.path.join(root, "nvidia", "*", "bin")):
            os.add_dll_directory(d)
            os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]


def _whisper(cfg):
    key = _key(cfg)
    if key not in _models:
        _models.clear()
        _batched.clear()
        if os.name == "nt":
            _add_cuda_dlls()
        from faster_whisper import WhisperModel

        from .whisper_models import resolve

        model = resolve(cfg.whisper_model, cfg=cfg)  # dialect models are downloaded + converted on first use
        device = cfg.whisper_device
        if device in ("auto", "cuda"):
            try:
                _models[key] = (WhisperModel(model, device="cuda", compute_type="int8",
                                             download_root=cfg.whisper_model_dir), "GPU")
                print(f"Whisper {cfg.whisper_model} loaded on GPU")
                return _models[key][0]
            except Exception as exc:
                if device == "cuda":
                    raise
                print(f"GPU unavailable ({exc}); using CPU, this is slower")
        _models[key] = (WhisperModel(model, device="cpu", compute_type="int8",
                                     download_root=cfg.whisper_model_dir, cpu_threads=os.cpu_count() or 4), "CPU")
        print(f"Whisper {cfg.whisper_model} loaded on CPU")
    return _models[key][0]


# Whisper sometimes emits stray CJK/Cyrillic/Hangul characters or digit loops on noisy 8 kHz phone audio.
_JUNK_SCRIPTS = re.compile(r"[Ѐ-ӿ　-鿿가-힯]+")
_REPEATS = re.compile(r"(.)\1{5,}")
_WORD_LOOPS = re.compile(r"(\S+)(?:\s+\1){3,}")  # "كلمة كلمة كلمة كلمة ..." -> "كلمة كلمة"


def _clean(text: str) -> str:
    text = _JUNK_SCRIPTS.sub("", text)
    text = _REPEATS.sub(r"\1\1\1", text)
    text = _WORD_LOOPS.sub(r"\1 \1", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _dialect_segments(audio, cfg) -> list[tuple[float, str]]:
    """Fine-tuned dialect models were trained without timestamps: cut the audio at pauses (VAD) and decode each
    piece greedily, as their authors recommend. Gives ~10 s lines and is much faster than long-form decoding."""
    from faster_whisper import BatchedInferencePipeline

    model = _whisper(cfg)
    if _key(cfg) not in _batched:
        _batched[_key(cfg)] = BatchedInferencePipeline(model)
    segments, _ = _batched[_key(cfg)].transcribe(
        audio,
        language=cfg.whisper_language or "ar",
        # No WHISPER_PROMPT: these models weren't trained with prompts and start looping on a word.
        batch_size=4,  # fits a 4 GB GPU
        beam_size=1,
        chunk_length=10,
        vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 200},
        condition_on_previous_text=False,
        no_speech_threshold=0.5,
        compression_ratio_threshold=2.4,
        repetition_penalty=1.1,
    )
    lines = [(s.start, _clean(s.text)) for s in segments]
    return [(start, text) for start, text in lines if text]


def _whisper_segments(audio, cfg) -> list[tuple[float, str]]:
    from .whisper_models import DIALECT_MODELS

    if cfg.whisper_model in DIALECT_MODELS:
        return _dialect_segments(audio, cfg)
    segments, _ = _whisper(cfg).transcribe(
        audio,
        language=cfg.whisper_language or None,
        initial_prompt=cfg.whisper_prompt or None,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 200},
        beam_size=5,
        # Settings that reduce invented text during silences and hold music.
        condition_on_previous_text=False,
        no_speech_threshold=0.5,
        compression_ratio_threshold=2.0,
        log_prob_threshold=-1.0,
        repetition_penalty=1.1,
        word_timestamps=True,
        hallucination_silence_threshold=1.0,
    )
    lines = [(s.start, _clean(s.text)) for s in segments]
    return [(start, text) for start, text in lines if text]


def _local(path: Path, cfg) -> str:
    import av
    import numpy as np
    from faster_whisper import decode_audio

    with av.open(str(path)) as container:
        channels = container.streams.audio[0].channels

    with _model_lock:
        if channels == 2:
            # Many PBXs record caller and callee on separate channels: that gives perfect speaker separation.
            left, right = decode_audio(str(path), split_stereo=True)
            if not np.allclose(left, right, atol=1e-3):
                lines = [(t, "channel_L", text) for t, text in _whisper_segments(left, cfg)]
                lines += [(t, "channel_R", text) for t, text in _whisper_segments(right, cfg)]
                lines.sort(key=lambda line: line[0])
                return "\n".join(f"[{_fmt_ts(t)}] {who}: {text}" for t, who, text in lines)
        # Mono (or identical channels): no speaker labels; Claude infers who is speaking from context.
        return "\n".join(f"[{_fmt_ts(t)}] {text}" for t, text in _whisper_segments(str(path), cfg))


# --- Paid APIs (optional) ---------------------------------------------------------------------

def _elevenlabs(path: Path, cfg) -> str:
    if not cfg.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is empty")
    with open(path, "rb") as fh:
        resp = requests.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": cfg.elevenlabs_api_key},
            data={"model_id": cfg.elevenlabs_model, "diarize": "true", "num_speakers": "2",
                  "tag_audio_events": "false"},
            files={"file": (path.name, fh, "audio/mpeg")},
            timeout=600,
        )
    resp.raise_for_status()
    body = resp.json()

    # Group words into speaker turns: "[00:12] speaker_0: ..."
    lines, current_speaker, current_words, turn_start = [], None, [], 0.0
    for word in body.get("words", []):
        if word.get("type") == "audio_event":
            continue
        speaker = word.get("speaker_id") or "speaker"
        if speaker != current_speaker and word.get("type") == "word":
            if current_words:
                lines.append(f"[{_fmt_ts(turn_start)}] {current_speaker}: {''.join(current_words).strip()}")
            current_speaker, current_words, turn_start = speaker, [], word.get("start", 0)
        current_words.append(word.get("text", ""))
    if current_words:
        lines.append(f"[{_fmt_ts(turn_start)}] {current_speaker}: {''.join(current_words).strip()}")
    return "\n".join(lines) if lines else body.get("text", "")


def _openai(path: Path, cfg) -> str:
    if not cfg.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is empty")
    with open(path, "rb") as fh:
        resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {cfg.openai_api_key}"},
            data={"model": cfg.openai_transcribe_model},
            files={"file": (path.name, fh, "audio/mpeg")},
            timeout=600,
        )
    resp.raise_for_status()
    return resp.json().get("text", "")


PROVIDERS = {"local": _local, "elevenlabs": _elevenlabs, "openai": _openai}


def transcriber_label(cfg=None) -> str:
    """Who produced the transcript, stored with it (e.g. "Whisper large-v3-turbo (local, GPU)")."""
    cfg = cfg or settings
    provider = cfg.transcribe_provider
    if provider == "local":
        device = _models.get(_key(cfg), (None, None))[1]
        return f"Whisper {cfg.whisper_model} (local{', ' + device if device else ''})"
    if provider == "elevenlabs":
        return f"ElevenLabs {cfg.elevenlabs_model}"
    if provider == "openai":
        return f"OpenAI {cfg.openai_transcribe_model}"
    return provider


def transcribe(path: Path, cfg=None) -> str:
    """Transcribe a recording. `cfg` is a Settings object (default: this process's settings); an agent passes
    the server's defaults merged with its own overrides."""
    cfg = cfg or settings
    try:
        provider = PROVIDERS[cfg.transcribe_provider]
    except KeyError:
        raise RuntimeError(f"Unknown TRANSCRIBE_PROVIDER={cfg.transcribe_provider!r}; use one of {list(PROVIDERS)}")
    return provider(path, cfg)
