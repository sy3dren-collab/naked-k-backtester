@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  set "BACKTEST_PYTHON=python"
) else (
  set "BACKTEST_PYTHON=py -3"
)
%BACKTEST_PYTHON% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo Please install Python 3.11 or newer from python.org.
  pause
  exit /b 1
)
%BACKTEST_PYTHON% tools\launch.py
if errorlevel 1 pause
