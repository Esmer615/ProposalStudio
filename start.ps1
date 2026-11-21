# 乐园 AI 提案工作台 — 本地一键启动（生产模式）
# 用法：双击或在 PowerShell 中执行 .\start.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
$dist = Join-Path $root "web\dist\index.html"

if (-not (Test-Path $py)) {
    Write-Host "[start] 未找到 .venv，请先运行安装步骤（README）：" -ForegroundColor Yellow
    Write-Host "  uv venv .venv --python <python.exe>" -ForegroundColor Yellow
    Write-Host "  uv pip install --python .venv\Scripts\python.exe -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $dist)) {
    Write-Host "[start] 未找到 web/dist/index.html；先构建前端：" -ForegroundColor Yellow
    Write-Host "  pnpm --dir web install" -ForegroundColor Yellow
    Write-Host "  pnpm --dir web build" -ForegroundColor Yellow
    Write-Host "  然后重新运行 .\start.ps1" -ForegroundColor Yellow
    exit 1
}

Write-Host "[start] 启动本地 API + 静态站点 http://127.0.0.1:8010" -ForegroundColor Cyan
$api = Start-Process -FilePath $py -ArgumentList @("-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", "8010") -WorkingDirectory $root -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:8010"
Write-Host "[start] 按 Ctrl+C 结束服务" -ForegroundColor Cyan
try {
    Wait-Process -Id $api.Id
} finally {
    if (-not $api.HasExited) { Stop-Process -Id $api.Id -Force }
}
