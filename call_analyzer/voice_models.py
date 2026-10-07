"""The emotion model of the voice step (VOICE_MODEL, a Hugging Face audio-classification model) as ONNX.

Like the Tunisian Whisper models, it is converted once on a machine that has torch and transformers (normally this
server; requirements-voice.txt) and then runs without torch, with onnxruntime, which faster-whisper already needs.
A remote agent that doesn't have the model downloads the converted one from the server instead of converting it
itself, so the installed agent app needs no torch.

The converted model lives in <WHISPER_MODEL_DIR>/voice/<repo with / as -->/: model.onnx and model.json (labels and
how the audio is normalized).
"""
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import FROZEN, settings
from .whisper_models import ModelUnavailable

SAMPLE_RATE = 16000

# Set by a remote agent: fetch_model(name, dest) downloads the converted model from the server into `dest`.
# Raises ModelUnavailable when the server doesn't have it either.
fetch_model = None


@dataclass(frozen=True)
class VoiceModel:
    label: str
    size_gb: float  # disk space once converted to ONNX


# The models VOICE_MODEL can be set to (Settings shows this list, like the Whisper models). The key is the Hugging
# Face repo; each one was converted and run on phone recordings. All are ungated and need no login.
VOICE_MODELS = {
    "superb/wav2vec2-base-superb-er": VoiceModel(
        "Neutral, happy, angry, sad · English speech, small and fast (default)", 0.4),
    "Aniemore/wav2vec2-emotion-v1-crosslingual": VoiceModel(
        "7 emotions · cross-lingual, more detail but 3x slower", 1.2),
    "Lajavaness/wav2vec2-lg-xlsr-fr-speech-emotion-recognition": VoiceModel(
        "Neutral, tension, pleased, sad, relaxed · trained on French, 3x slower", 1.2),
}


def model_dir(name: str, cfg=None) -> Path:
    return Path((cfg or settings).whisper_model_dir) / "voice" / name.replace("/", "--")


def is_installed(name: str, cfg=None) -> bool:
    folder = model_dir(name, cfg)
    return (folder / "model.onnx").exists() and (folder / "model.json").exists()


def install(name: str, log=print, cfg=None) -> Path:
    """Make the model usable here: fetch the converted one from the server (an agent), or convert it (needs torch +
    transformers, once). Returns its folder."""
    cfg = cfg or settings
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
    convert(name, out, log)
    return out


def convert(name: str, out: Path, log=print) -> None:
    """Download the model from Hugging Face and export it to ONNX."""
    try:
        import torch
        from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
    except ImportError as exc:
        how = ("set the environment variable INSTALL_VOICE=true (as a build variable) and redeploy"
               if Path("/.dockerenv").exists() else "run `pip install -r requirements-voice.txt`")
        if FROZEN:
            how = "let the server convert it first (it needs torch): the agent downloads it from there"
        raise RuntimeError(f"The voice model '{name}' must be converted once, which needs torch and transformers: "
                           f"{how} ({exc})") from exc
    from huggingface_hub import constants
    constants.HF_HUB_DISABLE_XET = True  # plain HTTPS: Xet transfers can stall on some networks

    log(f"Downloading and converting {name} for the voice step (a minute, only the first time)…")
    model = AutoModelForAudioClassification.from_pretrained(name).eval()
    extractor = AutoFeatureExtractor.from_pretrained(name)
    id2label = model.config.id2label
    labels = [str(id2label[i]) for i in range(len(id2label))]

    class Logits(torch.nn.Module):  # the ONNX graph's output is the logits only, not transformers' output object
        def __init__(self, inner):
            super().__init__()
            self.inner = inner

        def forward(self, input_values):
            return self.inner(input_values).logits

    tmp = out.with_name(out.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with torch.no_grad():
        torch.onnx.export(
            Logits(model), (torch.randn(1, SAMPLE_RATE * 3),), str(tmp / "model.onnx"), input_names=["input_values"],
            output_names=["logits"], dynamic_axes={"input_values": {0: "batch", 1: "samples"}, "logits": {0: "batch"}},
            opset_version=17, dynamo=False)
    (tmp / "model.json").write_text(json.dumps({
        "source": name, "labels": labels, "do_normalize": bool(getattr(extractor, "do_normalize", True)),
        "sampling_rate": int(getattr(extractor, "sampling_rate", SAMPLE_RATE))}), encoding="utf-8")
    shutil.rmtree(out, ignore_errors=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp.rename(out)
    log(f"Converted {name} in {out}")


class OnnxClassifier:
    """Calls like a transformers audio-classification pipeline: classifier({"raw": samples, "sampling_rate": 16000})
    gives [{"label", "score"}, ...], highest first."""

    def __init__(self, folder: Path):
        import onnxruntime as ort

        meta = json.loads((folder / "model.json").read_text(encoding="utf-8"))
        self.labels, self.normalize = meta["labels"], meta["do_normalize"]
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self.session = ort.InferenceSession(str(folder / "model.onnx"), options, providers=["CPUExecutionProvider"])

    def __call__(self, audio: dict) -> list[dict]:
        x = np.asarray(audio["raw"], dtype=np.float32)
        if self.normalize:  # what the model's feature extractor does: zero mean, unit variance
            x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
        logits = self.session.run(None, {"input_values": x[None, :]})[0][0].astype(np.float64)
        probs = np.exp(logits - logits.max())
        probs /= probs.sum()
        return sorted(({"label": label, "score": float(p)} for label, p in zip(self.labels, probs)),
                      key=lambda item: -item["score"])
