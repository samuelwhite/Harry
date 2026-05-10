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
        [int]$Port
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
$AgentExe = Join-Path $InstallRoot "harry_agent.exe"
$ConfigPath = Join-Path $InstallRoot "agent_config.json"
$ServiceExe = Join-Path $InstallRoot "HarryAgentService.exe"
$ServiceXml = Join-Path $InstallRoot "HarryAgentService.xml"
$UpdaterScript = Join-Path $InstallRoot "update_agent.ps1"
$WrapperLog = Join-Path $InstallRoot "HarryAgentService.wrapper.log"
$OutLog = Join-Path $InstallRoot "HarryAgentService.out.log"
$ErrLog = Join-Path $InstallRoot "HarryAgentService.err.log"
$HadExistingInstall = (Test-Path $AgentExe) -or (Test-Path $ServiceExe) -or (Test-Path $ServiceXml) -or (Test-Path $ConfigPath)

Write-Host ""
Write-Host "Installing Harry Agent to $InstallRoot ..."
Write-Host "Installer source folder: $scriptDir"
Write-Host ("Existing install detected: {0}" -f ($(if ($HadExistingInstall) { "yes" } else { "no" })))
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

if (Test-Path ".\update_agent.ps1") {
    Copy-Item ".\update_agent.ps1" $UpdaterScript -Force
} else {
    Write-Host "ERROR: update_agent.ps1 not found in the package folder."
    Write-Host "Expected at: $scriptDir\update_agent.ps1"
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "Enter the Harry Brain address."
Write-Host "This is the full address of the machine running Harry Brain."
Write-Host "Examples:"
Write-Host "  192.168.1.100"
Write-Host "  192.168.1.100:8789"
Write-Host "  http://192.168.1.100:8789"
Write-Host ""

$brain = $null
if (-not [string]::IsNullOrWhiteSpace($env:HARRY_PUBLIC_BASE_URL)) {
    try {
        $brain = Normalize-BrainUrl $env:HARRY_PUBLIC_BASE_URL
        Write-Host "Using HARRY_PUBLIC_BASE_URL: $brain"
    } catch {
        Write-Host ""
        Write-Host "ERROR: HARRY_PUBLIC_BASE_URL is invalid." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
} else {
    $publicPort = Get-DefaultBrainPort
    $discovered = Discover-HarryBrain -Port $publicPort

    if ($discovered.Count -eq 1) {
        $brain = $discovered[0]
        Write-Host "Auto-discovered Harry Brain: $brain"
    } elseif ($discovered.Count -gt 1) {
        if (-not (Test-IsAdmin)) {
            Write-Host "Multiple Harry Brain instances were discovered, but the installer cannot prompt here." -ForegroundColor Yellow
        }

        Write-Host ""
        Write-Host "Multiple Harry Brain instances were discovered:"
        for ($i = 0; $i -lt $discovered.Count; $i++) {
            Write-Host ("  {0}) {1}" -f ($i + 1), $discovered[$i])
        }
        Write-Host "  m) Enter a Brain address manually"
        $choice = Read-Host "Choose a Brain [1]"
        if ([string]::IsNullOrWhiteSpace($choice)) {
            $choice = "1"
        }

        if ($choice -match '^\d+$' -and [int]$choice -ge 1 -and [int]$choice -le $discovered.Count) {
            $brain = $discovered[[int]$choice - 1]
        }
    }
}

if (-not $brain) {
    if (-not [Console]::IsInputRedirected) {
        Write-Host ""
        Write-Host "No Brain was auto-discovered."
        Write-Host "Enter the Brain address that other machines can reach."
        Write-Host "Examples:"
        Write-Host "  192.168.1.100"
        Write-Host "  192.168.1.100:8789"
        Write-Host "  http://192.168.1.100:8789"
        Write-Host ""
        $brainInput = Read-Host "Harry Brain address"

        if ([string]::IsNullOrWhiteSpace($brainInput)) {
            Write-Host "ERROR: No Brain address provided." -ForegroundColor Red
            Read-Host "Press Enter to exit"
            exit 1
        }

        try {
            $brain = Normalize-BrainUrl $brainInput
        } catch {
            Write-Host ""
            Write-Host "ERROR: Invalid Harry Brain address: $brainInput" -ForegroundColor Red
            Write-Host ""
            Read-Host "Press Enter to exit"
            exit 1
        }
    } else {
        Write-Host ""
        Write-Host "ERROR: Harry Brain could not be auto-discovered in non-interactive mode." -ForegroundColor Red
        Write-Host "Set the Brain address manually and rerun the installer." -ForegroundColor Yellow
        exit 1
    }
} else {
    try {
        $brain = Normalize-BrainUrl $brain
    } catch {
        Write-Host ""
        Write-Host "ERROR: Invalid discovered Harry Brain address: $brain" -ForegroundColor Red
        Write-Host ""
        Read-Host "Press Enter to exit"
        exit 1
    }
}

try {
    $verified = Test-BrainDiscoveryCandidate -BrainUrl $brain
    if (-not $verified) {
        throw "Harry Brain did not advertise discovery metadata at $brain"
    }
    $brain = $verified
} catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
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
$config | ConvertTo-Json | Set-Content -Encoding UTF8 $ConfigPath

Write-Host ""
Write-Host "Saved config to $ConfigPath"
Write-Host "Brain URL: $brain"

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
Write-Host "Upgraded existing install: $([bool]$HadExistingInstall)"
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
