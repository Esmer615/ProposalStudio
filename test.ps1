# 本地验收：引擎测试 + 前端类型检查/构建
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root ".venv\Scripts\python.exe"
Set-Location $root

Write-Host "== pytest ==" -ForegroundColor Cyan
if (Test-Path $py) {
    if (Test-Path "engine\tests") { & $py -m pytest engine/tests -q }
    if (Test-Path "server\tests") { & $py -m pytest server/tests -q }
    if (Test-Path "agent\tests") { & $py -m pytest agent/tests -q }
} else {
    Write-Host "缺少 .venv，跳过 Python 测试" -ForegroundColor Yellow
}

Write-Host "== frontend build ==" -ForegroundColor Cyan
if (Test-Path "web\package.json") {
    pnpm --dir web build
} else {
    Write-Host "缺少 web/package.json，跳过前端构建" -ForegroundColor Yellow
}

Write-Host "== API smoke (if server running) ==" -ForegroundColor Cyan
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:8010/api/health" -TimeoutSec 3
    $h | ConvertTo-Json -Depth 5
} catch {
    Write-Host "API 未启动，跳过 smoke（可运行 .\start-dev.ps1）" -ForegroundColor Yellow
}
