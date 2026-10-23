# Start the local llama.cpp inference server (OpenAI compatible + raw /completion)
# NOTE: keep this file pure ASCII. Windows PowerShell 5.1 reads .ps1 as ANSI
# unless it has a BOM, which corrupts non-ASCII literals and breaks parsing.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File serve.ps1
#   powershell -ExecutionPolicy Bypass -File serve.ps1 -Port 8081 -Ctx 4096
#   powershell -ExecutionPolicy Bypass -File serve.ps1 -Model "E:\Ai\models\other.gguf"
param(
    [string]$Model = 'E:\Ai\models\mt-1.8b-Q8_0.gguf',
    [int]$Port = 8080,
    [int]$Ctx = 8192,
    [int]$GpuLayers = 99,
    [string]$HostAddr = '127.0.0.1'
)

$ErrorActionPreference = 'Stop'
$exe = 'E:\Ai\llama.cpp\llama-server.exe'

if (-not (Test-Path -LiteralPath $exe)) { Write-Host "[ERROR] missing $exe" -ForegroundColor Red; exit 1 }
if (-not (Test-Path -LiteralPath $Model)) { Write-Host "[ERROR] missing $Model" -ForegroundColor Red; exit 1 }

Write-Host "model : $Model" -ForegroundColor Cyan
Write-Host "listen: http://${HostAddr}:$Port  (ctx=$Ctx, ngl=$GpuLayers)" -ForegroundColor Cyan
Write-Host "stop  : Ctrl+C" -ForegroundColor DarkGray

& $exe -m $Model -ngl $GpuLayers -c $Ctx --host $HostAddr --port $Port -np 1 --log-colors off
