@echo off
setlocal

cd /d "%~dp0python_editor"
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONFAULTHANDLER=1"

if exist ".venv\Scripts\python.exe" (
  goto :check_requirements
)

echo Creating local Python environment in python_editor\.venv...
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 -m venv .venv
  goto :venv_created
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  python -m venv .venv
  goto :venv_created
)

echo Python was not found. Install Python 3.10+ and run this file again.
goto :done

:venv_created
if not exist ".venv\Scripts\python.exe" (
  echo Failed to create python_editor\.venv.
  goto :done
)

:check_requirements
".venv\Scripts\python.exe" -c "import numpy, sounddevice, soundfile, pydub" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
  goto :install_requirements
)

:run_editor
".venv\Scripts\python.exe" -m yunyun_editor
goto :done

:install_requirements
echo Installing requirements...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if %ERRORLEVEL% EQU 0 (
  ".venv\Scripts\python.exe" -m pip install -e .
)
if %ERRORLEVEL% NEQ 0 (
  echo.
  echo Requirement installation failed.
  echo You can try manually:
  echo   cd python_editor
  echo   .venv\Scripts\python.exe -m pip install -e .
  goto :done
)
goto :run_editor

:done
if errorlevel 1 pause
