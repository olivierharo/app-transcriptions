@echo off
chcp 65001 >nul
title Transcription automatique - Enregistrements audio
cd /d "%~dp0"
echo Demarrage de la surveillance...
echo.
".venv\Scripts\python.exe" "src\surveiller.py"
echo.
echo La surveillance s'est arretee.
pause
