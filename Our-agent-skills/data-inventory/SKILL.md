---
name: data-inventory
description: 红豆库存数据阶段：检查令牌、按目标档期强制实时拉取月度快照（--overwrite）、对快照做可售汇总。只读；凭证来自 HONGDOU_USER/HONGDOU_PASS 或 gitignored 文件，绝不打印。这是引擎求解前的库存数据入库阶段。
version: 1.1.0
stage: data_inventory
order: 15
tools: [inventory.status, inventory.snapshot, inventory.analyze]
outputs: [inventory-summary, data-version, warnings]
guardrails:
  - 只调用 .claude/skills/hongdou-inventory/scripts 下的只读脚本（auth/snapshot/analyze）。
  - 不打印 token/password/安全码；所有日志与异常信息都做脱敏。
  - 只抓 policy.allowed_months 允许的月份，默认 2027-07/08。
  - "工作流强制实时拉取：每次提案都传 --overwrite 覆盖写 data/snapshots，忽略 options.data_mode（cached 不再跳过）。"
  - 抓取失败/部分失败不得破坏旧快照文件；保留旧文件并把状态记为 degraded。
  - snapshot 写出的 CSV 才进引擎；fetch.py 的筛选结果绝不放进 data/snapshots。
  - 不允许把 2023-05 与 2027 库存/报价混写。
---

# 数据阶段：红豆库存入库（data-inventory）

> 脚本真实路径：`.claude/skills/hongdou-inventory/scripts/`（本 skill 只是薄适配层，不复制脚本）。
> 角色：在确定性引擎求解前，确认/刷新目标档期的库存快照可读，并回传数据版本。

## 0. 你在这一步做什么

1. **status** —— 检查红豆令牌是否可用（`auth.py --status` 只读本地缓存，不发网络）。
2. **snapshot** —— 按请求档期覆盖的月份，抓/校验 `data/snapshots/{bus,metro}_YYYY-MM-*.csv`。
3. **analyze** —— 对目标快照做离线汇总，产出可售明细摘要。

你**不改价格、不算曝光、不改库存数字**；这些由 `engine/data_loader.py` 读取快照后交求解器。

---

## 1. 命令（在项目根执行，`.venv\Scripts\python.exe`）

```powershell
$SK = ".claude\skills\hongdou-inventory\scripts"

# 1) 令牌状态（只读；无缓存/过期返回非零退出码）
.venv\Scripts\python.exe $SK\auth.py --status

# 2) 目标档期月度快照（工作流强制实时拉取：总是 --overwrite）
.venv\Scripts\python.exe $SK\snapshot.py --from-month 2027-07 --to-month 2027-08 --overwrite

# 3) 对目标快照做离线汇总
.venv\Scripts\python.exe $SK\analyze.py --file data\snapshots\metro_2027-07-01_2027-07-31.csv --free-only --exclude-special
```

- `stdout` 是 JSON，`stderr` 是进度/错误摘要；只解析 stdout JSON。
- `snapshot.py` 写 `data/snapshots/hongdou_fetch_manifest.json` 只是抓取审计，不参与引擎加载。
- 引擎真正生效依赖：快照 CSV 落盘 + `engine.orchestrator.reload_data()` + `engine.candidates.reload_geo()` 清缓存。

---

## 2. 月份与档期规则

- 只允许抓 `policy.allowed_months`（2027-06..10）内的月份。
- 目标月份来自请求 `start_date`/`weeks` 覆盖的自然月；缺省默认 2027-07 与 2027-08。
- **强制拉取**：`ProposalRunner` 每次都调 `snapshot.py --overwrite`（`media=all`），不读 `data_mode`，不跳过已有快照。
- 档期覆盖月缺快照：引擎会 `DATA_UNAVAILABLE`；此时按 policy.failure 策略降级，不静默换月。

---

## 3. 输出契约

```jsonc
{
  "status": "ready | degraded | skipped",
  "mode": "live",
  "forced": true,
  "tools": {
    "inventory.status":  {"ok": true, "authenticated": true, "remaining_sec": 1234},
    "inventory.snapshot": {"ok": true, "months": ["2027-07"], "entries": [{"month":"2027-07","media":"bus","status":"ok","rows":334}]},
    "inventory.analyze": {"ok": true, "summary": {"rows": 334, "free_points": 280}}
  },
  "data_version": "<engine 重载后的 data_version>",
  "inventory_ts": "<最新快照 mtime>",
  "warnings": ["红豆抓取超时，保留旧快照"],
  "credential_source": "env 或 gitignored 文件（不打印值）"
}
```

- `status` 取值：`ready`（成功刷新或确认）、`degraded`（部分失败但旧快照可用）、`skipped`（无凭证/离线，仅用现有快照）。
- 任何输出都带数据时间戳/版本/来源；绝不含 token 原文。

---

## 4. 自检

- [ ] 未打印 token/password/安全码
- [ ] 只调用了 auth/snapshot/analyze 三个只读脚本
- [ ] 目标月份在 allowed_months 白名单内
- [ ] 每次提案都传 --overwrite 实时拉取，忽略 data_mode=cached
- [ ] 失败时保留旧快照，status 降级为 degraded 而非伪造成功
- [ ] 快照文件路径落在 data/snapshots/，且文件名符合 `{media}_YYYY-MM-01_YYYY-MM-last.csv`
