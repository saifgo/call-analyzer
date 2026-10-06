# Builds the Windows installer of the Call Analyzer Agent.
#
#   .\packaging\build_agent.ps1            CPU build:  CallAnalyzerAgent-Setup-<version>.exe      (~150-300 MB)
#   .\packaging\build_agent.ps1 -Gpu       GPU build:  CallAnalyzerAgent-GPU-Setup-<version>.exe  (adds the NVIDIA CUDA libraries)
#
# Needs the project's .venv with requirements.txt and requirements-agent.txt installed, and Inno Setup 6
# (winget install JRSoftware.InnoSetup) for the installer; without it you get the program folder only.
# Output goes to -OutDir (default: D:\call-analyzer-build when D: exists, else .\build).
param(
    [switch]$Gpu,
    [string]$Version = "1.0",
    [string]$OutDir
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Create the venv first: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt -r requirements-agent.txt" }
if (-not $OutDir) { $OutDir = if (Test-Path "D:\") { "D:\call-analyzer-build" } else { Join-Path $root "build" } }
$variant = if ($Gpu) { "-GPU" } else { "" }
$work = Join-Path $OutDir "work$variant"
$dist = Join-Path $OutDir "dist$variant"
New-Item -ItemType Directory -Force $OutDir | Out-Null

Write-Host "== Icon"
& $py (Join-Path $PSScriptRoot "make_icon.py")

Write-Host "== PyInstaller ($(if ($Gpu) { 'GPU' } else { 'CPU' }))"
$env:AGENT_GPU = if ($Gpu) { "1" } else { "0" }
$env:PYTHONUTF8 = "1"
& $py -m PyInstaller (Join-Path $PSScriptRoot "agent.spec") --noconfirm --clean --workpath $work --distpath $dist
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$app = Join-Path $dist "CallAnalyzerAgent"

$iscc = @(
    (Get-Command iscc -ErrorAction SilentlyContinue).Source,
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
    Write-Warning "Inno Setup not found (winget install JRSoftware.InnoSetup): no installer built. The program is in $app"
    exit 0
}
Write-Host "== Installer"
& $iscc "/DAppVersion=$Version" "/DSourceDir=$app" "/DVariant=$variant" "/O$OutDir" (Join-Path $PSScriptRoot "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Host "Done: $(Get-ChildItem $OutDir -Filter 'CallAnalyzerAgent*-Setup-*.exe' | Sort-Object LastWriteTime | Select-Object -Last 1 -ExpandProperty FullName)"
