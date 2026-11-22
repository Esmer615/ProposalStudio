---
name: data-bigdata
description: 新云大数据平台数据阶段：媒体覆盖查询、周边 POI 计数、方案公交线路真实几何（AI线路），作为 Agent 解释/可视化上下文（不是报价或库存来源）。只读脚本；数据月份固定 202305；需人工验证码登录一次。无有效会话/验证码时跳过不阻塞。
version: 1.1.0
stage: data_bigdata
order: 16
tools: [bigdata.coverage, bigdata.poi, bigdata.routes]
outputs: [coverage-context, poi-context, route-geometry, warnings]
guardrails:
  - 只允许调用只读脚本（coverage.mjs、coverage_poi.mjs、ai_route_batch.mjs）；禁用 ai_share、condition、address 全量、批量全网格。
  - 线路几何只用于可视化，不进入报价/库存/Reach/评分；数据月份固定 202305。
  - 无有效会话/验证码时返回 skipped + reason=MANUAL_LOGIN_REQUIRED，不尝试自动登录、不绕过验证码。
  - 会话过期不自动登录；成果只作为解释/可视化上下文。
  - allow_share=false；radius、POI 类型、线路条数与缓存 TTL 受 policy 白名单约束。
---

# 数据阶段：新云大数据上下文（data-bigdata）

> 脚本真实路径：`.claude/skills/xinyun-bigdata/scripts/`（薄适配层，不复制脚本）。
> 角色：为提案提供“周边覆盖/POI/方案线路几何”解释与可视化上下文；**不改报价、不改库存数字、不改评分**。

## 0. 你在这一步做什么

1. **coverage** —— 中心场馆 + 半径 → 周边公交线路/地铁站（`coverage.mjs`）。
2. **poi** —— 中心场馆 + 半径 → 周边 POI 计数（`coverage_poi.mjs --mode count`）。
3. **routes** —— 引擎选出的公交线路名（`plan.bus[].line`）+ 方案地铁线路（`plan.metro[]` 的 L01/L09/L11 证据与站名表 LINE_NO → `地铁N号线`）→ 真实线路几何（`ai_route_batch.mjs`，只读/缓存）。平台线路树含「地铁线路」分组，地铁按前缀匹配分支。

会话文件 `data/external/platform_storage.json` 由人工 `login.mjs`（过验证码一次）生成；缺失即跳过。
先用 `ai_route_batch.mjs --check` 轻量确认会话，避免会话过期时白等页面脚本。

---

## 1. 命令（项目根执行，Node 用系统 `node`）

```powershell
$SK = ".claude\skills\xinyun-bigdata\scripts"

# 会话探测（不开浏览器）
node $SK\ai_route_batch.mjs --check

# 覆盖媒体（只读）
node $SK\coverage.mjs --address "上海乐高乐园" --radius 1000

# 周边点位（只读，count 模式，类型受白名单约束）
node $SK\coverage_poi.mjs --address "上海乐高乐园" --radius 1000 --types "商场,幼儿园" --mode count

# 方案线路真实几何（只读；最多 policy.routes_max_lines 条；带缓存）
node $SK\ai_route_batch.mjs --lines "136,157,17" --out data\external\platform\queries
```

- `ai_route_batch.mjs` 的 `stdout` 是单行 JSON（`lines[]` 含 `path`/`bbox`）；`missing[]` 显式列出线路缺失。
- 全部缓存命中时不启动浏览器；`--cached-only` 可强制离线。
- 若会话文件不存在/过期，返回 `MANUAL_LOGIN_REQUIRED`，不自动登录。

---

## 2. 白名单与限制

- radius 只允许 `policy.radius_whitelist`（默认 1000）。
- POI 类型只允许 `policy.poi_type_whitelist`（默认 商场/幼儿园/学校/医院/交通枢纽 等）。
- 线路：最多 `policy.routes_max_lines` 条，缓存 TTL `policy.route_cache_ttl_days` 天；超限截断并在 warnings 说明。
- `data_month` 固定 `202305`；覆盖接口无日期参数，属当前轨迹快照。
- `allow_share=false`：不调用 `ai_share.mjs`；不调 `condition.mjs`/`address.mjs` 全量；不批量拉网格。
- 线路几何只作为地图可视化上下文；不进入报价/库存/Reach/评分。

---

## 3. 输出契约

```jsonc
{
  "status": "ready | degraded | skipped",
  "reason": "MANUAL_LOGIN_REQUIRED | ... | null",
  "tools": {
    "bigdata.coverage": {"ok": true, "summary": {"bus": 2, "metro": 0, "bus_lines": ["1675路"]}},
    "bigdata.poi":     {"ok": true, "summary": {"商场": 1, "幼儿园": 0}},
    "bigdata.routes":  {"ok": false, "summary": {"requested": 23, "resolved": 1, "cached": 1, "fetched": 0, "missing": 22}}
  },
  "coverage-context": {"bus_lines": ["1675路"], "metro_stations": []},
  "poi-context": {"商场": 1, "幼儿园": 0},
  "route-geometry": [{"line": "1001", "lineId": 9871, "path": [[121.58, 31.11]], "bbox": [121.57, 31.11, 121.59, 31.12], "source": "新云 AI线路", "data_month": "202305"}],
  "data_month": "202305",
  "warnings": ["线路几何 1/23 条（MANUAL_LOGIN_REQUIRED），缺失线路按区县示意"]
}
```

- 无有效会话/验证码 → `status=skipped`、`reason=MANUAL_LOGIN_REQUIRED`，不阻塞引擎；缓存命中仍可出图。
- 超时/数据为空 → `status=degraded`，地图只用本地图层，标注“2023-05 补充数据不可用”。
- 所有日志脱敏；不打印会话/凭证内容。

---

## 4. 自检

- [ ] 只调了 coverage / coverage_poi / ai_route_batch 三个只读命令
- [ ] 没调 ai_share / condition / address 全量
- [ ] radius、POI 类型、线路条数在 policy 白名单内
- [ ] data_month 固定 202305，没混入 2027 数字
- [ ] 线路几何只用于可视化，没进入报价/库存/评分
- [ ] 无会话时跳过并给出 MANUAL_LOGIN_REQUIRED，没自动登录
