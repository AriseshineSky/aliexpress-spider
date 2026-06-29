#Requires -Version 5.1
<#
.SYNOPSIS
  Start aliexpress-spider crawl (after install.ps1).
#>
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CrawlArgs
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
$userDataDir = if ($env:USER_DATA_DIR) { $env:USER_DATA_DIR } else { Join-Path $env:USERPROFILE ".aliexpress-spider\browser" }

if (-not (Test-Path $venvPython)) {
    Write-Error @"
.venv not found.

Git clone only downloads source code. Run the installer first:
  scripts\install.bat
"@
}

$depCheck = & $venvPython -c "import em_product, playwright" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host $depCheck
    Write-Error @"

Missing Python dependencies (e.g. em_product).

Git pull does NOT install packages. Run:
  scripts\install.bat
  scripts\reinstall.bat   # clean .venv if install still fails

Then:
  scripts\start.bat
"@
}

$argsList = @(
    "-m", "aliexpress_spider", "crawl",
    "--user-data-dir", $userDataDir,
    "--output-dir", (Join-Path $Root "data")
) + $CrawlArgs

Write-Host "==> Starting aliexpress-spider crawl"
Write-Host "Python: $venvPython"
Write-Host "Profile: $userDataDir"
Write-Host ""

& $venvPython @argsList
exit $LASTEXITCODE
