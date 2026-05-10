#define MyAppName "Harry Agent"
#define MyAppVersion "2026.05.10"
#define MyAppPublisher "Harry Contributors"

[Setup]
AppId={{8D3D0A8B-3D89-4A55-9F0B-7A6A7A7E4F21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName=C:\ProgramData\Harry\agent-installer
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir=..\output
OutputBaseFilename=HarryAgentSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
SetupLogging=yes
UninstallDisplayIcon={app}\HarryAgentService.exe

[Files]
Source: "..\..\..\app\dist\windows\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}"

[UninstallRun]
Filename: "{app}\HarryAgentService.exe"; Parameters: "stop"; Flags: runhidden skipifdoesntexist
Filename: "{app}\HarryAgentService.exe"; Parameters: "uninstall"; Flags: runhidden skipifdoesntexist

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install_agent.ps1"""; Flags: runhidden waituntilterminated; StatusMsg: "Searching for Harry Brain and finalising setup..."
