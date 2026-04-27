# Signs winvision-mcp.exe and installs it to Program Files for UIAccess.
# UIAccess requires:
#   1. The PE is signed by a cert in LocalMachine\TrustedPublisher.
#   2. The PE lives under %ProgramFiles% (or System32).
#
# This script:
#   1. Builds a one-file pyinstaller binary of winvision-mcp.
#   2. Generates (or reuses) a self-signed code-signing cert.
#   3. Adds the cert to TrustedPublisher (LocalMachine).
#   4. Embeds manifest/winvision.manifest (uiAccess=true).
#   5. Signs the binary.
#   6. Copies to "C:\Program Files\WinVision\winvision-mcp.exe".
#
# UIAccess is OPTIONAL. Skip this script if you do not need to drive elevated
# windows (the server still works on normal apps without it).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File sign_and_install.ps1

[CmdletBinding()]
param(
    [string]$CertSubject  = "CN=WinVision MCP Self-Signed",
    [string]$InstallDir   = "C:\Program Files\WinVision",
    [string]$ManifestPath = (Resolve-Path "$PSScriptRoot\..\manifest\winvision.manifest").Path
)

$ErrorActionPreference = "Stop"

function Require-Admin {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "This script must be run from an elevated PowerShell prompt."
    }
}

Require-Admin

# 1. Build pyinstaller binary
Write-Host "[1/6] Building one-file binary..." -ForegroundColor Cyan
$repoRoot = Resolve-Path "$PSScriptRoot\.."
Push-Location $repoRoot
try {
    python -m pip install --quiet pyinstaller
    python -m PyInstaller `
        --onefile `
        --name winvision-mcp `
        --console `
        --manifest $ManifestPath `
        --collect-submodules winvision_mcp `
        src\winvision_mcp\__main__.py
} finally {
    Pop-Location
}

$exePath = Join-Path $repoRoot "dist\winvision-mcp.exe"
if (-not (Test-Path $exePath)) { throw "Build did not produce $exePath" }

# 2. Get-or-create cert
Write-Host "[2/6] Locating code-signing cert ($CertSubject)..." -ForegroundColor Cyan
$cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq $CertSubject } | Select-Object -First 1
if (-not $cert) {
    Write-Host "  -> creating new self-signed cert" -ForegroundColor Yellow
    $cert = New-SelfSignedCertificate `
        -Subject $CertSubject `
        -Type CodeSigningCert `
        -KeyUsage DigitalSignature `
        -KeyAlgorithm RSA `
        -KeyLength 2048 `
        -NotAfter (Get-Date).AddYears(5) `
        -CertStoreLocation "Cert:\CurrentUser\My"
}

# 3. Trust the cert
Write-Host "[3/6] Adding cert to LocalMachine\TrustedPublisher..." -ForegroundColor Cyan
$store = Get-Item "Cert:\LocalMachine\TrustedPublisher"
$store.Open("ReadWrite")
$store.Add($cert)
$store.Close()

# 4. Embed manifest (already done by --manifest above; verify)
Write-Host "[4/6] Verifying embedded manifest..." -ForegroundColor Cyan
$mt = Get-Command "mt.exe" -ErrorAction SilentlyContinue
if ($mt) {
    & $mt.Source -inputresource:"$exePath;#1" -out:"$env:TEMP\embedded.manifest" | Out-Null
    if (-not (Get-Content "$env:TEMP\embedded.manifest" -Raw).Contains('uiAccess="true"')) {
        Write-Warning "Embedded manifest does not contain uiAccess=true. Re-embedding..."
        & $mt.Source -manifest $ManifestPath -outputresource:"$exePath;#1"
    }
} else {
    Write-Warning "mt.exe not found; skipping manifest verification."
}

# 5. Sign the binary
Write-Host "[5/6] Signing binary..." -ForegroundColor Cyan
$signResult = Set-AuthenticodeSignature -FilePath $exePath -Certificate $cert -TimestampServer "http://timestamp.digicert.com"
if ($signResult.Status -ne "Valid") {
    throw "Signing failed: $($signResult.StatusMessage)"
}

# 6. Install to Program Files
Write-Host "[6/6] Installing to $InstallDir..." -ForegroundColor Cyan
if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir | Out-Null }
Copy-Item $exePath (Join-Path $InstallDir "winvision-mcp.exe") -Force

Write-Host ""
Write-Host "Done. UIAccess-enabled binary installed at:" -ForegroundColor Green
Write-Host "  $InstallDir\winvision-mcp.exe" -ForegroundColor Green
Write-Host ""
Write-Host "To use this binary as your MCP server, point your client at the full path." -ForegroundColor Yellow
Write-Host "Without UIAccess (i.e. running via 'winvision-mcp' from PATH), elevated windows" -ForegroundColor Yellow
Write-Host "will refuse to focus and SetForegroundWindow may silently fail." -ForegroundColor Yellow
