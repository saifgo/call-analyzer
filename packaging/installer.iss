; Inno Setup script for the Call Analyzer Agent (see build_agent.ps1).
; Per-user install: no administrator rights needed. Settings, models and the log live in
; %LOCALAPPDATA%\CallAnalyzerAgent and are kept when the app is uninstalled or updated.
#ifndef AppVersion
  #define AppVersion "1.0"
#endif
#ifndef SourceDir
  #error SourceDir must point at the PyInstaller output folder
#endif
#ifndef Variant
  #define Variant ""
#endif

[Setup]
AppId={{6F2D9E54-3B1A-4C7E-9A58-0D5C7B1E4A92}
AppName=Call Analyzer Agent
AppVersion={#AppVersion}
AppPublisher=Call Analyzer
DefaultDirName={localappdata}\Programs\CallAnalyzerAgent
DefaultGroupName=Call Analyzer Agent
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=agent.ico
UninstallDisplayIcon={app}\CallAnalyzerAgent.exe
OutputBaseFilename=CallAnalyzerAgent{#Variant}-Setup-{#AppVersion}
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
; The running app holds this mutex (agent_app.single_instance): Setup asks to close it before updating.
AppMutex=Local\CallAnalyzerAgent
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "startup"; Description: "Start the agent when I sign in to Windows"; GroupDescription: "Options:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Call Analyzer Agent"; Filename: "{app}\CallAnalyzerAgent.exe"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "CallAnalyzerAgent"; ValueData: """{app}\CallAnalyzerAgent.exe"" --background"; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\CallAnalyzerAgent.exe"; Description: "Open Call Analyzer Agent"; Flags: nowait postinstall skipifsilent
