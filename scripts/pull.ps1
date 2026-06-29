#Requires -Version 5.1
<#
.SYNOPSIS
  Pull latest code from GitHub (Windows).
#>
param(
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "==> aliexpress-spider update"
Write-Host "Project: $Root"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "Git not found. Install from https://git-scm.com/download/win"
}

if (-not (Test-Path (Join-Path $Root ".git"))) {
    Write-Error @"
This folder is not a git repository.

First-time setup:
  cd C:\src
  git clone https://github.com/AriseshineSky/aliexpress-spider.git
  cd aliexpress-spider
  scripts\install.bat
"@
}

$branch = (& git rev-parse --abbrev-ref HEAD).Trim()
Write-Host "Branch: $branch"

Write-Host ""
Write-Host "==> git pull origin $branch"
& git pull origin $branch
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "If you see login/403 errors, run:" -ForegroundColor Yellow
    Write-Host "  gh auth login" -ForegroundColor Yellow
    Write-Host "  gh auth setup-git" -ForegroundColor Yellow
    Write-Host "Then run scripts\pull.bat again." -ForegroundColor Yellow
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Code updated."

if ($Install) {
    Write-Host ""
    Write-Host "==> Running install (dependencies may have changed)"
    & (Join-Path $Root "scripts\install.ps1")
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Next:"
Write-Host "  scripts\start.bat"
Write-Host "  scripts\pull.bat -Install    # also reinstall deps after pull"
Write-Host ""
