@echo off
chcp 65001 >nul
title Transcriptions
cd /d "%~dp0src"
"..\.venv-whisperx\Scripts\python.exe" -m app
if errorlevel 1 (
  echo.
  echo L'application s'est arretee sur une erreur.
  pause
)
