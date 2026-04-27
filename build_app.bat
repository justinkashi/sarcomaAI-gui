@echo off
REM build_app.bat — Build SarcomaAI.exe (Windows)
REM
REM Usage:
REM   cd sarcomaAI-gui
REM   build_app.bat
REM
REM Requires: dist_venv\ (set up with all deps + pyinstaller)
REM           Node.js / npm on PATH

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

set VENV=%SCRIPT_DIR%dist_venv

echo =^> Step 1: Generate Windows icon (sarcomaai.ico)
"%VENV%\Scripts\python.exe" generate_ico.py
if errorlevel 1 (
    echo ERROR: Icon generation failed.
    exit /b 1
)

echo.
echo =^> Step 2: Build React frontend
cd frontend
call npm run build
if errorlevel 1 (
    echo ERROR: npm run build failed.
    exit /b 1
)
cd ..
echo     React build complete -- frontend/build/

echo.
echo =^> Step 3: Run PyInstaller (using dist_venv)
"%VENV%\Scripts\pyinstaller.exe" sarcomaai.spec --noconfirm --clean
if errorlevel 1 (
    echo ERROR: PyInstaller failed.
    exit /b 1
)

echo.
echo =^> Done.
echo     Executable: dist\SarcomaAI\SarcomaAI.exe
echo     Distribute the entire dist\SarcomaAI\ folder (or zip it).
