@echo off
setlocal EnableExtensions
title LEDPET V1.0 (by THEGEM)
cd /d "%~dp0"
chcp 65001 >nul

rem ---------- find a working Python ----------
set "PY="
py -3 -c "print(1)" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "print(1)" >nul 2>&1 && set "PY=python"
if not defined PY python3 -c "print(1)" >nul 2>&1 && set "PY=python3"

if not defined PY (
  echo.
  echo   ================================================
  echo    [LEDPET V1.0] Python was not found!
  echo.
  echo    Please install Python from:
  echo        https://www.python.org/downloads/
  echo.
  echo    During setup, make sure to tick:
  echo        "Add python.exe to PATH"
  echo.
  echo    After installing, run this file again.
  echo   ================================================
  pause
  exit /b 1
)

rem ---------- everything else is handled by launcher.py ----------
%PY% "%~dp0launcher.py"
if errorlevel 1 (
  echo.
  echo   [LEDPET V1.0] Launcher failed - see launcher_log.txt
  pause
)
exit /b 0
