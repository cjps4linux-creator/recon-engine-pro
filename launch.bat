@echo off
title Recon Engine Pro
echo Starting Recon Engine Pro...
setlocal
cd /d "%~dp0"

rem Prefer a project-local virtualenv, then an environment override,
rem then a system Python on PATH.
set "PYTHON="
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not defined PYTHON if defined HERMES_PYTHON set "PYTHON=%HERMES_PYTHON%"
if not defined PYTHON for %%P in (python.exe python) do if not defined PYTHON set "PYTHON=%%~$PATH:P"

if not defined PYTHON (
  echo [launcher] No Python interpreter found.
  echo [launcher] Create a virtualenv at "%~dp0.venv" or set HERMES_PYTHON.
  pause
  exit /b 1
)

"%PYTHON%" "%~dp0launcher.py"
endlocal
