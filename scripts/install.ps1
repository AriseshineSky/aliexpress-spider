#Requires -Version 5.1
<#
.SYNOPSIS
  Install aliexpress-spider on Windows (no Git required).
#>
param(
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "==> aliexpress-spider installer (Windows)"
Write-Host "Project: $Root"
Write-Host "Note: em_product is bundled in this repo (no external product-validator install)."

function Get-PythonCommand {
    param([string]$Preferred)
    $candidates = @()
    if ($Preferred) { $candidates += ,@($Preferred) }
    $candidates += ,@("py", "-3.12")
    $candidates += ,@("py", "-3.11")
    $candidates += ,@("py", "-3.10")
    $candidates += ,@("py", "-3")
    $candidates += ,@("python")
    $candidates += ,@("python3")

    foreach ($cmd in $candidates) {
        try {
            $versionText = & $cmd[0] @($cmd[1..($cmd.Length - 1)]) -c "import sys; print(sys.version_info[:2])" 2>$null
            if (-not $versionText) { continue }
            if ($versionText -match "\(3,\s*(\d+)\)") {
                $minor = [int]$Matches[1]
                if ($minor -ge 10) {
                    return ,$cmd
                }
            }
        } catch {
            continue
        }
    }
    return $null
}

$pythonCmd = Get-PythonCommand -Preferred $PythonExe
if (-not $pythonCmd) {
    Write-Error "Python 3.10+ not found. Install from https://www.python.org/downloads/ and enable 'Add Python to PATH'."
}

$display = & $pythonCmd[0] @($pythonCmd[1..($pythonCmd.Length - 1)]) -c "import sys; print(sys.version.split()[0], sys.executable)"
Write-Host "Python: $display"

if (-not (Test-Path ".venv")) {
    Write-Host "[1/5] Creating virtual environment .venv"
    & $pythonCmd[0] @($pythonCmd[1..($pythonCmd.Length - 1)]) -m venv .venv
}

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual environment creation failed: $venvPython not found"
}

Write-Host "[2/5] Upgrading pip"
& $venvPython -m pip install --upgrade pip

Write-Host "[3/5] Installing aliexpress-spider and dependencies"
& $venvPython -m pip install -e .
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install packages. Ensure github.com is reachable."
}

Write-Host "[4/5] Installing Playwright Chromium"
& $venvPython -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to install Playwright Chromium."
}

Write-Host "[5/5] Verifying install"
& $venvPython -c "import em_product; import aliexpress_spider; print('em_product OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Install verification failed: em_product not importable."
}

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "==> Created .env from .env.example (edit before crawling)"
}

Write-Host ""
Write-Host "Installation complete."
Write-Host ""
Write-Host "Next steps:"
Write-Host "  .\scripts\verify.bat"
Write-Host "  .\scripts\start.bat"
Write-Host "  .\scripts\pull.bat           # update code from GitHub"
Write-Host ""
