# PyInstaller spec for the Call Analyzer Agent (see build_agent.ps1).
#   AGENT_GPU=1 also ships the NVIDIA CUDA libraries, so Whisper can use the PC's GPU (about 2 GB more).
import os
import site
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parent
GPU = os.environ.get("AGENT_GPU") == "1"

datas = collect_data_files("faster_whisper")  # the voice-activity model (silero_vad)
binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("onnxruntime") + collect_dynamic_libs("av")

if GPU:
    # Where transcribe._add_cuda_dlls() looks for them: <app>/nvidia/<package>/bin
    for packages in site.getsitepackages():
        for bin_dir in Path(packages, "nvidia").glob("*/bin"):
            for dll in bin_dir.glob("*.dll"):
                binaries.append((str(dll), f"nvidia/{bin_dir.parent.name}/bin"))

a = Analysis(
    [str(ROOT / "packaging" / "agent_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["pystray._win32", "PIL._tkinter_finder", "PIL.ImageTk", "tkinter", "anthropic"],
    # The server, its web stack and the model converter are not part of the agent.
    excludes=["fastapi", "uvicorn", "starlette", "torch", "transformers", "tensorflow", "matplotlib", "scipy",
              "pandas", "IPython", "pytest", "cursor_sdk", "markdown"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CallAnalyzerAgent",
    console=False,  # a tray app; started from a terminal with a command it prints there (agent_app.attach_console)
    icon=str(ROOT / "packaging" / "agent.ico"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="CallAnalyzerAgent", upx=False)
