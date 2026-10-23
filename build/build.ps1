# Build the distributable folder (PyInstaller onedir) for the local translator.
# Pure ASCII on purpose: Windows PowerShell 5.1 parses .ps1 as ANSI.
#
#   powershell -ExecutionPolicy Bypass -File build.ps1
#
# Output:
#   E:\Sheeran\dist\LocalTranslator\
#     LocalTranslator.exe
#     _internal\            (python runtime + PySide6 + onnxruntime + OCR models)
#     runtime\              (llama-server.exe + CUDA DLLs)
#     models\               (the .gguf translation model, swappable)
param(
    [switch]$SkipRuntime,
    [switch]$SkipModel
)

$ErrorActionPreference = 'Stop'

$py    = 'E:\Ai\venv312\Scripts\python.exe'
$app   = 'E:\Sheeran\app'
$dist  = 'E:\Sheeran\dist'
$work  = 'E:\Sheeran\build\pyi'
$name  = 'LocalTranslator'
$sp    = 'E:\Ai\venv312\Lib\site-packages'
$icon  = 'E:\Sheeran\build\app.ico'
$model = 'E:\Ai\models\mt-1.8b-bf16-Q5_K_M.gguf'
$llama = 'E:\Ai\llama.cpp'


# --- 前置检查：正在运行的程序会锁住 dist，导致 PermissionError ---
$running = Get-Process LocalTranslator -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "[ERROR] LocalTranslator.exe is running (pid: $($running.Id -join ',')). Close it first." -ForegroundColor Red
    exit 1
}
Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "=== 1/3 PyInstaller bundle ===" -ForegroundColor Cyan

$pyargs = @(
    '-m', 'PyInstaller',
    '--noconfirm', '--clean',
    '--windowed',
    '--name', $name,
    '--distpath', $dist,
    '--workpath', $work,
    '--specpath', $work,
    '--hidden-import', 'rapidocr',
    '--collect-all', 'qfluentwidgets',
    '--collect-all', 'qframelesswindow',
    '--hidden-import', 'win32gui',
    '--hidden-import', 'win32api',
    '--hidden-import', 'win32con',
    '--hidden-import', 'win32print',
    '--collect-binaries', 'pywin32',
    '--collect-data', 'rapidocr',
    '--add-data', "$sp\rapidocr\models;rapidocr\models",
    '--add-data', "$sp\rapidocr\config.yaml;rapidocr",
    '--add-data', "$sp\rapidocr\default_models.yaml;rapidocr",
    '--add-data', "$sp\rapidocr\inference_engine\pytorch\networks\arch_config.yaml;rapidocr\inference_engine\pytorch\networks",
    '--collect-binaries', 'onnxruntime',
    '--collect-data', 'onnxruntime',
    '--exclude-module', 'PySide6.QtWebEngineCore',
    '--exclude-module', 'PySide6.QtWebEngineWidgets',
    '--exclude-module', 'PySide6.QtWebEngineQuick',
    '--exclude-module', 'PySide6.QtQuick',
    '--exclude-module', 'PySide6.QtQml',
    '--exclude-module', 'PySide6.QtQuickWidgets',
    '--exclude-module', 'PySide6.Qt3DCore',
    '--exclude-module', 'PySide6.Qt3DRender',
    '--exclude-module', 'PySide6.QtMultimedia',
    '--exclude-module', 'PySide6.QtMultimediaWidgets',
    '--exclude-module', 'PySide6.QtCharts',
    '--exclude-module', 'PySide6.QtDataVisualization',
    '--exclude-module', 'torch',
    '--exclude-module', 'transformers',
    '--exclude-module', 'tokenizers',
    '--exclude-module', 'scipy',
    '--exclude-module', 'pandas',
    '--exclude-module', 'matplotlib',
    '--exclude-module', 'IPython',
    '--exclude-module', 'pytest'
)
if (Test-Path $icon) { $pyargs += @('--icon', $icon) }
$verfile = Join-Path $PSScriptRoot 'version_info.txt'
if (Test-Path $verfile) { $pyargs += @('--version-file', $verfile) }
$pyargs += @("$app\main.py")

Write-Host "running: pyinstaller $($pyargs.Count) args"
& $py @pyargs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with code $LASTEXITCODE" }

$out = Join-Path $dist $name
if (-not (Test-Path (Join-Path $out "$name.exe"))) { throw "exe not found in $out" }

Write-Host "=== 2/3 runtime (llama-server + CUDA dll) ===" -ForegroundColor Cyan
if (-not $SkipRuntime) {
    $rt = Join-Path $out 'runtime'
    New-Item -ItemType Directory -Force $rt | Out-Null
    Copy-Item (Join-Path $llama '*') $rt -Recurse -Force
}

Write-Host "=== 3/3 model ===" -ForegroundColor Cyan
if (-not $SkipModel) {
    $md = Join-Path $out 'models'
    New-Item -ItemType Directory -Force $md | Out-Null
    Copy-Item $model $md -Force
}

Get-ChildItem 'E:\Sheeran\build\*.txt' | Copy-Item -Destination $out -Force

$size = (Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ''
Write-Host "dist: $out" -ForegroundColor Green
Write-Host ("size: {0:N0} MB" -f $size) -ForegroundColor Green
Write-Host "verify: $out\$name.exe --selftest" -ForegroundColor Green


