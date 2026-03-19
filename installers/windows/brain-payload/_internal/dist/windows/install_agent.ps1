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
    # For Harry, default to 8787 unless the user explicitly entered a port.
    $explicitPort = $false
    if ($InputUrl -match ":\d+(/|$)") {
        $explicitPort = $true
    }

    if (-not $explicitPort) {
        $port = 8787
    }

    return "${scheme}://${brainHost}:${port}"
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
        $port = 8787
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
    Write-Host "This is the full address of the machine running Harry Brain."
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
        Test-BrainReachability -BrainUrl $brain
    } catch {
        Write-Host ""
        Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host ""
        Read-Host "Press Enter to exit"
        exit 1
    }

    @{ brain_url = $brain } |
        ConvertTo-Json |
        Set-Content -Encoding UTF8 $ConfigPath

    Write-Host ""
    Write-Host "Saved config to $ConfigPath"
    Write-Host "Brain URL: $brain"
} else {
    Write-Host ""
    Write-Host "Existing config found at $ConfigPath"
    try {
        $existingConfig = Get-Content $ConfigPath -Raw | ConvertFrom-Json
        if ($existingConfig.brain_url) {
            Write-Host "Brain URL: $($existingConfig.brain_url)"
        }
    } catch {
        Write-Host "Could not read existing config."
    }
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
