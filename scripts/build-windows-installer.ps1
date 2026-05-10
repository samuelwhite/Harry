param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-InnoSetupCompiler {
    $candidates = New-Object System.Collections.Generic.List[string]

    try {
        $cmd = Get-Command ISCC.exe -ErrorAction Stop
        if ($cmd.Source) {
            [void]$candidates.Add($cmd.Source)
        }
    } catch {
    }

    foreach ($path in @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )) {
        [void]$candidates.Add($path)
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }

    throw "ISCC.exe was not found. Install Inno Setup 6 or add ISCC.exe to PATH."
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = $Root
    )

    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$FilePath failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
}

function Invoke-PythonJson {
    param([string]$Command)

    $oldPythonPath = $env:PYTHONPATH
    $appPath = Join-Path $Root "app"
    if ([string]::IsNullOrWhiteSpace($oldPythonPath)) {
        $env:PYTHONPATH = $appPath
    } else {
        $env:PYTHONPATH = $appPath + [IO.Path]::PathSeparator + $oldPythonPath
    }

    try {
        $result = & python -c $Command 2>&1
        if ($LASTEXITCODE -ne 0) {
            $message = ($result | Out-String).Trim()
            throw "Failed to import app.versions or app.ui.db while gathering Windows installer metadata.`n$message"
        }

        $json = ($result | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($json)) {
            throw "Windows installer metadata command returned no output."
        }

        return $json
    } finally {
        $env:PYTHONPATH = $oldPythonPath
    }
}

$Root = (Resolve-Path $Root).Path
$InstallerScript = Join-Path $Root "installers/windows/iss/HarryAgent.iss"
$SyncScript = Join-Path $Root "scripts/sync_windows_artifacts.py"
$DownloadDir = Join-Path $Root "downloads"
$BuildDir = Join-Path $Root "build/windows-installer"
$InstallerExe = Join-Path $BuildDir "HarryAgentSetup.exe"
$InstallerManifest = Join-Path $DownloadDir "HarryAgentSetup.manifest.json"

Invoke-Checked "python" @($SyncScript, "--root", $Root)

New-Item -ItemType Directory -Force -Path $DownloadDir, $BuildDir | Out-Null

$compiler = Get-InnoSetupCompiler
Write-Host "Building HarryAgentSetup.exe from $InstallerScript"
Invoke-Checked $compiler @("/Q", "/O$BuildDir", "/FHarryAgentSetup", $InstallerScript)

if (-not (Test-Path $InstallerExe)) {
    throw "Installer build did not create $InstallerExe"
}

Copy-Item $InstallerExe (Join-Path $DownloadDir "HarryAgentSetup.exe") -Force

$versionsJson = Invoke-PythonJson "import json; from app.versions import BRAIN_VERSION, AGENT_VERSION; from app.ui.db import _load_schema_current; print(json.dumps({'brain_version': BRAIN_VERSION, 'agent_version': AGENT_VERSION, 'schema_current': _load_schema_current()}))"
$versions = $versionsJson | ConvertFrom-Json

if (-not $versions -or [string]::IsNullOrWhiteSpace([string]$versions.brain_version) -or [string]::IsNullOrWhiteSpace([string]$versions.agent_version) -or [string]::IsNullOrWhiteSpace([string]$versions.schema_current)) {
    throw "Windows installer version metadata was empty or invalid."
}

$manifest = [ordered]@{
    installer_name = "HarryAgentSetup.exe"
    brain_version = $versions.brain_version
    agent_version = $versions.agent_version
    schema_current = $versions.schema_current
    source_iss_sha256 = (Get-FileHash $InstallerScript -Algorithm SHA256).Hash
    agent_binary_sha256 = (Get-FileHash (Join-Path $Root "app/dist/windows/harry_agent.exe") -Algorithm SHA256).Hash
    built_utc = (Get-Date).ToUniversalTime().ToString("o")
}

$manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $InstallerManifest -Encoding UTF8

Write-Host "Installer artifact: $(Join-Path $DownloadDir 'HarryAgentSetup.exe')"
Write-Host "Manifest: $InstallerManifest"
Write-Host "Brain version: $($versions.brain_version)"
Write-Host "Agent version: $($versions.agent_version)"
Write-Host "Schema version: $($versions.schema_current)"
