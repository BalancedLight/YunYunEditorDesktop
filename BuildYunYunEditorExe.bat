@echo off
setlocal

if /I "%~1"=="--help" goto :usage
if /I "%~1"=="-h" goto :usage

set "REPO_ROOT=%~dp0"
set "PROJECT_DIR=%REPO_ROOT%python_editor"
set "SPEC_FILE=%PROJECT_DIR%\yunyun_editor.spec"
set "VENV_PY=%PROJECT_DIR%\.venv\Scripts\python.exe"
set "DIST_DIR=%REPO_ROOT%dist"
set "WORK_DIR=%REPO_ROOT%build\pyinstaller"

if not exist "%PROJECT_DIR%" (
  echo Could not find python_editor next to this script.
  exit /b 1
)

if not exist "%SPEC_FILE%" (
  echo Could not find %SPEC_FILE%.
  exit /b 1
)

cd /d "%PROJECT_DIR%"
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONFAULTHANDLER=1"

if exist "%VENV_PY%" goto :install_deps

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
exit /b 1

:venv_created
if not exist "%VENV_PY%" (
  echo Failed to create python_editor\.venv.
  exit /b 1
)

:install_deps
echo Installing build dependencies into python_editor\.venv...
"%VENV_PY%" -m pip install --upgrade pip
if %ERRORLEVEL% NEQ 0 exit /b 1

"%VENV_PY%" -m pip install -e . pyinstaller
if %ERRORLEVEL% NEQ 0 exit /b 1

echo Building YunYunEditor.exe...
"%VENV_PY%" -m PyInstaller --noconfirm --clean --distpath "%DIST_DIR%" --workpath "%WORK_DIR%" "%SPEC_FILE%"
if %ERRORLEVEL% NEQ 0 exit /b 1

echo.
echo Build complete:
echo   %DIST_DIR%\YunYunEditor\YunYunEditor.exe
echo Keep the whole dist\YunYunEditor folder together when you move it.
exit /b 0

:usage
echo Usage: BuildYunYunEditorExe.bat
echo.
echo Builds a PyInstaller onedir package at dist\YunYunEditor\YunYunEditor.exe.
exit /b 0