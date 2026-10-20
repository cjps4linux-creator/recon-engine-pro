@echo off
title Recon Engine Pro
echo Starting Recon Engine Pro...
cd /d "%~dp0"

set PYTHON=C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe
"%PYTHON%" "%~dp0launcher.py"
