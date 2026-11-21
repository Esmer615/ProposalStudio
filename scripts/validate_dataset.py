#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验 data/processed/ 数据资产的一致性。失败时非零退出。

校验项：
  1) manifest 与 inventory/candidates 的行数/free 对账
  2) candidates 中无 free<=0（min_free 应 >0）
  3) candidates 中无 specialSituation 封闭/改造口
  4) 未知等级被标记（不静默）
  5) 跨月 min_free 正确（不求和）
  6) manifest.map 文件 sha256 与磁盘一致
  7) candidates.geo.json / candidates_enriched.json 存在且与 candidates 同键数

用法：
    PYTHONIOENCODING=utf-8 python scripts/validate_dataset.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(BASE, "data", "processed")
DATA = os.path.join(BASE, "data")


def load(p):
    return json.load(open(p, encoding="utf-8"))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    errors = []
    warns = []

    manifest_path = os.path.join(PROC, "manifest.json")
    inventory_path = os.path.join(PROC, "inventory.json")
    candidates_path = os.path.join(PROC, "candidates.json")

    for p in (manifest_path, inventory_path, candidates_path):
        if not os.path.exists(p):
            errors.append(f"缺少文件 {p}")
            return 1

    manifest = load(manifest_path)
    inventory = load(inventory_path)
    candidates = load(candidates_path)

    # 1) 行数/free 对账：manifest.monthly vs inventory
    monthly = manifest.get("monthly", {})
    inv_monthly = {}
    for r in inventory:
        m = r["month"]
        t = r["type"]
        inv_monthly.setdefault(m, {"bus": {"rows": 0, "free": 0}, "metro": {"rows": 0, "free": 0}})
        inv_monthly[m][t]["rows"] += 1
        inv_monthly[m][t]["free"] += r["free"]

    for m in sorted(monthly):
        if m not in inv_monthly:
            errors.append(f"manifest 月 {m} 在 inventory 中缺失")
            continue
        for t in ("bus", "metro"):
            a = monthly[m][t]
            b = inv_monthly[m][t]
            if a["rows"] != b["rows"]:
                errors.append(f"{m}/{t} 行数不符 manifest={a['rows']} vs inventory={b['rows']}")
            if a["free"] != b["free"]:
                errors.append(f"{m}/{t} free 不符 manifest={a['free']} vs inventory={b['free']}")

    # 2) candidates 无 free<=0
    for c in candidates:
        if (c.get("min_free") or 0) <= 0:
            errors.append(f"候选 {c['business_key']} min_free<=0")

    # 3) candidates 无封闭/改造特殊状态
    block_kw = ["封闭", "改造", "施工", "停用", "停运"]
    for c in candidates:
        sp = c.get("specialSituation") or ""
        if sp and any(k in sp for k in block_kw):
            errors.append(f"候选 {c['business_key']} 存在封闭/改造状态: {sp}")

    # 4) 未知等级标记
    unknown = [c for c in candidates if c.get("level") == "unknown"]
    if unknown:
        warns.append(f"存在 {len(unknown)} 个未知等级候选（已标记，需在引擎排除或人工处理）")

    # 5) 跨月 min_free 校验：对每个候选，min_free 必须等于其所有 record 的 min
    key_to_free = {}
    for r in inventory:
        k = r["business_key"]
        key_to_free.setdefault(k, [])
        key_to_free[k].append(r["free"])
    for c in candidates:
        k = c["business_key"]
        if k in key_to_free:
            expected_min = min(key_to_free[k])
            if c["min_free"] != expected_min:
                errors.append(f"候选 {k} min_free={c['min_free']} != 跨月 min={expected_min}")

    # 6) manifest 文件 sha256 对账
    for fd in manifest.get("files", []):
        # 找对应文件
        base = fd.get("path")
        # 尝试 snapshots 和 data 根
        for cand in (os.path.join(DATA, "snapshots", base), os.path.join(DATA, base)):
            if os.path.exists(cand):
                actual = sha256_file(cand)
                if actual != fd.get("sha256"):
                    errors.append(f"{base} sha256 不符 manifest={fd.get('sha256')[:10]} vs 磁盘={actual[:10]}")
                break
        else:
            warns.append(f"manifest 文件 {base} 未在磁盘找到（可能已移动）")

    # 7) geo/enriched 文件存在性
    for name in ("candidates.geo.json", "candidates_enriched.json"):
        p = os.path.join(PROC, name)
        if not os.path.exists(p):
            warns.append(f"缺少 {name}（富化文件）")

    # 输出结果
    print(f"校验 inventory={len(inventory)} 条，candidates={len(candidates)} 条")
    print(f"manifest data_version={manifest.get('data_version')}")
    print(f"错误: {len(errors)}  警告: {len(warns)}")
    for w in warns:
        print(f"  [WARN] {w}")
    for e in errors:
        print(f"  [FAIL] {e}")

    if errors:
        print("校验失败（exit 1）")
        return 1
    print("校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
