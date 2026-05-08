param(
    [string]$BrainUrl,
    [string]$AgentDownloadUrl,
    [string]$CurrentVersion
)

$ErrorActionPreference = "Stop"

$InstallRoot = "C:\ProgramData\Harry"
$ServiceExe = Join-Path $InstallRoot "HarryAgentService.exe"
$AgentExe = Join-Path $InstallRoot "harry_agent.exe"
$AgentLkg = Join-Path $InstallRoot "harry_agent.exe.lkg"
$UpdaterLog = Join-Path $InstallRoot "HarryAgent.update.log"

function Write-UpdateLog {
    param([string]$Message)
    try {
        $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        Add-Content -Path $UpdaterLog -Value "[$ts] $Message" -Encoding UTF8
    } catch {
    }
}

function Invoke-ServiceCommand {
    param([string]$Action)

    if (-not (Test-Path $ServiceExe)) {
        return
    }

    try {
        & $ServiceExe $Action | Out-Host
    } catch {
        Write-UpdateLog "service_$Action_failed error=$($_.Exception.Message)"
    }
}

function Test-ExeHeader {
    param([string]$Path)

    try {
        if (-not (Test-Path $Path)) {
            return $false
        }

        $bytes = [System.IO.File]::ReadAllBytes($Path)
        return $bytes.Length -ge 2 -and $bytes[0] -eq 0x4D -and $bytes[1] -eq 0x5A
    } catch {
        return $false
    }
}

function Get-UpdateUrl {
    if (-not [string]::IsNullOrWhiteSpace($AgentDownloadUrl)) {
        return $AgentDownloadUrl.Trim().TrimEnd("/")
    }

    if (-not [string]::IsNullOrWhiteSpace($BrainUrl)) {
        return ($BrainUrl.Trim().TrimEnd("/") + "/downloads/windows-agent-exe")
    }

    throw "No agent download URL was provided."
}

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

$downloadUrl = Get-UpdateUrl
$tempExe = Join-Path $env:TEMP ("harry_agent_update_{0}.exe" -f ([guid]::NewGuid().ToString("N")))

try {
    Write-Host "Downloading Windows agent update from $downloadUrl"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $tempExe -TimeoutSec 30 -UseBasicParsing

    if (-not (Test-Path $tempExe)) {
        throw "download_failed"
    }

    $tempInfo = Get-Item $tempExe
    if ($tempInfo.Length -lt 1024) {
        throw "download_too_small"
    }

    if (-not (Test-ExeHeader $tempExe)) {
        throw "download_not_exe"
    }

    if (Test-Path $AgentExe) {
        $currentHash = (Get-FileHash $AgentExe -Algorithm SHA256).Hash
        $nextHash = (Get-FileHash $tempExe -Algorithm SHA256).Hash
        if ($currentHash -eq $nextHash) {
            Write-Host "Windows agent is already up to date."
            Remove-Item $tempExe -Force -ErrorAction SilentlyContinue
            exit 0
        }
        Copy-Item $AgentExe $AgentLkg -Force
    }

    Write-Host "Stopping Harry Agent service..."
    Invoke-ServiceCommand -Action "stop"

    Write-Host "Uninstalling Harry Agent service..."
    Invoke-ServiceCommand -Action "uninstall"

    Move-Item -Force $tempExe $AgentExe

    Write-Host "Installing Harry Agent service..."
    if (Test-Path $ServiceExe) {
        & $ServiceExe install | Out-Host
    }

    Write-Host "Starting Harry Agent service..."
    if (Test-Path $ServiceExe) {
        & $ServiceExe start | Out-Host
    }

    Write-Host "Windows agent updated successfully."
    Write-Host "Current version: $CurrentVersion"
    Write-Host "New file: $AgentExe"
    Write-UpdateLog "update_success current=$CurrentVersion download_url=$downloadUrl"
    exit 0
} catch {
    Write-Host ""
    Write-Host "Windows agent update failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-UpdateLog "update_failed current=$CurrentVersion download_url=$downloadUrl error=$($_.Exception.Message)"

    try {
        if (Test-Path $AgentLkg) {
            Copy-Item $AgentLkg $AgentExe -Force
            Write-Host "Restored previous agent binary." -ForegroundColor Yellow
        }
    } catch {
        Write-UpdateLog "restore_failed error=$($_.Exception.Message)"
    }

    try {
        if (Test-Path $ServiceExe) {
            & $ServiceExe install | Out-Host
            & $ServiceExe start | Out-Host
        }
    } catch {
        Write-UpdateLog "restart_failed error=$($_.Exception.Message)"
    }

    exit 1
} finally {
    if (Test-Path $tempExe) {
        Remove-Item $tempExe -Force -ErrorAction SilentlyContinue
    }
}
