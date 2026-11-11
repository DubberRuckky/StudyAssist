# StudyAssist Launcher Script
Set-Location -Path $PSScriptRoot

if (Test-Path ".venv\Scripts\python.exe") {
    Write-Host "🚀 [StudyAssist] Launching application via isolated virtual environment..." -ForegroundColor Green
    & ".\.venv\Scripts\python.exe" app.py
} else {
    Write-Host "⚠️ [StudyAssist] .venv not found. Attempting launch via system python..." -ForegroundColor Yellow
    python app.py
}
