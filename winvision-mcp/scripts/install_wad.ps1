# Installs WinAppDriver (optional fallback for UIA on legacy WinForms apps).
# WinVision uses UIA + WGC directly and does NOT require WinAppDriver, but it can be
# helpful when targeting older WPF/WinForms apps that expose better automation via WAD.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File install_wad.ps1

[CmdletBinding()]
param(
    [string]$Version = "1.2.1",
    [string]$DownloadUrl = "https://github.com/microsoft/WinAppDriver/releases/download/v1.2.1/WindowsApplicationDriver-1.2.1-win-x64.exe"
)

$ErrorActionPreference = "Stop"

$installer = Join-Path $env:TEMP "WinAppDriver-$Version.exe"
Write-Host "Downloading WinAppDriver $Version..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $DownloadUrl -OutFile $installer -UseBasicParsing

Write-Host "Running installer (silent)..." -ForegroundColor Cyan
Start-Process -FilePath $installer -ArgumentList "/quiet" -Wait

$wadPath = "C:\Program Files\Windows Application Driver\WinAppDriver.exe"
if (Test-Path $wadPath) {
    Write-Host "WinAppDriver installed at: $wadPath" -ForegroundColor Green
    Write-Host "Start it with:  & '$wadPath'  (listens on http://127.0.0.1:4723)" -ForegroundColor Yellow
} else {
    Write-Warning "WinAppDriver was not found at expected path. Installer may have failed."
    exit 1
}
