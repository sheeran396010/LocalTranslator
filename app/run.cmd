@echo off
rem Dev launcher: runs the app from source on Windows.
rem Requires Python 3.12 with requirements.txt installed,
rem plus models\ and runtime\ prepared next to the project root.
setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

"%PY%" app\main.py %*
if errorlevel 1 pause
endlocal
