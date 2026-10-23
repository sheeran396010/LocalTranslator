# Dev launcher: run the app from source on Windows.
# Keep this file pure ASCII: Windows PowerShell 5.1 reads .ps1 as ANSI unless
# it has a BOM, which would corrupt non-ASCII literals and break parsing.
#
# Usage:
#   .\run.cmd                                   (double-click friendly)
#   powershell -ExecutionPolicy Bypass -File .\run.ps1
#
# Uses .venv\Scripts\python.exe when present, otherwise `python` from PATH.
# models\ and runtime\ must be prepared next to the project root.

$root   = Split-Path $PSScriptRoot -Parent
$venvPy = Join-Path $root '.venv\Scripts\python.exe'
$py     = if (Test-Path $venvPy) { $venvPy } else { 'python' }
$app    = Join-Path $PSScriptRoot 'main.py'

if (-not (Test-Path -LiteralPath $app)) {
    Write-Host "[ERROR] main.py not found next to this script." -ForegroundColor Red
    exit 1
}

Write-Host "python : $py"
Write-Host "app    : $app"
Write-Host "hint   : Alt+Q capture | Alt+R live | Alt+P pause | Alt+W stop" -ForegroundColor DarkGray

& $py $app @args
exit $LASTEXITCODE
