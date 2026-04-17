Write-Host "🔄 Syncing environment..." -ForegroundColor Cyan
uv sync

# 2. Check if sync was successful
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Sync failed. Check your pyproject.toml" -ForegroundColor Red
    pause
    exit
}

# 3. Run the project using the 'start' alias
Write-Host "🚀 Starting OCR Application..." -ForegroundColor Green
uv run python Main.py

# Keep window open if it crashes or finishes
pause