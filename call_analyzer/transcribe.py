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

_model = None
_device = None  # "GPU" or "CPU" once the local model is loaded
_batched = None
_model_lock = threading.Lock()  # one GPU/CPU model, one transcription at a time


def _add_cuda_dlls():
    """Make the pip-installed CUDA libraries (nvidia-cublas/cudnn) visible on Windows."""
    for d in glob.glob(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "*", "bin")):
        os.add_dll_directory(d)
        os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]


def _whisper():
    global _model, _device
    if _model is None:
        if os.name == "nt":
            _add_cuda_dlls()
        from faster_whisper import WhisperModel

        from .whisper_models import resolve

        model = resolve(settings.whisper_model)  # dialect models are downloaded + converted on first use
        device = settings.whisper_device
        if device in ("auto", "cuda"):
            try:
                _model = WhisperModel(model, device="cuda", compute_type="int8",
                                      download_root=settings.whisper_model_dir)
                _device = "GPU"
                print(f"Whisper {settings.whisper_model} loaded on GPU")
                return _model
            except Exception as exc:
                if device == "cuda":
                    raise
                print(f"GPU unavailable ({exc}); using CPU, this is slower")
        _model = WhisperModel(model, device="cpu", compute_type="int8",
                              download_root=settings.whisper_model_dir, cpu_threads=os.cpu_count() or 4)
        _device = "CPU"
        print(f"Whisper {settings.whisper_model} loaded on CPU")
    return _model


# Whisper sometimes emits stray CJK/Cyrillic/Hangul characters or digit loops on noisy 8 kHz phone audio.
_JUNK_SCRIPTS = re.compile(r"[Ѐ-ӿ　-鿿가-힯]+")
_REPEATS = re.compile(r"(.)\1{5,}")
_WORD_LOOPS = re.compile(r"(\S+)(?:\s+\1){3,}")  # "كلمة كلمة كلمة كلمة ..." -> "كلمة كلمة"


def _clean(text: str) -> str:
    text = _JUNK_SCRIPTS.sub("", text)
    text = _REPEATS.sub(r"\1\1\1", text)
    text = _WORD_LOOPS.sub(r"\1 \1", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _dialect_segments(audio) -> list[tuple[float, str]]:
    """Fine-tuned dialect models were trained without timestamps: cut the audio at pauses (VAD) and decode each
    piece greedily, as their authors recommend. Gives ~10 s lines and is much faster than long-form decoding."""
    global _batched
    from faster_whisper import BatchedInferencePipeline

    if _batched is None:
        _batched = BatchedInferencePipeline(_whisper())
    segments, _ = _batched.transcribe(
        audio,
        language=settings.whisper_language or "ar",
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


def _whisper_segments(audio) -> list[tuple[float, str]]:
    from .whisper_models import DIALECT_MODELS

    if settings.whisper_model in DIALECT_MODELS:
        return _dialect_segments(audio)
    segments, _ = _whisper().transcribe(
        audio,
        language=settings.whisper_language or None,
        initial_prompt=settings.whisper_prompt or None,
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


def _local(path: Path) -> str:
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
                lines = [(t, "channel_L", text) for t, text in _whisper_segments(left)]
                lines += [(t, "channel_R", text) for t, text in _whisper_segments(right)]
                lines.sort(key=lambda line: line[0])
                return "\n".join(f"[{_fmt_ts(t)}] {who}: {text}" for t, who, text in lines)
        # Mono (or identical channels): no speaker labels; Claude infers who is speaking from context.
        return "\n".join(f"[{_fmt_ts(t)}] {text}" for t, text in _whisper_segments(str(path)))


# --- Paid APIs (optional) ---------------------------------------------------------------------

def _elevenlabs(path: Path) -> str:
    if not settings.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is empty")
    with open(path, "rb") as fh:
        resp = requests.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": settings.elevenlabs_api_key},
            data={"model_id": settings.elevenlabs_model, "diarize": "true", "num_speakers": "2",
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


def _openai(path: Path) -> str:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is empty")
    with open(path, "rb") as fh:
        resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            data={"model": settings.openai_transcribe_model},
            files={"file": (path.name, fh, "audio/mpeg")},
            timeout=600,
        )
    resp.raise_for_status()
    return resp.json().get("text", "")


PROVIDERS = {"local": _local, "elevenlabs": _elevenlabs, "openai": _openai}


def transcriber_label() -> str:
    """Who produced the transcript, stored with it (e.g. "Whisper large-v3-turbo (local, GPU)")."""
    provider = settings.transcribe_provider
    if provider == "local":
        return f"Whisper {settings.whisper_model} (local{', ' + _device if _device else ''})"
    if provider == "elevenlabs":
        return f"ElevenLabs {settings.elevenlabs_model}"
    if provider == "openai":
        return f"OpenAI {settings.openai_transcribe_model}"
    return provider


def transcribe(path: Path) -> str:
    try:
        provider = PROVIDERS[settings.transcribe_provider]
    except KeyError:
        raise RuntimeError(f"Unknown TRANSCRIBE_PROVIDER={settings.transcribe_provider!r}; use one of {list(PROVIDERS)}")
    return provider(path)
