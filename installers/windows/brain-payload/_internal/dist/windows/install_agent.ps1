param(
    [ValidateSet("automatic", "manual", "automatic-multi")]
    [string]$InstallerMode = "",
    [string]$BrainUrl = "",
    [switch]$DebugInstaller
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $currentUser = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $currentUser.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Normalize-BrainUrl {
    param (
        [string]$InputUrl
    )

    $url = "$InputUrl".Trim()

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
        throw "Invalid Harry Brain address: $InputUrl"
    }

    $scheme = $uri.Scheme
    $brainHost = $uri.Host
    $port = $uri.Port

    if ([string]::IsNullOrWhiteSpace($brainHost)) {
        throw "Invalid Harry Brain address: $InputUrl"
    }

    # If no explicit port was supplied, Uri will give default 80/443.
    # For Harry, default to 8789 unless the user explicitly entered a port.
    $explicitPort = $false
    if ($InputUrl -match ":\d+(/|$)") {
        $explicitPort = $true
    }

    if (-not $explicitPort) {
        $port = 8789
    }

    return "${scheme}://${brainHost}:${port}"
}

function Get-DefaultBrainPort {
    if ($env:HARRY_PUBLIC_PORT -match '^\d+$') {
        $port = [int]$env:HARRY_PUBLIC_PORT
        if ($port -ge 1 -and $port -le 65535) {
            return $port
        }
    }

    return 8789
}

function Get-InstallerDiscoveryMode {
    if (-not [string]::IsNullOrWhiteSpace($InstallerMode)) {
        return $InstallerMode
    }

    if (-not [string]::IsNullOrWhiteSpace($env:HARRY_INSTALLER_MODE)) {
        switch -Regex ($env:HARRY_INSTALLER_MODE.Trim().ToLowerInvariant()) {
            '^(automatic|auto)$' { return "automatic" }
            '^(manual)$' { return "manual" }
            '^(multi|automatic-multi|auto-multi)$' { return "automatic-multi" }
        }
    }

    return "automatic"
}

function Get-InstallerBrainUrl {
    if (-not [string]::IsNullOrWhiteSpace($BrainUrl)) {
        return $BrainUrl
    }

    if (-not [string]::IsNullOrWhiteSpace($env:HARRY_INSTALLER_BRAIN_URL)) {
        return $env:HARRY_INSTALLER_BRAIN_URL
    }

    return $null
}

function Invoke-ServiceCommand {
    param(
        [string]$Action
    )

    if (-not (Test-Path $ServiceExe)) {
        return $false
    }

    try {
        & $ServiceExe $Action | Out-Host
        return $true
    } catch {
        Write-Host "Service command '$Action' failed: $($_.Exception.Message)" -ForegroundColor Yellow
        return $false
    }
}

function Invoke-TaskKillBestEffort {
    param(
        [string]$ImageName
    )

    if ([string]::IsNullOrWhiteSpace($ImageName)) {
        return $false
    }

    $output = $null
    try {
        $output = & (Join-Path $env:SystemRoot "System32\taskkill.exe") /F /T /IM $ImageName 2>&1
    } catch {
        $output = @($_.Exception.Message)
    }

    $text = @($output) -join "`n"
    if ($text) {
        $text | Out-Host
        foreach ($line in @($output)) {
            if ($line) {
                Write-InstallLog ("taskkill {0}" -f $line)
            }
        }
    }

    if ($text -match 'not found' -or $text -match 'No running instance') {
        Write-InstallLog "taskkill_process_absent image=$ImageName"
        return $false
    }

    if ($LASTEXITCODE -ne 0) {
        Write-InstallLog "taskkill_exit_code=$LASTEXITCODE image=$ImageName"
    } else {
        Write-InstallLog "taskkill_requested image=$ImageName"
    }

    return $true
}

function Get-HarryAgentServiceState {
    try {
        $result = & (Join-Path $env:SystemRoot "System32\sc.exe") query "HarryAgent" 2>&1
        foreach ($line in @($result)) {
            if ($line -match 'STATE\s*:\s*\d+\s+(\w+)') {
                return $Matches[1].ToUpperInvariant()
            }
        }
    } catch {
    }

    if (Test-Path $ServiceExe) {
        try {
            $result = & $ServiceExe status 2>&1
            foreach ($line in @($result)) {
                if ($line -match 'STATE\s*:\s*\d+\s+(\w+)') {
                    return $Matches[1].ToUpperInvariant()
                }
            }
        } catch {
        }
    }

    return $null
}

function Test-HarryAgentServiceRegistered {
    $state = Get-HarryAgentServiceState
    return -not [string]::IsNullOrWhiteSpace($state)
}

function Test-HarryAgentServiceRunning {
    $state = Get-HarryAgentServiceState
    return $state -eq "RUNNING" -or $state -eq "START_PENDING" -or $state -eq "STOP_PENDING"
}

function Wait-HarryAgentServiceProcessExit {
    param(
        [int]$TimeoutSeconds = 20
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-HarryAgentServiceRunning)) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }

    return -not (Test-HarryAgentServiceRunning)
}

function Wait-HarryAgentServiceProcessStart {
    param(
        [int]$TimeoutSeconds = 20
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ((Get-HarryAgentServiceState) -eq "RUNNING") {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }

    return (Get-HarryAgentServiceState) -eq "RUNNING"
}

function Stop-HarryAgentService {
    if (-not (Test-Path $ServiceExe)) {
        return
    }

    if (-not (Test-HarryAgentServiceRegistered)) {
        return
    }

    Write-Host "Stopping Harry Agent service..."
    [void](Invoke-ServiceCommand -Action "stop")

    if (-not (Wait-HarryAgentServiceProcessExit -TimeoutSeconds 20)) {
        Write-Host "Service is still running; trying taskkill fallback..." -ForegroundColor Yellow
        [void](Invoke-TaskKillBestEffort -ImageName "HarryAgentService.exe")
        if (-not (Wait-HarryAgentServiceProcessExit -TimeoutSeconds 10)) {
            throw "Harry Agent service is still running after stop attempts."
        }
    }
}

function Start-HarryAgentService {
    if (-not (Test-Path $ServiceExe)) {
        throw "HarryAgentService.exe was not found after installation."
    }

    Write-Host "Installing Harry Agent service..."
    if (-not (Invoke-ServiceCommand -Action "install")) {
        throw "Failed to install Harry Agent service."
    }

    if (-not (Test-HarryAgentServiceRegistered)) {
        throw "Harry Agent service did not register after install."
    }

    Write-Host "Starting Harry Agent service..."
    if (-not (Invoke-ServiceCommand -Action "start")) {
        throw "Failed to start Harry Agent service."
    }

    if (-not (Wait-HarryAgentServiceProcessStart -TimeoutSeconds 20)) {
        throw "Harry Agent service did not start successfully."
    }
}

function Get-FirstLocalIPv4 {
    try {
        $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -notlike "127.*" -and
                $_.IPAddress -notlike "169.254.*" -and
                $_.PrefixOrigin -ne "WellKnown"
            } |
            Select-Object -ExpandProperty IPAddress

        foreach ($ip in $ips) {
            if (-not [string]::IsNullOrWhiteSpace($ip)) {
                return $ip
            }
        }
    } catch {
    }

    return $null
}

function Get-SubnetCandidates {
    param (
        [string]$Ip,
        [int]$Port
    )

    # Discovery only fans out across the active LAN subnet(s) derived from local IPv4
    # adapters, so we probe nearby RFC1918 addresses instead of sweeping unrelated ranges.
    if ([string]::IsNullOrWhiteSpace($Ip)) {
        return @()
    }

    if ($Ip -notmatch '^\d+\.\d+\.\d+\.\d+$') {
        return @()
    }

    if ($Ip -match '^127\.|^169\.254\.|^172\.(1[6-9]|2\d|3[0-1])\.|^192\.168\.240\.') {
        return @()
    }

    $prefix = Get-SubnetPrefix3 -Ip $Ip
    if (-not $prefix) {
        return @()
    }

    $lastOctets = @(1, 2, 10, 20, 50, 100, 150, 200, 254)
    $candidates = @()

    foreach ($octet in $lastOctets) {
        $candidate = "${prefix}.${octet}"
        if ($candidate -ne $Ip) {
            $candidates += "http://${candidate}:${Port}"
        }
    }

    return $candidates
}

function Get-DiscoveryCandidates {
    param (
        [int]$Port
    )

    $candidates = New-Object System.Collections.Generic.List[string]
    $seen = New-Object System.Collections.Generic.HashSet[string]

    foreach ($seed in @("http://harry.local:$Port", "http://harry-brain.local:$Port")) {
        if ($seen.Add($seed)) { [void]$candidates.Add($seed) }
    }

    $localIps = New-Object System.Collections.Generic.List[string]
    try {
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -match '^\d+\.\d+\.\d+\.\d+$' -and
                $_.IPAddress -notlike '127.*' -and
                $_.IPAddress -notlike '169.254.*'
            } |
            ForEach-Object {
                if ($seen.Add($_.IPAddress)) {
                    [void]$localIps.Add($_.IPAddress)
                }
            }
    } catch {
    }

    try {
        Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
            Select-Object -ExpandProperty NextHop |
            ForEach-Object {
                if ($_ -match '^\d+\.\d+\.\d+\.\d+$' -and $seen.Add($_)) {
                    [void]$localIps.Add($_)
                }
            }
    } catch {
    }

    try {
        Get-NetNeighbor -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -match '^\d+\.\d+\.\d+\.\d+$' -and
                $_.IPAddress -notlike '127.*' -and
                $_.IPAddress -notlike '169.254.*'
            } |
            ForEach-Object {
                if ($seen.Add($_.IPAddress)) {
                    [void]$localIps.Add($_.IPAddress)
                }
            }
    } catch {
    }

    foreach ($ip in $localIps) {
        foreach ($candidate in (Get-SubnetCandidates -Ip $ip -Port $Port)) {
            if ($seen.Add($candidate)) {
                [void]$candidates.Add($candidate)
            }
        }
    }

    return $candidates
}

function Test-BrainDiscoveryCandidate {
    param (
        [string]$BrainUrl
    )

    $base = "$BrainUrl".Trim().TrimEnd("/")
    if ([string]::IsNullOrWhiteSpace($base)) {
        return $null
    }

    foreach ($path in @("/discover", "/.well-known/harry-brain")) {
        $url = "${base}${path}"
        try {
            $response = Invoke-WebRequest -Uri $url -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
            $payload = $response.Content | ConvertFrom-Json
            if ($payload -and $payload.service -eq "harry-brain" -and $payload.ok -eq $true) {
                if ($payload.canonical_base_url) {
                    return ($payload.canonical_base_url).TrimEnd("/")
                }
                if ($payload.recommended_lan_url) {
                    return ($payload.recommended_lan_url).TrimEnd("/")
                }
                if ($payload.base_url) {
                    return ($payload.base_url).TrimEnd("/")
                }
                return $base
            }
        } catch {
        }
    }

    return $null
}

function Discover-HarryBrain {
    param (
        [int]$Port,
        [switch]$MultiDiscovery
    )

    Write-Host "Searching for Harry Brain..."

    $candidates = Get-DiscoveryCandidates -Port $Port
    Write-Host ("Discovery candidates: {0}" -f $candidates.Count)

    $found = New-Object System.Collections.Generic.List[string]
    $seen = New-Object System.Collections.Generic.HashSet[string]

    foreach ($candidate in $candidates) {
        Write-Host ("  probing {0}" -f $candidate)
        $discovered = Test-BrainDiscoveryCandidate -BrainUrl $candidate
        if ($discovered -and $seen.Add($discovered)) {
            [void]$found.Add($discovered)
            Write-Host ("    discovered {0}" -f $discovered)
            if (-not $MultiDiscovery) {
                return @($discovered)
            }
        }
    }

    if ($found.Count -eq 0) {
        Write-Host "No Harry Brain discovery responses were found from local candidates."
    }

    return $found
}

function Get-SubnetPrefix3 {
    param (
        [string]$Ip
    )

    if ([string]::IsNullOrWhiteSpace($Ip)) {
        return $null
    }

    $parts = $Ip.Split(".")
    if ($parts.Length -ne 4) {
        return $null
    }

    return ($parts[0..2] -join ".")
}

function Test-BrainReachability {
    param (
        [string]$BrainUrl
    )

    try {
        $uri = [System.Uri]$BrainUrl
    } catch {
        throw "Invalid Harry Brain address: $BrainUrl"
    }

    $hostName = $uri.Host
    $port = $uri.Port

    if ($port -lt 1) {
        $port = 8789
    }

    Write-Host ""
    Write-Host "Checking connectivity to Harry Brain..."
    Write-Host "Address: $BrainUrl"
    Write-Host "Host   : $hostName"
    Write-Host "Port   : $port"

    $result = $null
    try {
        $result = Test-NetConnection -ComputerName $hostName -Port $port -WarningAction SilentlyContinue
    } catch {
        $result = $null
    }

    if ($result -and $result.TcpTestSucceeded) {
        Write-Host "Connection check succeeded." -ForegroundColor Green
        return
    }

    $localIp = Get-FirstLocalIPv4
    $brainIp = $null

    try {
        $resolved = Resolve-DnsName -Name $hostName -Type A -ErrorAction Stop |
            Where-Object { $_.IPAddress } |
            Select-Object -First 1 -ExpandProperty IPAddress

        if ($resolved) {
            $brainIp = $resolved
        }
    } catch {
        if ($hostName -match '^\d+\.\d+\.\d+\.\d+$') {
            $brainIp = $hostName
        }
    }

    Write-Host ""
    Write-Host "ERROR: Could not reach Harry Brain at $BrainUrl" -ForegroundColor Red
    Write-Host ""
    Write-Host "This usually means one of the following:" -ForegroundColor Yellow
    Write-Host " - The Brain address is incorrect"
    Write-Host " - Harry Brain is not running"
    Write-Host " - The machines are on different networks without routing"
    Write-Host " - A firewall is blocking the connection (TCP port $port)"
    Write-Host ""
    Write-Host "Try:" -ForegroundColor Cyan
    Write-Host " - Open $BrainUrl in a browser from this machine"
    Write-Host " - Check that the Brain machine is powered on and Harry Brain is running"
    Write-Host " - Check both machines are on the same network, or that routing is allowed between them"
    Write-Host " - Ensure TCP port $port is allowed through the firewall on the Brain machine"
    Write-Host ""

    if ($localIp -and $brainIp) {
        $localPrefix = Get-SubnetPrefix3 -Ip $localIp
        $brainPrefix = Get-SubnetPrefix3 -Ip $brainIp

        if ($localPrefix -and $brainPrefix -and $localPrefix -ne $brainPrefix) {
            Write-Host "Note: This machine ($localIp) appears to be on a different subnet than the Brain ($brainIp)." -ForegroundColor Yellow
            Write-Host "      This requires routing or firewall rules between those networks."
            Write-Host ""
        }
    }

    throw "Harry Brain could not be reached."
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
$LogDir = Join-Path $InstallRoot "logs"
$InstallLog = Join-Path $LogDir "HarryAgent.install.log"
$RuntimeLog = Join-Path $LogDir "HarryAgent.runtime.log"
$AgentExe = Join-Path $InstallRoot "harry_agent.exe"
$ConfigPath = Join-Path $InstallRoot "agent_config.json"
$ServiceExe = Join-Path $InstallRoot "HarryAgentService.exe"
$ServiceXml = Join-Path $InstallRoot "HarryAgentService.xml"
$DiagnoseScript = Join-Path $InstallRoot "diagnose.ps1"
$UpdaterScript = Join-Path $InstallRoot "update_agent.ps1"
$WrapperLog = Join-Path $InstallRoot "HarryAgentService.wrapper.log"
$OutLog = Join-Path $InstallRoot "HarryAgentService.out.log"
$ErrLog = Join-Path $InstallRoot "HarryAgentService.err.log"
$InstallSessionId = [guid]::NewGuid().ToString()
$HadExistingInstall = (Test-Path $AgentExe) -or (Test-Path $ServiceExe) -or (Test-Path $ServiceXml) -or (Test-Path $ConfigPath)
$TranscriptStarted = $false

function Write-InstallLog {
    param([string]$Message)

    try {
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
        $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        Add-Content -Path $InstallLog -Value "[$ts] $Message" -Encoding UTF8
    } catch {
    }
}

function Write-RuntimeMarker {
    param([string]$Message)

    try {
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
        $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        Add-Content -Path $RuntimeLog -Value "[$ts] $Message" -Encoding UTF8
    } catch {
    }
}

function Invoke-AgentOneShotSend {
    param(
        [string]$Reason,
        [string]$BrainUrl
    )

    if (-not (Test-Path $AgentExe)) {
        Write-InstallLog "one_shot_send_skipped reason=$Reason agent_missing"
        return [pscustomobject]@{
            Succeeded = $false
            Unsupported = $false
            ExitCode = $null
            Output = "Agent executable missing"
        }
    }

    Write-Host "Triggering one-shot telemetry send..."
    $validationCommand = "& `"$AgentExe`" --send-once"
    Write-InstallLog "one_shot_send_attempt reason=$Reason brain=$BrainUrl agent=$AgentExe command=$validationCommand"

    $output = $null
    try {
        $output = & $AgentExe --send-once 2>&1
    } catch {
        $output = @($_.Exception.Message)
    }

    $text = @($output) -join "`n"
    if ($text) {
        Write-InstallLog "one_shot_send_output $text"
    }

    if ($LASTEXITCODE -eq 0) {
        Write-InstallLog "one_shot_send_success exit_code=0"
        return [pscustomobject]@{
            Succeeded = $true
            Unsupported = $false
            ExitCode = 0
            Output = $text
        }
    }

    Write-InstallLog "one_shot_send_failure exit_code=$LASTEXITCODE"
    $unsupported = [string]::IsNullOrWhiteSpace($text) -eq $false -and ($text -match '(?i)usage:\s+harry_agent\.exe' -or $text -match '(?i)unrecognized arguments?')
    return [pscustomobject]@{
        Succeeded = $false
        Unsupported = $unsupported
        ExitCode = $LASTEXITCODE
        Output = $text
    }
}

function Set-InstallerBusyStatus {
    param([string]$Message)

    try { $WizardForm.ProgressGauge.Style = npbstMarquee } catch { }
    try {
        $WizardForm.StatusLabel.Caption = $Message
        $WizardForm.StatusLabel.Update()
    } catch {
    }
}

function Set-InstallerIdleStatus {
    param([string]$Message)

    try { $WizardForm.ProgressGauge.Style = npbstNormal } catch { }
    try {
        $WizardForm.StatusLabel.Caption = $Message
        $WizardForm.StatusLabel.Update()
    } catch {
    }
}

function Wait-FirstTelemetryResult {
    param(
        [string]$SessionId,
        [string]$BrainUrl,
        [int]$TimeoutSeconds = 180
    )

    $marker = "install_validation_start session=$SessionId"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $fallbackAttempted = $false
    $markerFound = $false
    $seenMarker = $false

    Write-Host "Waiting for first telemetry send..."
    Write-InstallLog "validation_wait_for_first_send session=$SessionId timeout_seconds=$TimeoutSeconds"

    while ((Get-Date) -lt $deadline) {
        if (Test-Path $RuntimeLog) {
            $lines = @(Get-Content -Path $RuntimeLog -Tail 500 -ErrorAction SilentlyContinue)
            foreach ($line in $lines) {
                if (-not $seenMarker) {
                    if ($line -match [regex]::Escape($marker)) {
                        $seenMarker = $true
                        Write-InstallLog "runtime_marker_seen session=$SessionId"
                    }
                    continue
                }

                if ($line -match 'ingest_success') {
                    $markerFound = $true
                    Write-InstallLog ("first_telemetry_success line={0}" -f $line)
                    Write-InstallLog "first_telemetry_marker_found=true"
                    return
                }

                if ($line -match 'ingest_failure') {
                    $markerFound = $true
                    Write-InstallLog ("first_telemetry_failure line={0}" -f $line)
                    Write-InstallLog "first_telemetry_marker_found=true"
                    throw "First telemetry send failed. See $RuntimeLog"
                }
            }
        }

        if (-not $fallbackAttempted -and (Get-Date) -ge $deadline.AddSeconds(-90)) {
            $fallbackAttempted = $true
            $validation = Invoke-AgentOneShotSend -Reason "validation_fallback" -BrainUrl $BrainUrl
            Write-InstallLog "one_shot_send_result exit_code=$($validation.ExitCode) unsupported=$($validation.Unsupported)"
            if ($validation.Unsupported) {
                throw "Agent validation command is unsupported. See $RuntimeLog"
            }

            if ($validation.Succeeded) {
                Write-InstallLog "first_telemetry_success via=send_once marker_found=$markerFound"
                return
            }

            Write-InstallLog "one_shot_send_retry_needed"
        }

        Start-Sleep -Seconds 2
    }

    if (-not $fallbackAttempted) {
        $validation = Invoke-AgentOneShotSend -Reason "validation_timeout" -BrainUrl $BrainUrl
        Write-InstallLog "one_shot_send_result exit_code=$($validation.ExitCode) unsupported=$($validation.Unsupported)"
        if ($validation.Unsupported) {
            throw "Agent validation command is unsupported. See $RuntimeLog"
        }

        if ($validation.Succeeded) {
            Write-InstallLog "first_telemetry_success via=send_once_timeout_fallback marker_found=$markerFound"
            return
        }
    }

    throw "Timed out waiting for first telemetry send. See $RuntimeLog"
}

function Copy-InstallerPayloadFile {
    param(
        [string]$FileName,
        [string]$TargetPath
    )

    $SourcePath = Join-Path $scriptDir $FileName

    if (-not (Test-Path $SourcePath)) {
        Write-Host "ERROR: $FileName not found in the package folder."
        Write-Host "Expected at: $SourcePath"
        Write-InstallLog "missing_file $FileName source=$SourcePath target=$TargetPath"
        exit 1
    }

    Write-Host ("Payload source: {0}" -f $SourcePath)
    Write-Host ("Install target: {0}" -f $TargetPath)
    Write-InstallLog "payload_copy file=$FileName source=$SourcePath target=$TargetPath"

    try {
        $resolvedSource = (Resolve-Path -LiteralPath $SourcePath).Path
        $resolvedTarget = $null
        if (Test-Path -LiteralPath $TargetPath) {
            $resolvedTarget = (Resolve-Path -LiteralPath $TargetPath).Path
        }

        if ($resolvedSource -and $resolvedTarget -and ($resolvedSource -ieq $resolvedTarget)) {
            Write-Host ("Already staged: {0}" -f $FileName)
            Write-InstallLog "payload_copy_same_path_avoided file=$FileName path=$resolvedTarget"
            return
        }
    } catch {
        Write-InstallLog "payload_copy_path_resolution_failed file=$FileName error=$($_.Exception.Message)"
    }

    Copy-Item $SourcePath $TargetPath -Force
    Write-InstallLog "payload_copy_complete file=$FileName"
}

function Test-InstalledAgentState {
    param(
        [string]$ConfiguredBrainUrl,
        [string]$ExpectedAgentVersion
    )

    $issues = New-Object System.Collections.Generic.List[string]

    if (-not (Test-Path $ConfigPath)) {
        $issues.Add("agent_config.json is missing")
    } else {
        try {
            $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
            if (-not $config.public_base_url) { $issues.Add("configured Brain URL is empty") }
            if (-not $config.brain_url) { $issues.Add("brain_url is empty") }
            if (-not $config.ingest_url) { $issues.Add("ingest_url is empty") }
            if (-not $config.agent_version) { $issues.Add("agent_version is empty") }
        } catch {
            $issues.Add("agent_config.json could not be parsed")
        }
    }

    if (-not (Test-Path $AgentExe)) {
        $issues.Add("harry_agent.exe is missing")
    }

    if (-not (Test-HarryAgentServiceRegistered)) {
        $issues.Add("HarryAgent service is not registered")
    }

    if (-not (Test-HarryAgentServiceRunning)) {
        $issues.Add("HarryAgent service is not running")
    }

    if ([string]::IsNullOrWhiteSpace($ConfiguredBrainUrl)) {
        $issues.Add("Brain URL is empty")
    }

    if ([string]::IsNullOrWhiteSpace($ExpectedAgentVersion)) {
        $issues.Add("agent version could not be read")
    }

    if (-not [string]::IsNullOrWhiteSpace($ExpectedAgentVersion) -and $config.agent_version -and ($config.agent_version -ne $ExpectedAgentVersion)) {
        $issues.Add("agent_version mismatch (config=$($config.agent_version); expected=$ExpectedAgentVersion)")
    }

    if ($issues.Count -gt 0) {
        Write-InstallLog ("install_validation_failed issues={0}" -f ($issues -join "; "))
        throw "Post-install validation failed: $($issues -join '; ')"
    }

    Write-InstallLog "install_validation_success"
}

Write-Host ""
Write-Host "Installing Harry Agent to $InstallRoot ..."
Write-Host "Installer source folder: $scriptDir"
Write-Host ("Existing install detected: {0}" -f ($(if ($HadExistingInstall) { "yes" } else { "no" })))
Write-Host "Payload source path: $scriptDir"
Write-Host "Install target path: $InstallRoot"
Write-Host "Install log: $InstallLog"
Write-Host "Runtime log: $RuntimeLog"
Write-InstallLog "payload_source=$scriptDir"
Write-InstallLog "install_target=$InstallRoot"
Write-InstallLog "installer_start existing_install=$HadExistingInstall source=$scriptDir"
Write-Host ""

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

try {
    Start-Transcript -Path $InstallLog -Append | Out-Null
    $TranscriptStarted = $true
} catch {
    Write-Host "Transcript logging could not be started: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-InstallLog "transcript_unavailable error=$($_.Exception.Message)"
}

if ($HadExistingInstall) {
    Stop-HarryAgentService
    Write-InstallLog "existing_service_stopped"
}

$InstallerMode = Get-InstallerDiscoveryMode
$MultiDiscovery = $env:HARRY_INSTALLER_MULTI_DISCOVERY -match '^(1|true|yes)$'
Write-Host "Installer mode: $InstallerMode"
Write-InstallLog "installer_mode=$InstallerMode multi_discovery=$MultiDiscovery"

Copy-InstallerPayloadFile -FileName "harry_agent.exe" -TargetPath $AgentExe
Copy-InstallerPayloadFile -FileName "HarryAgentService.xml" -TargetPath $ServiceXml
Copy-InstallerPayloadFile -FileName "HarryAgentService.exe" -TargetPath $ServiceExe
Copy-InstallerPayloadFile -FileName "update_agent.ps1" -TargetPath $UpdaterScript
Copy-InstallerPayloadFile -FileName "diagnose.ps1" -TargetPath $DiagnoseScript

$brain = $null
Write-Host ""
Write-Host "Connection mode: $InstallerMode"
Write-Host "Automatic discovery will search the local network for Harry Brain unless manual mode was selected."
Write-Host ""

if (-not [string]::IsNullOrWhiteSpace($env:HARRY_PUBLIC_BASE_URL)) {
    try {
        $brain = Normalize-BrainUrl $env:HARRY_PUBLIC_BASE_URL
        Write-Host "Using HARRY_PUBLIC_BASE_URL: $brain"
        Write-InstallLog "brain_source=env value=$brain"
    } catch {
        Write-InstallLog "brain_source=env invalid"
        throw "HARRY_PUBLIC_BASE_URL is invalid."
    }
} elseif ($InstallerMode -eq "automatic" -or $InstallerMode -eq "automatic-multi") {
    $publicPort = Get-DefaultBrainPort
    $discovered = @(Discover-HarryBrain -Port $publicPort -MultiDiscovery:($MultiDiscovery -or $InstallerMode -eq "automatic-multi"))
    Write-InstallLog ("discovery_candidates={0}" -f $discovered.Count)

    if ($discovered.Count -gt 0) {
        $brain = [string](@($discovered)[0])
        Write-Host "Auto-discovered Harry Brain: $brain"
        Write-InstallLog "brain_source=discovery value=$brain"
    } else {
        Write-Host "No Harry Brain was auto-discovered."
        Write-InstallLog "brain_auto_discovery_no_results"
    }
} else {
    Write-Host "Manual Brain address mode selected; discovery scan skipped."
    Write-InstallLog "discovery_skipped_manual_mode"
}

if (-not $brain) {
    if ($InstallerMode -eq "manual") {
        $manualBrain = Get-InstallerBrainUrl
        if ([string]::IsNullOrWhiteSpace($manualBrain)) {
            Write-InstallLog "brain_prompt_cancelled"
            throw "Manual Brain address was not provided."
        }

        try {
            $brain = Normalize-BrainUrl $manualBrain
            Write-InstallLog "brain_source=manual value=$brain"
        } catch {
            Write-InstallLog "brain_source=manual invalid value=$manualBrain"
            throw "Invalid Harry Brain address: $manualBrain"
        }
    } else {
        Write-InstallLog "brain_auto_discovery_failed_noninteractive"
        throw "Harry Brain could not be auto-discovered. Re-run the installer and choose Manual Brain address."
    }
}

try {
    $brain = Normalize-BrainUrl $brain
} catch {
    Write-InstallLog "brain_source=normalized_invalid value=$brain"
    throw "Invalid Harry Brain address: $brain"
}

try {
    $verified = Test-BrainDiscoveryCandidate -BrainUrl $brain
    if (-not $verified) {
        throw "Harry Brain did not advertise discovery metadata at $brain"
    }
    $brain = $verified
    Write-InstallLog "brain_verified=$brain"
} catch {
    Write-InstallLog "brain_verification_failed error=$($_.Exception.Message)"
    throw
}

$config = @{}
if (Test-Path $ConfigPath) {
    try {
        $existingConfig = Get-Content $ConfigPath -Raw | ConvertFrom-Json
        if ($existingConfig) {
            foreach ($prop in $existingConfig.PSObject.Properties) {
                $config[$prop.Name] = $prop.Value
            }
        }
    } catch {
        Write-Host "Could not read existing config; rewriting Brain URL settings." -ForegroundColor Yellow
    }
}

$config.public_base_url = $brain
$config.brain_url = $brain
$config.ingest_url = "$brain/ingest"
$config.agent_version = $agentVersion
$config.configured_at = (Get-Date).ToUniversalTime().ToString("o")
$config | ConvertTo-Json | Set-Content -Encoding UTF8 $ConfigPath

Write-Host ""
Write-Host "Saved config to $ConfigPath"
Write-Host "Brain URL: $brain"
Write-InstallLog "config_written path=$ConfigPath brain_url=$brain"

Write-Host ""
Write-Host "Refreshing Harry Agent service..."

try {
    & $ServiceExe uninstall | Out-Host
    Write-InstallLog "service_uninstall_attempted"
} catch {
    Write-Host "Service uninstall skipped."
    Write-InstallLog "service_uninstall_skipped"
}

Start-HarryAgentService
Write-InstallLog "service_started"

try {
    $agentVersion = (& $AgentExe --version 2>$null | Select-Object -First 1).Trim()
} catch {
    $agentVersion = ""
}

if ([string]::IsNullOrWhiteSpace($agentVersion)) {
    $agentVersion = "unknown"
    Write-InstallLog "agent_version_unavailable"
} else {
    Write-InstallLog "agent_version=$agentVersion"
}

$serviceState = Get-HarryAgentServiceState
if ([string]::IsNullOrWhiteSpace($serviceState)) {
    $serviceState = "unknown"
}

Write-Host ""
Write-Host "Verifying installed agent..."
Write-Host "Agent version: $agentVersion"
Write-Host "Service registration: $serviceState"

Write-RuntimeMarker "install_validation_start session=$InstallSessionId brain=$brain"

try {
    Wait-FirstTelemetryResult -SessionId $InstallSessionId -BrainUrl $brain -TimeoutSeconds 180
} catch {
    Write-InstallLog "initial_send_failed error=$($_.Exception.Message)"
    throw
}

Write-Host ""
Write-Host "Harry Agent installed successfully."
Write-Host "Upgraded existing install: $([bool]$HadExistingInstall)"
Write-Host "Service registration: $serviceState"
try {
    $installedVersion = (& $AgentExe --version 2>$null | Select-Object -First 1).Trim()
    if ($installedVersion) {
        Write-Host "Installed agent version: $installedVersion"
    }
} catch {
    Write-Host "Installed agent version: unknown"
}
Write-Host "Installed agent path: $AgentExe"
Write-Host "Configured Brain URL: $brain"
Write-Host "Ingest URL: $brain/ingest"
Write-Host "Diagnostic script: $DiagnoseScript"
Write-Host "Install log: $InstallLog"
Write-Host "Runtime log: $RuntimeLog"
Write-Host "Files:   $InstallRoot"
Write-Host "Config:  $ConfigPath"
Write-Host "Logs:"
Write-Host "  Wrapper: $WrapperLog"
Write-Host "  Output : $OutLog"
Write-Host "  Errors : $ErrLog"
Write-Host "  Diagnose: $DiagnoseScript"
Write-Host "  Install : $InstallLog"
Write-Host "  Runtime : $RuntimeLog"
Write-Host ""
Write-Host "To watch the main log live in PowerShell, run:"
Write-Host "  Get-Content `"$OutLog`" -Wait"
Write-Host ""
try {
    Test-InstalledAgentState -ConfiguredBrainUrl $brain -ExpectedAgentVersion $agentVersion
} catch {
    Write-InstallLog "post_install_validation_failed error=$($_.Exception.Message)"
    if ($TranscriptStarted) {
        try { Stop-Transcript | Out-Null } catch { }
    }
    throw
}

if ($TranscriptStarted) {
    try { Stop-Transcript | Out-Null } catch { }
}
