# 开发模式：FastAPI(8000) + Vite(5173)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) { Write-Host "[dev] 缺少 .venv，请先按 README 安装" -ForegroundColor Red; exit 1 }

Write-Host "[dev] API http://127.0.0.1:8010" -ForegroundColor Cyan
$api = Start-Process -FilePath $py -ArgumentList @("-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", "8010", "--reload") -WorkingDirectory $root -PassThru
Start-Sleep -Seconds 2
Write-Host "[dev] Web http://127.0.0.1:5173" -ForegroundColor Cyan
Start-Process "http://127.0.0.1:5173"
try {
    pnpm --dir web dev --host 127.0.0.1 --port 5173
} finally {
    if (-not $api.HasExited) { Stop-Process -Id $api.Id -Force }
}
