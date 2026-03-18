#define MyAppName "Harry Agent"
#define MyAppVersion "2026.03.18"
#define MyAppPublisher "Samuel White"

[Setup]
AppId={{8D3D0A8B-3D89-4A55-9F0B-7A6A7A7E4F21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName=C:\ProgramData\Harry
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
Source: "..\payload\harry_agent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\payload\HarryAgentService.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\payload\HarryAgentService.xml"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}"

[UninstallRun]
Filename: "{app}\HarryAgentService.exe"; Parameters: "stop"; Flags: runhidden skipifdoesntexist
Filename: "{app}\HarryAgentService.exe"; Parameters: "uninstall"; Flags: runhidden skipifdoesntexist

[Code]
var
  BrainPage: TInputQueryWizardPage;
  BrainUrl: String;

function TrimEx(const S: String): String;
begin
  Result := Trim(S);
end;

function StartsWith(const S, Prefix: String): Boolean;
begin
  Result := CompareText(Copy(S, 1, Length(Prefix)), Prefix) = 0;
end;

function NormalizeBrainUrl(InputValue: String): String;
var
  S: String;
  HostPart: String;
begin
  S := TrimEx(InputValue);

  if S = '' then
  begin
    Result := '';
    exit;
  end;

  if not StartsWith(LowerCase(S), 'http://') and not StartsWith(LowerCase(S), 'https://') then
    S := 'http://' + S;

  HostPart := Copy(S, Pos('://', S) + 3, MaxInt);
  if Pos(':', HostPart) = 0 then
    S := S + ':8787';

  Result := S;
end;

function EscapeJson(const S: String): String;
var
  I: Integer;
  C: Char;
begin
  Result := '';
  for I := 1 to Length(S) do
  begin
    C := S[I];
    case C of
      '"': Result := Result + '\"';
      '\': Result := Result + '\\';
      Chr(13): Result := Result + '\r';
      Chr(10): Result := Result + '\n';
    else
      Result := Result + C;
    end;
  end;
end;

function WriteAgentConfig(const BaseUrl: String): Boolean;
var
  ConfigPath: String;
  JsonText: String;
begin
  ConfigPath := ExpandConstant('{app}\agent_config.json');
  JsonText :=
    '{' + #13#10 +
    '  "brain_url": "' + EscapeJson(BaseUrl) + '"' + #13#10 +
    '}' + #13#10;

  Result := SaveStringToFile(ConfigPath, JsonText, False);
end;

function RunHidden(const Filename, Params, WorkingDir: String; var ResultCode: Integer): Boolean;
begin
  Result := Exec(Filename, Params, WorkingDir, SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function TestBrainConnectivity(const BaseUrl: String; var Msg: String): Boolean;
var
  PsFile: String;
  OutFile: String;
  Script: String;
  ResultCode: Integer;
  OutputText: AnsiString;
begin
  PsFile := ExpandConstant('{tmp}\harry_test_brain.ps1');
  OutFile := ExpandConstant('{tmp}\harry_test_brain.txt');

  Script :=
    '$ProgressPreference = ''SilentlyContinue''' + #13#10 +
    '$url = ''' + BaseUrl + '/nodes''' + #13#10 +
    'try {' + #13#10 +
    '  $r = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 5' + #13#10 +
    '  ''OK '' + [string]$r.StatusCode | Set-Content -Path ''' + OutFile + '''' + #13#10 +
    '  exit 0' + #13#10 +
    '} catch {' + #13#10 +
    '  $_.Exception.Message | Set-Content -Path ''' + OutFile + '''' + #13#10 +
    '  exit 1' + #13#10 +
    '}' + #13#10;

  if not SaveStringToFile(PsFile, Script, False) then
  begin
    Msg := 'Could not create connectivity test script.';
    Result := False;
    exit;
  end;

  if not RunHidden(
    ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-ExecutionPolicy Bypass -NoProfile -File "' + PsFile + '"',
    ExpandConstant('{tmp}'),
    ResultCode
  ) then
  begin
    Msg := 'Could not launch PowerShell.';
    Result := False;
    exit;
  end;

  if LoadStringFromFile(OutFile, OutputText) then
    Msg := TrimEx(String(OutputText))
  else
    Msg := 'No response details captured.';

  Result := (ResultCode = 0);
end;

function InstallService(): Boolean;
var
  ExePath: String;
  ResultCode: Integer;
begin
  ExePath := ExpandConstant('{app}\HarryAgentService.exe');

  RunHidden(ExePath, 'stop', ExpandConstant('{app}'), ResultCode);
  RunHidden(ExePath, 'uninstall', ExpandConstant('{app}'), ResultCode);

  if not RunHidden(ExePath, 'install', ExpandConstant('{app}'), ResultCode) then
  begin
    MsgBox('Failed to run HarryAgentService install.', mbCriticalError, MB_OK);
    Result := False;
    exit;
  end;

  if ResultCode <> 0 then
  begin
    MsgBox('Service install failed with exit code ' + IntToStr(ResultCode) + '.', mbCriticalError, MB_OK);
    Result := False;
    exit;
  end;

  if not RunHidden(ExePath, 'start', ExpandConstant('{app}'), ResultCode) then
  begin
    MsgBox('Failed to start Harry Agent service.', mbCriticalError, MB_OK);
    Result := False;
    exit;
  end;

  if ResultCode <> 0 then
  begin
    MsgBox('Service start failed with exit code ' + IntToStr(ResultCode) + '.', mbCriticalError, MB_OK);
    Result := False;
    exit;
  end;

  Result := True;
end;

procedure InitializeWizard();
begin
  BrainPage := CreateInputQueryPage(
    wpWelcome,
    'Harry Brain Connection',
    'Where should this agent report?',
    'Enter the Harry Brain IP address or hostname. Example: 192.168.7.174'
  );

  BrainPage.Add('&Brain address:', False);
  BrainPage.Values[0] := 'localhost';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  TestMsg: String;
begin
  Result := True;

  if CurPageID = BrainPage.ID then
  begin
    BrainUrl := NormalizeBrainUrl(BrainPage.Values[0]);

    if BrainUrl = '' then
    begin
      MsgBox('Please enter a Brain address.', mbError, MB_OK);
      Result := False;
      exit;
    end;

    if not TestBrainConnectivity(BrainUrl, TestMsg) then
    begin
      MsgBox(
        'Could not reach Harry Brain at:' + #13#10 + BrainUrl + #13#10#13#10 +
        'Details: ' + TestMsg + #13#10#13#10 +
        'Check the IP/hostname, that Brain is running, and that port 8787 is reachable.',
        mbCriticalError, MB_OK
      );
      Result := False;
      exit;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if WizardSilent then
      BrainUrl := NormalizeBrainUrl('localhost')
    else
      BrainUrl := NormalizeBrainUrl(BrainPage.Values[0]);

    if not WriteAgentConfig(BrainUrl) then
    begin
      MsgBox('Failed to write agent_config.json.', mbCriticalError, MB_OK);
      exit;
    end;

    if not InstallService() then
      exit;

    MsgBox(
      'Harry Agent installed successfully.' + #13#10#13#10 +
      'Brain URL: ' + BrainUrl + #13#10 +
      'Install path: ' + ExpandConstant('{app}') + #13#10#13#10 +
      'Log files:' + #13#10 +
      ExpandConstant('{app}\HarryAgentService.wrapper.log') + #13#10 +
      ExpandConstant('{app}\HarryAgentService.out.log') + #13#10 +
      ExpandConstant('{app}\HarryAgentService.err.log'),
      mbInformation, MB_OK
    );
  end;
end;