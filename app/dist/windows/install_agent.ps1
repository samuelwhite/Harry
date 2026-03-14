$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $currentUser = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $currentUser.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Normalize-BrainUrl {
    param (
        [string]$InputUrl
    )

    $url = $InputUrl.Trim()

    if ([string]::IsNullOrWhiteSpace($url)) {
        return $null
    }

    # Remove trailing slashes
    $url = $url.TrimEnd("/")

    # Add scheme if missing
    if ($url -notmatch "^[a-zA-Z][a-zA-Z0-9+\-.]*://") {
        $url = "http://$url"
    }

    try {
        $uri = [System.Uri]$url
    } catch {
        throw "Invalid Harry Brain URL: $InputUrl"
    }

    $scheme = $uri.Scheme
    $brainHost = $uri.Host
    $port = $uri.Port

    if ([string]::IsNullOrWhiteSpace($brainHost)) {
        throw "Invalid Harry Brain URL: $InputUrl"
    }

    # If no explicit port was supplied, Uri will give default 80/443.
    # For Harry, default to 8787 unless user explicitly entered a port.
    $explicitPort = $false
    if ($InputUrl -match ":\d+(/|$)") {
        $explicitPort = $true
    }

    if (-not $explicitPort) {
        $port = 8787
    }

    return "${scheme}://${brainHost}:${port}"
}

$scriptPath = $MyInvocation.MyCommand.Path
$scriptDir = Split-Path -Parent $scriptPath

if (-not (Test-IsAdmin)) {
    Write-Host ""
    Write-Host "Harry Agent installer needs Administrator rights."
    Write-Host "Re-launching PowerShell as Administrator..."
    Write-Host ""

    Start-Process powershell -Verb RunAs -WorkingDirectory $scriptDir -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$scriptPath`""
    )

    exit 0
}

Set-Location $scriptDir

$InstallRoot = "C:\ProgramData\Harry"
$AgentExe = Join-Path $InstallRoot "harry_agent.exe"
$ConfigPath = Join-Path $InstallRoot "agent_config.json"
$ServiceExe = Join-Path $InstallRoot "HarryAgentService.exe"
$ServiceXml = Join-Path $InstallRoot "HarryAgentService.xml"
$WrapperLog = Join-Path $InstallRoot "HarryAgentService.wrapper.log"
$OutLog = Join-Path $InstallRoot "HarryAgentService.out.log"
$ErrLog = Join-Path $InstallRoot "HarryAgentService.err.log"

Write-Host ""
Write-Host "Installing Harry Agent to $InstallRoot ..."
Write-Host "Installer source folder: $scriptDir"
Write-Host ""

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

if (Test-Path ".\harry_agent.exe") {
    Copy-Item ".\harry_agent.exe" $AgentExe -Force
} else {
    Write-Host "ERROR: harry_agent.exe not found in the package folder."
    Write-Host "Expected at: $scriptDir\harry_agent.exe"
    Read-Host "Press Enter to exit"
    exit 1
}

if (Test-Path ".\HarryAgentService.xml") {
    Copy-Item ".\HarryAgentService.xml" $ServiceXml -Force
} else {
    Write-Host "ERROR: HarryAgentService.xml not found in the package folder."
    Write-Host "Expected at: $scriptDir\HarryAgentService.xml"
    Read-Host "Press Enter to exit"
    exit 1
}

if (Test-Path ".\HarryAgentService.exe") {
    Copy-Item ".\HarryAgentService.exe" $ServiceExe -Force
} else {
    Write-Host "ERROR: HarryAgentService.exe not found in the package folder."
    Write-Host "Expected at: $scriptDir\HarryAgentService.exe"
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path $ConfigPath)) {
    Write-Host ""
    Write-Host "Enter the Harry Brain address."
    Write-Host "This is the address of the machine running Harry Brain."
    Write-Host "You can enter just an IP or hostname."
    Write-Host "Examples:"
    Write-Host "  192.168.1.20"
    Write-Host "  192.168.1.20:8787"
    Write-Host "  http://192.168.1.20:8787"
    Write-Host ""

    $defaultBrain = "http://harry-brain:8787"
    $brainInput = Read-Host "Harry Brain address [$defaultBrain]"

    if ([string]::IsNullOrWhiteSpace($brainInput)) {
        $brainInput = $defaultBrain
    }

    try {
        $brain = Normalize-BrainUrl $brainInput
    } catch {
        Write-Host ""
        Write-Host "ERROR: $($_.Exception.Message)"
        Read-Host "Press Enter to exit"
        exit 1
    }

    @{ brain_url = $brain } |
        ConvertTo-Json |
        Set-Content -Encoding UTF8 $ConfigPath

    Write-Host ""
    Write-Host "Saved config to $ConfigPath"
    Write-Host "Brain URL: $brain"
}

Write-Host ""
Write-Host "Refreshing Harry Agent service..."

try {
    & $ServiceExe stop | Out-Host
} catch {
    Write-Host "Service stop skipped."
}

try {
    & $ServiceExe uninstall | Out-Host
} catch {
    Write-Host "Service uninstall skipped."
}

Write-Host ""
Write-Host "Installing Harry Agent service..."
& $ServiceExe install

Write-Host "Starting Harry Agent service..."
& $ServiceExe start

Write-Host ""
Write-Host "Harry Agent installed successfully."
Write-Host "Files:   $InstallRoot"
Write-Host "Config:  $ConfigPath"
Write-Host "Logs:"
Write-Host "  Wrapper: $WrapperLog"
Write-Host "  Output : $OutLog"
Write-Host "  Errors : $ErrLog"
Write-Host ""
Write-Host "To watch the main log live in PowerShell, run:"
Write-Host "  Get-Content `"$OutLog`" -Wait"
Write-Host ""
Read-Host "Press Enter to exit"
