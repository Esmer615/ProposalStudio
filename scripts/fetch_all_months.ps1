# fetch_all_months.ps1
# 串行抓取红豆库存快照：公交 + 地铁，5 个月份（2027-06/07/08/09/10）。
# 依赖 scripts/fetch_hongdou.py（走 OAuth2 自动登录 + 401 自动重登）。
# 单月失败不阻塞其他月；退出码为失败月份数（0=全部成功）。
#
# 用法：
#   $env:PYTHONIOENCODING = "utf-8"
#   powershell -File scripts/fetch_all_months.ps1

$ErrorActionPreference = "Continue"

$PY   = "C:/Users/20614/AppData/Local/Python/pythoncore-3.14-64/python.exe"
$ROOT = Split-Path -Parent $PSScriptRoot
$OUT  = Join-Path $ROOT "data/snapshots"

$months = @(
    @{ label = "2027-06"; start = "2027-06-01"; end = "2027-06-30" },
    @{ label = "2027-07"; start = "2027-07-01"; end = "2027-07-31" },
    @{ label = "2027-08"; start = "2027-08-01"; end = "2027-08-31" },
    @{ label = "2027-09"; start = "2027-09-01"; end = "2027-09-30" },
    @{ label = "2027-10"; start = "2027-10-01"; end = "2027-10-31" }
)

$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force -Path $OUT | Out-Null

$failures = 0

foreach ($m in $months) {
    Write-Host ""
    Write-Host ("===== {0} : {1} ~ {2} =====" -f $m.label, $m.start, $m.end)

    foreach ($media in @("bus", "metro")) {
        $outfile = Join-Path $OUT ("{0}_{1}_{2}.csv" -f $media, $m.start, $m.end)
        Write-Host ("--- fetching {0} -> {1} ---" -f $media, $outfile)

        & $PY (Join-Path $ROOT "scripts/fetch_hongdou.py") `
            --start $m.start --end $m.end --only $media --out $OUT

        if ($LASTEXITCODE -ne 0) {
            Write-Host ("[FAIL] {0} {1} exit={2}" -f $m.label, $media, $LASTEXITCODE)
            $failures++
        }
    }
}

Write-Host ""
Write-Host ("===== DONE, failures={0} =====" -f $failures)
exit $failures
