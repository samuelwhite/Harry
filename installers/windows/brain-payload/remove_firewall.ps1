param(
    [int]$Port = 8787
)

$ruleName = "Harry Brain TCP $Port"

try {
    Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue | Out-Null
    exit 0
}
catch {
    exit 0
}
