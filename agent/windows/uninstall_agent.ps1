$InstallRoot = "C:\ProgramData\Harry"
$ServiceExe = Join-Path $InstallRoot "HarryAgentService.exe"

if (Test-Path $ServiceExe) {
    Write-Host "Stopping Harry Agent service..."
    & $ServiceExe stop | Out-Null

    Write-Host "Uninstalling Harry Agent service..."
    & $ServiceExe uninstall | Out-Null
}

if (Test-Path $InstallRoot) {
    Remove-Item -Recurse -Force $InstallRoot
    Write-Host "Removed $InstallRoot"
} else {
    Write-Host "Nothing to remove."
}
