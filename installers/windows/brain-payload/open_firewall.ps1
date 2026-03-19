param(
    [int]$Port = 8787
)

$ruleName = "Harry Brain TCP $Port"

try {
    $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-NetFirewallRule `
            -DisplayName $ruleName `
            -Direction Inbound `
            -Action Allow `
            -Protocol TCP `
            -LocalPort $Port `
            -Profile Private,Domain | Out-Null
    }
    exit 0
}
catch {
    Write-Error $_
    exit 1
}
