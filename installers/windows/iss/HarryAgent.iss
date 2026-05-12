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
Source: "..\..\..\app\dist\windows\*"; DestDir: "{tmp}\HarryAgentPayload"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{tmp}\HarryAgentPayload"

[UninstallRun]
Filename: "{app}\HarryAgentService.exe"; Parameters: "stop"; Flags: runhidden skipifdoesntexist
Filename: "{app}\HarryAgentService.exe"; Parameters: "uninstall"; Flags: runhidden skipifdoesntexist

[Code]
const
  HarryAgentServiceName = 'HarryAgent';
  HarryAgentServiceImage = 'HarryAgentService.exe';

var
  BrainModePage: TInputOptionWizardPage;
  ManualBrainPage: TInputQueryWizardPage;
  InstallSucceeded: Boolean;

function ExecBestEffort(const FileName, Params: string): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(FileName, Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function SelectedInstallerMode: string;
begin
  if BrainModePage.Values[1] then
    Result := 'manual'
  else
    Result := 'automatic';
end;

function SelectedBrainUrl: string;
begin
  Result := Trim(ManualBrainPage.Values[0]);
end;

procedure SetInstallerStatus(const MessageText: string);
begin
  WizardForm.StatusLabel.Caption := MessageText;
  WizardForm.StatusLabel.Update();
end;

procedure SetInstallerBusyStatus(const MessageText: string);
begin
  try
    WizardForm.ProgressGauge.Style := npbstMarquee;
  except
  end;
  SetInstallerStatus(MessageText);
end;

procedure SetInstallerIdleStatus(const MessageText: string);
begin
  try
    WizardForm.ProgressGauge.Style := npbstNormal;
  except
  end;
  SetInstallerStatus(MessageText);
end;

function RunInstallAgentScript: Boolean;
var
  ResultCode: Integer;
  Params: string;
begin
  if BrainModePage.Values[1] then
  begin
    if Trim(ManualBrainPage.Values[0]) = '' then
    begin
      MsgBox(
        'Please enter the Brain URL or IP address before continuing.',
        mbError,
        MB_OK
      );
      Result := False;
      Exit;
    end;
    SetInstallerBusyStatus('Installing Harry Agent with the selected Brain address...');
  end
  else
    SetInstallerBusyStatus('Searching for Harry Brain...');

  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{tmp}\HarryAgentPayload\install_agent.ps1') + '"';
  Params := Params + ' -InstallerMode "' + SelectedInstallerMode + '"';
  if SelectedInstallerMode = 'manual' then
    Params := Params + ' -BrainUrl "' + SelectedBrainUrl + '"';
  Result := Exec(
    ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Params,
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) and (ResultCode = 0);

  if not Result then
  begin
    MsgBox(
      'Harry Agent setup failed. The installer script did not complete successfully.' + #13#10 +
      'Exit code: ' + IntToStr(ResultCode) + #13#10#13#10 +
      'Please check C:\ProgramData\Harry\logs\HarryAgent.install.log for details.',
      mbError,
      MB_OK
    );
    Abort;
  end;

  InstallSucceeded := True;
  SetInstallerIdleStatus('Harry Agent installed successfully.');
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

procedure InitializeWizard;
begin
  InstallSucceeded := False;
  BrainModePage := CreateInputOptionPage(
    wpWelcome,
    'Harry Brain connection',
    'Choose how this installer connects to Harry Brain.',
    'Select one option below:',
    False,
    False
  );
  BrainModePage.Add('Automatic discovery (recommended)');
  BrainModePage.Add('Manual Brain address');
  BrainModePage.Values[0] := True;

  ManualBrainPage := CreateInputQueryPage(
    BrainModePage.ID,
    'Manual Brain address',
    'Enter the Harry Brain address.',
    'Examples: 192.168.1.100, 192.168.1.100:8789, http://192.168.1.100:8789, https://example.local'
  );
  ManualBrainPage.Add('Brain address:', False);
  ManualBrainPage.Values[0] := '';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (PageID = ManualBrainPage.ID) and (not BrainModePage.Values[1]) then
    Result := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  if CurPageID = ManualBrainPage.ID then
  begin
    if Trim(ManualBrainPage.Values[0]) = '' then
    begin
      MsgBox(
        'Please enter the Brain URL or IP address before continuing.',
        mbError,
        MB_OK
      );
      Result := False;
      Exit;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    SetInstallerBusyStatus('Preparing Harry Agent upgrade...');
    StopHarryAgentServiceForUpgrade();
  end;

  if CurStep = ssPostInstall then
  begin
    if BrainModePage.Values[1] then
      SetInstallerBusyStatus('Installing Harry Agent with the selected Brain address...')
    else
      SetInstallerBusyStatus('Searching for Harry Brain...');
    RunInstallAgentScript();
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and InstallSucceeded then
  begin
    WizardForm.FinishedLabel.Caption := 'Harry Agent installed successfully. This machine is now reporting to Harry Brain.';
  end;
end;
