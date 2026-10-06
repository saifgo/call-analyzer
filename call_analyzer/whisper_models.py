"""Whisper models for faster-whisper, including community models fine-tuned on Tunisian Derja.

Built-in names (large-v3, large-v3-turbo, medium, ...) are downloaded ready to use. The dialect models below are
published in Hugging Face transformers format, so the first time one is used it is downloaded and converted to
CTranslate2 (the format faster-whisper runs) inside WHISPER_MODEL_DIR. Converting needs `torch` and
`transformers` (requirements-convert.txt), only once per model.
"""
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import FROZEN, settings


class ModelUnavailable(Exception):
    """The server can't provide this converted model."""


# Set by a remote agent: fetch_model(name, dest) downloads the converted model from the server into `dest`, so the
# agent PC doesn't need torch to convert it. Raises ModelUnavailable when the server doesn't have it either.
fetch_model = None


@dataclass(frozen=True)
class DialectModel:
    repo: str
    label: str
    size_gb: float  # disk space once converted (float16)


DIALECT_MODELS = {
    # Fully fine-tuned large-v3 on ~46K Tunisian utterances with French/English code-switching
    # (NADI 2026 Tunisian code-switched ASR): blind-test WER 15%, vs > 50% for stock Whisper.
    "tunisian-large-v3": DialectModel(
        "oddadmix/Whisperv3-tunisian-codeswitch",
        "Tunisian Derja + French (large-v3, most accurate)", 3.1),
    # large-v3-turbo fine-tuned on several Arabic dialects including Tunisian. Faster, Apache-2.0.
    "arabic-dialectal-turbo": DialectModel(
        "oddadmix/whisper-large-v3-turbo-arabic-dialectal-v2",
        "Arabic dialects incl. Tunisian (turbo, faster)", 1.6),
}

# Used when a model doesn't ship preprocessor_config.json; faster-whisper would otherwise assume 80 mel bins.
_PREPROCESSOR_DEFAULTS = {"chunk_length": 30, "hop_length": 160, "n_fft": 400, "n_samples": 480000,
                          "nb_max_frames": 3000, "sampling_rate": 16000}


def model_dir(name: str, cfg=None) -> Path:
    return Path((cfg or settings).whisper_model_dir) / "ct2" / name


def is_installed(name: str, cfg=None) -> bool:
    return (model_dir(name, cfg) / "model.bin").exists()


def install(name: str, log=print, cfg=None) -> Path:
    """Download a dialect model from Hugging Face and convert it for faster-whisper."""
    cfg = cfg or settings
    model = DIALECT_MODELS[name]
    out = model_dir(name, cfg)
    if is_installed(name, cfg):
        return out
    if fetch_model is not None:
        try:
            log(f"Getting {name} from the server…")
            fetch_model(name, out)
            return out
        except ModelUnavailable as exc:
            log(f"{exc}; converting it here instead")
    try:
        from ctranslate2.converters import TransformersConverter
        from huggingface_hub import snapshot_download
        import torch  # noqa: F401  (needed by the converter)
        import transformers  # noqa: F401
    except ImportError as exc:
        how = ("set the environment variable INSTALL_CONVERT=true (as a build variable) and redeploy"
               if Path("/.dockerenv").exists() else "run `pip install -r requirements-convert.txt`")
        if FROZEN:
            how = "install it on the server first (Settings, Install now): the agent downloads it from there"
        raise RuntimeError(
            f"Whisper model '{name}' must be converted once, which needs torch and transformers: {how}, "
            f"or pick another WHISPER_MODEL ({exc})") from exc

    from huggingface_hub import constants
    constants.HF_HUB_DISABLE_XET = True  # Hugging Face's Xet transfer can stall on some networks; plain HTTPS doesn't

    src = Path(cfg.whisper_model_dir) / "src" / name
    log(f"Downloading {model.repo} (~{model.size_gb * 2:.0f} GB, only the first time)…")
    snapshot_download(model.repo, local_dir=src,
                      allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "tokenizer*"])

    copy_files = [f for f in ("tokenizer.json", "preprocessor_config.json") if (src / f).exists()]
    log(f"Converting {name} for faster-whisper (a few minutes)…")
    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    TransformersConverter(str(src), copy_files=copy_files, load_as_float16=True,
                          low_cpu_mem_usage=True).convert(str(tmp), quantization="float16", force=True)
    if not (tmp / "preprocessor_config.json").exists():
        n_mels = json.loads((src / "config.json").read_text(encoding="utf-8")).get("num_mel_bins", 128)
        (tmp / "preprocessor_config.json").write_text(
            json.dumps({**_PREPROCESSOR_DEFAULTS, "feature_size": n_mels}), encoding="utf-8")
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)
    shutil.rmtree(src, ignore_errors=True)  # the transformers weights are no longer needed
    log(f"Installed {name} in {out}")
    return out


def resolve(name: str, log=print, cfg=None) -> str:
    """What to pass to faster_whisper.WhisperModel: a built-in name / repo id, or a converted local folder."""
    if name in DIALECT_MODELS:
        return str(install(name, log, cfg))
    return name
