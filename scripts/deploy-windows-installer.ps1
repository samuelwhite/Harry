param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [Parameter(Mandatory = $true)]
    [string]$TargetHost,
    [string]$TargetUser = [Environment]::UserName,
    [string]$TargetPath = "/opt/harry/downloads"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-PythonJson {
    param([string]$RootPath, [string]$Command)

    $oldPythonPath = $env:PYTHONPATH
    $appPath = Join-Path $RootPath "app"
    if ([string]::IsNullOrWhiteSpace($oldPythonPath)) {
        $env:PYTHONPATH = $appPath
    } else {
        $env:PYTHONPATH = $appPath + [IO.Path]::PathSeparator + $oldPythonPath
    }

    try {
        $result = & python -c $Command 2>&1
        if ($LASTEXITCODE -ne 0) {
            $message = ($result | Out-String).Trim()
            throw "Failed to import app.versions or app.ui.db while reading installer metadata.`n$message"
        }

        $json = ($result | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($json)) {
            throw "Installer metadata command returned no output."
        }

        return $json
    } finally {
        $env:PYTHONPATH = $oldPythonPath
    }
}

function Get-CurrentVersions {
    param([string]$RootPath)

    $json = Invoke-PythonJson -RootPath $RootPath -Command "import json; from app.versions import BRAIN_VERSION, AGENT_VERSION; from app.ui.db import _load_schema_current; print(json.dumps({'brain_version': BRAIN_VERSION, 'agent_version': AGENT_VERSION, 'schema_current': _load_schema_current()}))"
    $versions = $json | ConvertFrom-Json
    if (-not $versions -or [string]::IsNullOrWhiteSpace([string]$versions.brain_version) -or [string]::IsNullOrWhiteSpace([string]$versions.agent_version) -or [string]::IsNullOrWhiteSpace([string]$versions.schema_current)) {
        throw "Installer version metadata was empty or invalid."
    }

    return $versions
}

$Root = (Resolve-Path $Root).Path
$DownloadDir = Join-Path $Root "downloads"
$InstallerExe = Join-Path $DownloadDir "HarryAgentSetup.exe"
$InstallerManifest = Join-Path $DownloadDir "HarryAgentSetup.manifest.json"

if (-not (Test-Path $InstallerExe)) {
    throw "Windows installer EXE not found: $InstallerExe"
}

if (-not (Test-Path $InstallerManifest)) {
    throw "Windows installer manifest not found: $InstallerManifest"
}

$versions = Get-CurrentVersions -RootPath $Root
$manifest = Get-Content $InstallerManifest -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $manifest) {
    throw "Windows installer manifest could not be parsed: $InstallerManifest"
}

if ($manifest.installer_name -ne "HarryAgentSetup.exe" -or $manifest.brain_version -ne $versions.brain_version -or $manifest.agent_version -ne $versions.agent_version -or $manifest.schema_current -ne $versions.schema_current) {
    throw "Windows installer manifest versions do not match the current source versions."
}

$scp = Get-Command scp -ErrorAction SilentlyContinue
if (-not $scp) {
    throw "scp was not found. Install OpenSSH client or make scp available on PATH."
}

$remote = "$TargetUser@$TargetHost:$TargetPath"
Write-Host "Copying Windows installer artifacts to $remote"
& $scp.Source $InstallerExe $InstallerManifest $remote
if ($LASTEXITCODE -ne 0) {
    throw "scp failed with exit code $LASTEXITCODE"
}

Write-Host "Copied:"
Write-Host "  $InstallerExe"
Write-Host "  $InstallerManifest"
Write-Host "Destination:"
Write-Host "  $remote"
