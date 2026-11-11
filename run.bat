@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    echo [StudyAssist] Launching application via isolated virtual environment...
    ".venv\Scripts\python.exe" app.py
) else (
    echo [StudyAssist] Warning: .venv not found. Attempting launch via system python...
    python app.py
)
if errorlevel 1 (
    echo.
    echo An error occurred while running StudyAssist.
    pause
)
