# -*- coding: utf-8 -*-
"""红豆真实库存加载：快照 CSV → 候选清单。

职责：
- 运行时只读 data/snapshots/*.csv（ProposalRunner 每次用 hongdou-inventory
  snapshot.py --overwrite 实时刷新后再 reload_data）；不再扫描 data/ 根目录，
  也不读 data/processed/*.json（那是审计/前端构建产物）。
- 公交按 (lineName, mediaName) 去重；地铁按 (lineName, exitName) 去重。
- 等级映射（bus 1=S/2=A++/3=A+/5=AA/6=unknown；metro 2=A++/3=A+）。
- 过滤 freeCount<=0、specialSituation 非空、未知等级；跨月取 min free（绝不求和）。
- 日期覆盖：请求 start/end 覆盖的月份，取重叠快照；缺失月 raise DATA_UNAVAILABLE
  （除非 allow_fallback=True 则用可用月兜底并标记）。
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from . import config
from .models import PlanError

# CSV 列名（去掉 BOM）
BUS_KINDS = {"BUS_VEHICLE"}
METRO_KINDS = {"METRO_GATE"}


class _Rows:
    """分批返回的原始行容器（跨月共享字段名）。"""

    def __init__(self) -> None:
        self.header: List[str] = []


@dataclass
class Candidate:
    """一条去重后的候选（bus 线 or metro 口）。"""

    id: str
    kind: str                 # bus / metro
    line_name: str            # 公交线路名 / 地铁站名
    media_type: str           # 大三侧 / 车身三侧 / 地铁出入口
    exit_name: Optional[str]  # 地铁出入口
    company: Optional[str]
    level: str
    free_count: int           # 跨月最小可售
    district: str
    station_attr: str         # 换乘信息（metro）
    business_area: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Inventory:
    """一次请求对应的库存快照结果。"""

    bus: List[Candidate]
    metro: List[Candidate]
    data_version: str
    inventory_ts: str
    inventory_periods: List[str]
    months: int
    source_files: List[str]
    fell_back: bool = False
    fallback_reason: str = ""


def _strip_bom(s: str) -> str:
    return s.lstrip("﻿")


def _read_csv(path: str) -> List[Dict[str, str]]:
    """读 CSV 返回 list[dict]；容错：字段缺失置空串。"""
    rows: List[Dict[str, str]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _month_of(snapshot_filename: str) -> Optional[str]:
    """从文件名解析月份区间，如 bus_2027-07-01_2027-07-31.csv → 2027-07。"""
    base = os.path.basename(snapshot_filename)
    parts = base.split("_")
    # bus_YYYY-MM-DD_YYYY-MM-DD.csv
    if len(parts) >= 3:
        d0 = parts[1]
        if len(d0) >= 7:
            return d0[:7]
    return None


def _list_month_snapshots() -> Dict[str, Dict[str, str]]:
    """返回 {month: {"bus": path, "metro": path}}，只扫描 data/snapshots。"""
    out: Dict[str, Dict[str, str]] = {}
    d = config.SNAPSHOT_DIR
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".csv"):
            continue
        m = _month_of(fn)
        if not m:
            continue
        full = os.path.join(d, fn)
        if fn.startswith("bus_"):
            out.setdefault(m, {})["bus"] = full
        elif fn.startswith("metro_"):
            out.setdefault(m, {})["metro"] = full
    return out


def _months_in_range(start_date: str, end_date: str) -> List[str]:
    """返回覆盖的自然月份列表（yyyymm 形式，向上取整）。"""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    out: List[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _int(s: Any) -> int:
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


def _safe(s: Any) -> str:
    return "" if s is None else str(s).strip()


def _bus_level(v: str) -> str:
    try:
        return config.BUS_LEVEL_MAP.get(int(float(v)), "unknown")
    except (TypeError, ValueError):
        return "unknown"


def _metro_level(v: str) -> str:
    try:
        return config.METRO_LEVEL_MAP.get(int(float(v)), "unknown")
    except (TypeError, ValueError):
        return "unknown"


def _dedupe_bus(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str], Dict[str, str]]:
    """按 (lineName, mediaName) 去重；保留 freeCount 更大的一条（信息最多）。"""
    best: Dict[Tuple[str, str], Dict[str, str]] = {}
    for r in rows:
        key = (_safe(r.get("lineName")), _safe(r.get("mediaName")))
        if not all(key):
            continue
        if key not in best or _int(r.get("freeCount")) > _int(best[key].get("freeCount")):
            best[key] = r
    return best


def _dedupe_metro(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str], Dict[str, str]]:
    """按 (lineName, exitName) 去重。"""
    best: Dict[Tuple[str, str], Dict[str, str]] = {}
    for r in rows:
        key = (_safe(r.get("lineName")), _safe(r.get("exitName")))
        if not all(key):
            continue
        if key not in best or _int(r.get("freeCount")) > _int(best[key].get("freeCount")):
            best[key] = r
    return best


def load_inventory(request, allow_fallback: bool = False) -> Inventory:
    """加载请求档期覆盖月份的库存；缺月 raise / fallback。"""
    months = _months_in_range(request.start_date, request.end_date)
    month_snap = _list_month_snapshots()

    # 媒体感知：只要求请求中实际用到的媒体的快照存在。
    # bus-only 请求不因缺少 metro 快照而失败，反之亦然。
    want_bus = "bus" in request.media
    want_metro = "metro" in request.media
    if not want_bus and not want_metro:
        want_bus = want_metro = True  # 兜底：未指定媒体则按两类都要

    def _missing_for(months: List[str]) -> List[str]:
        out: List[str] = []
        for m in months:
            snap = month_snap.get(m, {})
            if want_bus and "bus" not in snap:
                out.append(f"{m}:bus")
            if want_metro and "metro" not in snap:
                out.append(f"{m}:metro")
        return out

    missing = _missing_for(months)

    if missing and not allow_fallback:
        raise PlanError(
            "DATA_UNAVAILABLE",
            f"目标档期缺少快照 {', '.join(missing)}（现有：{', '.join(sorted(month_snap.keys())) or '无'}）",
            field="start_date",
            suggestions=[
                "选择已抓取月份作为档期",
                "联系数据组抓取缺失月份快照",
                "调用时传 allow_fallback=True 用现有月份兜底",
            ],
        )

    fell_back = bool(missing)
    use_months = months if not missing else sorted(month_snap.keys())

    # 逐月读 bus/metro，按去重键跨月聚合：min_free = 各月原始 freeCount 的最小值；
    # 任一覆盖月 free<=0 或 specialSituation 非空 -> 整键剔除（活动贯穿全部月份，某月不可售即不可选）。
    bus_free: Dict[Tuple[str, str], int] = {}
    metro_free: Dict[Tuple[str, str], int] = {}
    bus_row: Dict[Tuple[str, str], Dict[str, str]] = {}
    metro_row: Dict[Tuple[str, str], Dict[str, str]] = {}
    bus_bad: set = set()
    metro_bad: set = set()
    sources: List[str] = []

    for m in use_months:
        mp = month_snap.get(m, {})
        for kind in (("bus",) if want_bus else ()) + (("metro",) if want_metro else ()):
            p = mp.get(kind)
            if not p:
                continue
            sources.append(p)
            rows = _read_csv(p)
            if kind == "bus":
                ded = _dedupe_bus(rows)
                free_map = bus_free
                row_map = bus_row
                bad_map = bus_bad
            else:
                ded = _dedupe_metro(rows)
                free_map = metro_free
                row_map = metro_row
                bad_map = metro_bad
            for k, row in ded.items():
                # 等级未知的整月剔除（等级跨月一致，非跨月敏感）
                lv = _bus_level(row.get("lineLevel")) if kind == "bus" else _metro_level(row.get("lineLevel"))
                if lv == "unknown":
                    continue
                # 任一覆盖月 special / free<=0：标记整键剔除（跨月敏感，延后统一处理）
                if _safe(row.get("specialSituation")):
                    bad_map.add(k)
                f = _int(row.get("freeCount"))
                if f <= 0:
                    bad_map.add(k)
                if k not in free_map:
                    free_map[k] = f
                    row_map[k] = row
                else:
                    free_map[k] = min(free_map[k], f)  # 跨月取 min，绝不求和

    # 统一剔除跨月不可售键
    for k in bus_bad:
        bus_free.pop(k, None)
        bus_row.pop(k, None)
    for k in metro_bad:
        metro_free.pop(k, None)
        metro_row.pop(k, None)

    # 组装 Candidate
    bus_cand: List[Candidate] = []
    for (line, media), fc in bus_free.items():
        row = bus_row[(line, media)]
        lv = _bus_level(row.get("lineLevel"))
        company = _safe(row.get("companyName"))
        bus_cand.append(Candidate(
            id=f"bus:{line}:{media}",
            kind="bus",
            line_name=line,
            media_type=media,
            exit_name=None,
            company=company or None,
            level=lv,
            free_count=fc,
            district=config.bus_region(company),
            station_attr="",
            business_area="",
            raw=row,
        ))

    metro_cand: List[Candidate] = []
    for (station, exit_name), fc in metro_free.items():
        row = metro_row[(station, exit_name)]
        lv = _metro_level(row.get("lineLevel"))
        code = _safe(row.get("districtname"))
        metro_cand.append(Candidate(
            id=f"metro:{station}:{exit_name}",
            kind="metro",
            line_name=station,
            media_type="地铁出入口",
            exit_name=exit_name or None,
            company=None,
            level=lv,
            free_count=fc,
            district=config.metro_district(code),
            station_attr=_safe(row.get("stationAttr")),
            business_area=_safe(row.get("businessAreaName")),
            raw=row,
        ))

    data_version = _data_version(sources)
    inventory_ts = _latest_mtime(sources)

    return Inventory(
        bus=bus_cand,
        metro=metro_cand,
        data_version=data_version,
        inventory_ts=inventory_ts,
        inventory_periods=[f"{m}-01..{m}-{_days_in_month(m)}" for m in use_months],
        months=len(use_months),
        source_files=sources,
        fell_back=fell_back,
        fallback_reason=("缺月 " + ", ".join(missing)) if fell_back else "",
    )


def _days_in_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    import calendar
    return f"{calendar.monthrange(y, m)[1]:02d}"


def _data_version(sources: List[str]) -> str:
    """data_version = sha256(排序文件名 + 内容 sha) 前 12 位。"""
    h = hashlib.sha256()
    for p in sorted(set(sources)):
        h.update(p.encode("utf-8"))
        with open(p, "rb") as f:
            h.update(hashlib.sha256(f.read()).hexdigest().encode("utf-8"))
    return h.hexdigest()[:12]


def _latest_mtime(sources: List[str]) -> str:
    if not sources:
        return ""
    newest = max(sources, key=os.path.getmtime)
    ts = os.path.getmtime(newest)
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S+08:00")


def reload_data() -> None:
    """清空已缓存清单（供数据更新后重载）。data_loader 本身无全局缓存，
    保留此函数以供 orchestrator 调用时语义对齐。"""
    return None


__all__ = ["Candidate", "Inventory", "load_inventory", "reload_data"]
