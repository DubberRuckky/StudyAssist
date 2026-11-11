# StudyAssist Launcher Script
Set-Location -Path $PSScriptRoot

$venvDir = ".venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"
$hashFile = Join-Path $venvDir "requirements.txt.hash"

# 1. Check if virtual environment exists; if not, create it
if (-not (Test-Path $venvPy)) {
    Write-Host "[StudyAssist] Virtual environment not found. Creating .venv..." -ForegroundColor Cyan
    $created = $false
    try {
        & py -3.13 -m venv $venvDir 2>$null
        if (Test-Path $venvPy) { $created = $true }
    } catch {}

    if (-not $created) {
        try {
            & py -3.12 -m venv $venvDir 2>$null
            if (Test-Path $venvPy) { $created = $true }
        } catch {}
    }

    if (-not $created) {
        Write-Host "[StudyAssist] 'py -3.13' failed or not available. Falling back to system python..." -ForegroundColor Yellow
        try {
            & python -m venv $venvDir
            if (Test-Path $venvPy) { $created = $true }
        } catch {}
    }

    if (-not (Test-Path $venvPy)) {
        Write-Host "[StudyAssist] Error: Failed to create virtual environment in $venvDir." -ForegroundColor Red
        Write-Host "`nAn error occurred while running StudyAssist." -ForegroundColor Red
        Pause
        exit 1
    }
    Write-Host "[StudyAssist] Virtual environment created successfully." -ForegroundColor Green
}

# 2. Calculate SHA256 checksum of requirements.txt
$currentHash = $null
try {
    $currentHash = (Get-FileHash requirements.txt -Algorithm SHA256).Hash.ToLower()
} catch {}

if (-not $currentHash) {
    Write-Host "[StudyAssist] Error: Unable to compute checksum for requirements.txt." -ForegroundColor Red
    Write-Host "`nAn error occurred while running StudyAssist." -ForegroundColor Red
    Pause
    exit 1
}

# 3. Read stored hash if available
$storedHash = ""
if (Test-Path $hashFile) {
    $storedHash = (Get-Content $hashFile -Raw).Trim()
}

# 4. Compare hashes; install dependencies only if changed or missing
if ($currentHash -ne $storedHash) {
    Write-Host "[StudyAssist] Dependencies are missing or requirements.txt has changed." -ForegroundColor Cyan
    Write-Host "[StudyAssist] Installing dependencies into .venv..." -ForegroundColor Cyan
    & $venvPy -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[StudyAssist] Error: Failed to install requirements into virtual environment." -ForegroundColor Red
        Write-Host "[StudyAssist] Note: If using Python 3.14+, binary wheels for chromadb/onnxruntime" -ForegroundColor Yellow
        Write-Host "[StudyAssist] may not be available on PyPI yet. Please install Python 3.13." -ForegroundColor Yellow
        Write-Host "`nAn error occurred while running StudyAssist." -ForegroundColor Red
        Pause
        exit 1
    }
    Set-Content -Path $hashFile -Value $currentHash -NoNewline
    Write-Host "[StudyAssist] Dependencies verified successfully." -ForegroundColor Green
}

# 5. Launch the application via the virtual environment
Write-Host "🚀 [StudyAssist] Launching application via isolated virtual environment..." -ForegroundColor Green
& $venvPy app.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nAn error occurred while running StudyAssist." -ForegroundColor Red
    Pause
    exit $LASTEXITCODE
}
