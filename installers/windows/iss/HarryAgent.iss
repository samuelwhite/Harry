#define MyAppName "Harry Agent"
#define MyAppVersion "2026.05.09"
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

[Code]
const
  HarryAgentServiceName = 'HarryAgent';
  HarryAgentServiceImage = 'HarryAgentService.exe';

function ExecBestEffort(const FileName, Params: string): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(FileName, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function IsHarryAgentServiceRunning: Boolean;
var
  ResultCode: Integer;
begin
  Result :=
    Exec(
      ExpandConstant('{cmd}'),
      '/C tasklist /FI "IMAGENAME eq ' + HarryAgentServiceImage + '" | find /I "' + HarryAgentServiceImage + '" > nul',
      '',
      SW_HIDE,
      ewWaitUntilTerminated,
      ResultCode
    ) and (ResultCode = 0);
end;

procedure StopHarryAgentServiceForUpgrade;
var
  Attempts: Integer;
  Choice: Integer;
begin
  if not FileExists(ExpandConstant('{commonappdata}\Harry\HarryAgentService.exe')) then
    Exit;

  while IsHarryAgentServiceRunning do
  begin
    ExecBestEffort(ExpandConstant('{sys}\sc.exe'), 'stop "' + HarryAgentServiceName + '"');

    for Attempts := 1 to 20 do
    begin
      if not IsHarryAgentServiceRunning then
        Exit;
      Sleep(500);
    end;

    ExecBestEffort(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM "' + HarryAgentServiceImage + '"');

    for Attempts := 1 to 10 do
    begin
      if not IsHarryAgentServiceRunning then
        Exit;
      Sleep(500);
    end;

    if WizardSilent then
      Abort;
    Choice := MsgBox(
      'Harry Agent is still running and its files are locked.' + #13#10 + #13#10 +
      'Close the service, then click Retry to try again, or Cancel to stop setup.',
      mbError,
      MB_RETRYCANCEL
    );
    if Choice = IDCANCEL then
      Abort;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    StopHarryAgentServiceForUpgrade();
end;
