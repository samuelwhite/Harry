$xmlPath = Join-Path $PSScriptRoot "HarryBrainService.xml"

try {
    $ip = Get-CimInstance Win32_NetworkAdapterConfiguration |
        Where-Object { $_.IPEnabled -eq $true -and $_.IPAddress -ne $null } |
        ForEach-Object { $_.IPAddress } |
        Where-Object {
            $_ -match '^\d+\.\d+\.\d+\.\d+$' -and
            $_ -notlike '127.*' -and
            $_ -notlike '169.254.*'
        } |
        Select-Object -First 1

    if (-not $ip) {
        Write-Output "NO_IP_FOUND"
        exit 0
    }

    $content = Get-Content $xmlPath -Raw
    $content = $content -replace '__HARRY_PUBLIC_BASE_URL__', ("http://{0}:8787" -f $ip)
    Set-Content -Path $xmlPath -Value $content -Encoding UTF8

    Write-Output ("SET_PUBLIC_URL=http://{0}:8787" -f $ip)
    exit 0
}
catch {
    Write-Output ("ERROR=" + $_.Exception.Message)
    exit 0
}