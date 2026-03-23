[Setup]
AppId={{D6A6C8B8-9B41-4E7E-9D95-6A0F4C4E1B11}
AppName=Harry Brain
AppVersion=2026.03.18
DefaultDirName={commonpf}\Harry\brain
DefaultGroupName=Harry
OutputBaseFilename=HarryBrainSetup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\HarryBrainService.exe

[Dirs]
Name: "C:\ProgramData\Harry\brain"
Name: "C:\ProgramData\Harry\brain\data"
Name: "C:\ProgramData\Harry\brain\logs"

[Files]
Source: "..\brain-payload\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\..\downloads\HarryAgentInstall.sh"; DestDir: "{app}\downloads"; Flags: ignoreversion
Source: "..\..\..\downloads\HarryAgentSetup.exe"; DestDir: "{app}\downloads"; Flags: ignoreversion
Source: "..\..\..\downloads\HarryAgentSetup.exe"; DestDir: "{tmp}"; Flags: ignoreversion
Source: "..\brain-payload\open_firewall.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\brain-payload\remove_firewall.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\set_brain_public_url.ps1"""; Flags: runhidden waituntilterminated
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -NoProfile -File ""{app}\open_firewall.ps1"" -Port 8787"; Flags: runhidden waituntilterminated
Filename: "{app}\HarryBrainService.exe"; Parameters: "install"; Flags: runhidden waituntilterminated
Filename: "{app}\HarryBrainService.exe"; Parameters: "start"; Flags: runhidden waituntilterminated
Filename: "{tmp}\HarryAgentSetup.exe"; Parameters: "/VERYSILENT"; Flags: waituntilterminated; StatusMsg: "Just finalising and setting up the Harry Agent on this machine..."
Filename: "timeout.exe"; Parameters: "/T 3"; Flags: runhidden waituntilterminated
Filename: "http://127.0.0.1:8787/"; Flags: shellexec postinstall skipifsilent

[UninstallRun]
Filename: "{app}\HarryBrainService.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "StopHarryBrainService"
Filename: "{app}\HarryBrainService.exe"; Parameters: "uninstall"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "UninstallHarryBrainService"
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -NoProfile -File ""{app}\remove_firewall.ps1"" -Port 8787"; Flags: runhidden waituntilterminated skipifdoesntexist; RunOnceId: "RemoveHarryBrainFirewallRule"

[InstallDelete]
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
var
  RemoveExistingData: Boolean;

function DirExistsNonEmpty(const DirName: string): Boolean;
var
  FindRec: TFindRec;
begin
  Result := False;
  if not DirExists(DirName) then
    Exit;

  if FindFirst(DirName + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          Result := True;
          Exit;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure ExecBestEffort(const FileName, Params: string);
var
  ResultCode: Integer;
begin
  Exec(FileName, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure StopServiceIfExists(const ServiceName: string);
begin
  ExecBestEffort(ExpandConstant('{sys}\sc.exe'), 'stop "' + ServiceName + '"');
end;

procedure DeleteServiceIfExists(const ServiceName: string);
begin
  ExecBestEffort(ExpandConstant('{sys}\sc.exe'), 'delete "' + ServiceName + '"');
end;

procedure KillIfRunning(const ImageName: string);
begin
  ExecBestEffort(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "' + ImageName + '" /T');
end;

procedure SleepSeconds(const Seconds: string);
begin
  ExecBestEffort(ExpandConstant('{sys}\timeout.exe'), '/T ' + Seconds + ' /NOBREAK');
end;

procedure DeleteHarryDataIfRequested();
begin
  if not RemoveExistingData then
    Exit;

  DelTree('C:\ProgramData\Harry\brain\data', True, True, True);
  DelTree('C:\ProgramData\Harry\brain\logs', True, True, True);
  DelTree('C:\ProgramData\Harry\brain', True, True, True);
end;

procedure RemoveExistingInstallArtifacts();
begin
  StopServiceIfExists('HarryBrainService');
  StopServiceIfExists('HarryAgent');
  StopServiceIfExists('HarryAgentService');

  SleepSeconds('2');

  KillIfRunning('brain_server.exe');
  KillIfRunning('HarryBrainService.exe');
  KillIfRunning('harry_agent.exe');
  KillIfRunning('HarryAgentService.exe');

  SleepSeconds('2');

  if FileExists(ExpandConstant('{app}\HarryBrainService.exe')) then
  begin
    ExecBestEffort(ExpandConstant('{app}\HarryBrainService.exe'), 'stop');
    ExecBestEffort(ExpandConstant('{app}\HarryBrainService.exe'), 'uninstall');
  end;

  DeleteServiceIfExists('HarryBrainService');
  DeleteServiceIfExists('HarryAgent');
  DeleteServiceIfExists('HarryAgentService');

  SleepSeconds('2');

  if FileExists(ExpandConstant('{app}\remove_firewall.ps1')) then
  begin
    ExecBestEffort(
      'powershell.exe',
      '-ExecutionPolicy Bypass -NoProfile -File "' + ExpandConstant('{app}\remove_firewall.ps1') + '" -Port 8787'
    );
  end;
end;

function InitializeSetup(): Boolean;
var
  ExistingAppDir: string;
  ExistingProgramData: string;
  HasExistingInstall: Boolean;
  HasExistingData: Boolean;
  Choice: Integer;
begin
  Result := True;
  RemoveExistingData := False;

  ExistingAppDir := ExpandConstant('{commonpf}\Harry\brain');
  ExistingProgramData := 'C:\ProgramData\Harry\brain';

  HasExistingInstall :=
    DirExists(ExistingAppDir) or
    FileExists(ExistingAppDir + '\HarryBrainService.exe');

  HasExistingData :=
    DirExistsNonEmpty(ExistingProgramData) or
    DirExistsNonEmpty(ExistingProgramData + '\data') or
    DirExistsNonEmpty(ExistingProgramData + '\logs');

  if HasExistingInstall or HasExistingData then
  begin
    Choice := MsgBox(
      'An existing Harry Brain installation or data was found.' + #13#10 + #13#10 +
      'Click YES to reinstall and REMOVE existing Brain data/logs.' + #13#10 +
      'Click NO to reinstall and KEEP existing Brain data/logs.' + #13#10 +
      'Click CANCEL to stop setup.',
      mbConfirmation,
      MB_YESNOCANCEL
    );

    if Choice = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;

    RemoveExistingData := (Choice = IDYES);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    RemoveExistingInstallArtifacts();
    DeleteHarryDataIfRequested();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Choice: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    Choice := MsgBox(
      'Do you also want to delete Harry Brain data and logs?' + #13#10 + #13#10 +
      'Click YES to remove Brain data/logs.' + #13#10 +
      'Click NO to keep Brain data/logs.',
      mbConfirmation,
      MB_YESNO
    );

    if Choice = IDYES then
    begin
      DelTree('C:\ProgramData\Harry\brain\data', True, True, True);
      DelTree('C:\ProgramData\Harry\brain\logs', True, True, True);
      DelTree('C:\ProgramData\Harry\brain', True, True, True);
    end;
  end;
end;
