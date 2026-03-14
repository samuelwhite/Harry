[Setup]
AppName=Harry Brain
AppVersion=0.3.1
DefaultDirName={pf}\Harry\brain
DefaultGroupName=Harry
OutputBaseFilename=HarryBrainSetup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin

[Dirs]
Name: "C:\ProgramData\Harry\brain"
Name: "C:\ProgramData\Harry\brain\data"
Name: "C:\ProgramData\Harry\brain\logs"

[Files]
Source: "..\brain-payload\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\output\harry-agent-setup-0.3.1.exe"; DestDir: "{tmp}"; Flags: ignoreversion

[Run]
Filename: "{app}\HarryBrainService.exe"; Parameters: "install"; Flags: runhidden waituntilterminated
Filename: "{app}\HarryBrainService.exe"; Parameters: "start"; Flags: runhidden waituntilterminated
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""try { if (-not (Get-NetFirewallRule -DisplayName 'Harry Brain TCP 8787' -ErrorAction SilentlyContinue)) { New-NetFirewallRule -DisplayName 'Harry Brain TCP 8787' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8787 -Profile Private,Domain | Out-Null } } catch { exit 0 }"""; Flags: runhidden waituntilterminated
Filename: "{tmp}\harry-agent-setup-0.3.1.exe"; Parameters: "/VERYSILENT"; Flags: waituntilterminated
Filename: "http://localhost:8787/"; Flags: shellexec postinstall skipifsilent

[UninstallRun]
Filename: "{app}\HarryBrainService.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated skipifdoesntexist
Filename: "{app}\HarryBrainService.exe"; Parameters: "uninstall"; Flags: runhidden waituntilterminated skipifdoesntexist
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""try { Remove-NetFirewallRule -DisplayName 'Harry Brain TCP 8787' -ErrorAction SilentlyContinue } catch { exit 0 }"""; Flags: runhidden waituntilterminated
