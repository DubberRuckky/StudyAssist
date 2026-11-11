@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "HASH_FILE=%VENV_DIR%\requirements.txt.hash"

:: 1. Check if virtual environment exists; if not, create it
if not exist "%VENV_PY%" (
    echo [StudyAssist] Virtual environment not found. Creating .venv...
    py -3.13 -m venv "%VENV_DIR%" 2>nul
    if not exist "%VENV_PY%" (
        py -3.12 -m venv "%VENV_DIR%" 2>nul
    )
    if not exist "%VENV_PY%" (
        echo [StudyAssist] 'py -3.13' failed or not available. Falling back to system python...
        python -m venv "%VENV_DIR%"
    )
    if not exist "%VENV_PY%" (
        echo [StudyAssist] Error: Failed to create virtual environment in %VENV_DIR%.
        goto :error
    )
    echo [StudyAssist] Virtual environment created successfully.
)

:: 2. Calculate SHA256 checksum of requirements.txt
set "CURRENT_HASH="
for /f "skip=1 tokens=*" %%A in ('certutil -hashfile requirements.txt SHA256 2^>nul') do (
    if not defined CURRENT_HASH set "CURRENT_HASH=%%A"
)

if not defined CURRENT_HASH (
    echo [StudyAssist] Error: Unable to compute checksum for requirements.txt.
    goto :error
)

:: 3. Read stored hash if available
set "STORED_HASH="
if exist "%HASH_FILE%" (
    set /p STORED_HASH=<"%HASH_FILE%"
)

:: 4. Compare hashes; install dependencies only if changed or missing
if not "!CURRENT_HASH!"=="!STORED_HASH!" (
    echo [StudyAssist] Dependencies are missing or requirements.txt has changed.
    echo [StudyAssist] Installing dependencies into .venv...
    "%VENV_PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [StudyAssist] Error: Failed to install requirements into virtual environment.
        echo [StudyAssist] Note: If using Python 3.14+, binary wheels for chromadb/onnxruntime
        echo [StudyAssist] may not be available on PyPI yet. Please install Python 3.13.
        goto :error
    )
    echo !CURRENT_HASH!>"%HASH_FILE%"
    echo [StudyAssist] Dependencies verified successfully.
)

:: 5. Launch the application via the virtual environment
echo [StudyAssist] Launching application via isolated virtual environment...
"%VENV_PY%" app.py
if errorlevel 1 goto :error
goto :eof

:error
echo.
echo An error occurred while running StudyAssist.
pause
exit /b 1
