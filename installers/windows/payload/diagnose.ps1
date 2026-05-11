$ErrorActionPreference = "Stop"

$InstallRoot = "C:\ProgramData\Harry"
$AgentExe = Join-Path $InstallRoot "harry_agent.exe"
$ConfigPath = Join-Path $InstallRoot "agent_config.json"
$LogDir = Join-Path $InstallRoot "logs"
$InstallLog = Join-Path $LogDir "HarryAgent.install.log"
$RuntimeLog = Join-Path $LogDir "HarryAgent.runtime.log"
$ServiceExe = Join-Path $InstallRoot "HarryAgentService.exe"
$ServiceName = "HarryAgent"

function Get-ServiceState {
    try {
        $output = & (Join-Path $env:SystemRoot "System32\sc.exe") query $ServiceName 2>&1
        foreach ($line in @($output)) {
            if ($line -match 'STATE\s*:\s*\d+\s+(\w+)') {
                return $Matches[1].ToUpperInvariant()
            }
        }
    } catch {
    }

    if (Test-Path $ServiceExe) {
        try {
            $output = & $ServiceExe status 2>&1
            foreach ($line in @($output)) {
                if ($line -match 'STATE\s*:\s*\d+\s+(\w+)') {
                    return $Matches[1].ToUpperInvariant()
                }
            }
        } catch {
        }
    }

    if (-not (Test-Path $ServiceExe)) {
        return "missing"
    }

    return "unknown"
}

function Get-DisplayValue {
    param([object]$Value)

    if ($null -eq $Value) {
        return "<missing>"
    }

    $text = "$Value".Trim()
    if ([string]::IsNullOrWhiteSpace($text)) {
        return "<missing>"
    }

    return $text
}

function Show-FileList {
    Write-Host "Installed files:"
    if (Test-Path $InstallRoot) {
        Get-ChildItem $InstallRoot -File | Sort-Object Name | ForEach-Object {
            Write-Host ("  {0} ({1} bytes)" -f $_.Name, $_.Length)
        }
    } else {
        Write-Host "  <install root missing>"
    }
}

function Show-Config {
    Write-Host ""
    Write-Host "Configured Brain URL:"
    if (Test-Path $ConfigPath) {
        try {
            $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
            Write-Host ("  public_base_url: {0}" -f (Get-DisplayValue $config.public_base_url))
            Write-Host ("  brain_url: {0}" -f (Get-DisplayValue $config.brain_url))
            Write-Host ("  ingest_url: {0}" -f (Get-DisplayValue $config.ingest_url))
            Write-Host ("  agent_version: {0}" -f (Get-DisplayValue $config.agent_version))
        } catch {
            Write-Host "  <could not parse config>"
        }
    } else {
        Write-Host "  <missing>"
    }
}

function Show-AgentVersion {
    Write-Host ""
    Write-Host "Agent version:"
    if (Test-Path $AgentExe) {
        try {
            $version = (& $AgentExe --version 2>$null | Select-Object -First 1).Trim()
            Write-Host ("  {0}" -f ($(if ($version) { $version } else { "<unknown>" })))
        } catch {
            Write-Host "  <failed to read version>"
        }
    } else {
        Write-Host "  <missing>"
    }
}

function Show-ServiceStatus {
    Write-Host ""
    Write-Host "Service status:"
    Write-Host ("  Windows service: {0}" -f (Get-ServiceState))
    Write-Host "  Scheduled task: not used"
}

function Show-HealthChecks {
    Write-Host ""
    Write-Host "Health / discovery test:"
    if (Test-Path $AgentExe) {
        try {
            $json = & $AgentExe --diagnostics 2>$null
            if ($LASTEXITCODE -eq 0 -and $json) {
                $diag = $json | ConvertFrom-Json
                Write-Host ("  discovery_ok: {0}" -f $diag.discovery_ok)
                Write-Host ("  discovery_service: {0}" -f $diag.discovery_service)
                Write-Host ("  discovery_canonical_base_url: {0}" -f (Get-DisplayValue $diag.discovery_canonical_base_url))
                Write-Host ("  discovery_recommended_lan_url: {0}" -f (Get-DisplayValue $diag.discovery_recommended_lan_url))
                Write-Host ("  health_check_ok: {0}" -f $diag.health_check_ok)
                Write-Host ("  health_check_status: {0}" -f $diag.health_check_status)
                Write-Host ("  ingest_probe_ok: {0}" -f $diag.ingest_probe_ok)
                Write-Host ("  ingest_probe_status: {0}" -f $diag.ingest_probe_status)
                return
            }
        } catch {
        }
    }
    Write-Host "  <unavailable>"
}

function Show-Logs {
    Write-Host ""
    Write-Host "Log files:"
    foreach ($path in @($InstallLog, $RuntimeLog)) {
        if (Test-Path $path) {
            Write-Host ("  {0}" -f $path)
        } else {
            Write-Host ("  {0} (missing)" -f $path)
        }
    }
}

Write-Host "Harry Agent diagnostics"
Write-Host ("Install root: {0}" -f $InstallRoot)
Show-FileList
Show-Config
Show-AgentVersion
Show-ServiceStatus
Show-HealthChecks
Show-Logs
