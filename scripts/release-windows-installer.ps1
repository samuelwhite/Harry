param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$TargetHost,
    [string]$TargetUser = [Environment]::UserName,
    [string]$TargetPath = "/opt/harry/downloads"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = (Resolve-Path $Root).Path
$BuildScript = Join-Path $Root "scripts/build-windows-installer.ps1"
$DeployScript = Join-Path $Root "scripts/deploy-windows-installer.ps1"
$PwshExe = Join-Path $PSHOME "pwsh.exe"

Write-Host "Building Windows installer..."
& $PwshExe -File $BuildScript
if ($LASTEXITCODE -ne 0) {
    throw "Windows installer build failed with exit code $LASTEXITCODE"
}

if ([string]::IsNullOrWhiteSpace($TargetHost)) {
    Write-Host ""
    Write-Host "Build complete."
    Write-Host "Next steps:"
    Write-Host "  Copy downloads\\HarryAgentSetup.exe to your Brain downloads directory."
    Write-Host "  Copy downloads\\HarryAgentSetup.manifest.json to the same directory."
    Write-Host "  Or run this helper again with -TargetHost <brain-host> -TargetUser <ssh-user>."
    exit 0
}

Write-Host "Deploying Windows installer artifacts to $TargetHost..."
& $PwshExe -File $DeployScript -Root $Root -TargetHost $TargetHost -TargetUser $TargetUser -TargetPath $TargetPath
if ($LASTEXITCODE -ne 0) {
    throw "Windows installer deploy failed with exit code $LASTEXITCODE"
}

Write-Host "Release complete."
