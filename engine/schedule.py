# -*- coding: utf-8 -*-
"""排期：阶段 / 批次 / 夜装产能 / 雨备 / 监测 SLA / 误一补二。

使用请求的真实 2027 日期；批次 units 总和 == 付费 units；
安装日期在 go-live 前；公交 20 辆/晚、地铁 10 口/晚、10 夜、2 雨备。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from . import config


def _d(d: date, days: int) -> str:
    return (d + timedelta(days=days)).isoformat()


def build_schedule(request, bus_items: List[Dict[str, Any]], metro_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """bus_items/metro_items: 已选付费条目（含 units/status='paid'）。"""
    go_live = date.fromisoformat(request.start_date)
    take_down = date.fromisoformat(request.end_date)
    total_days = (take_down - go_live).days + 1

    bus_units = sum(it["units"] for it in bus_items if it.get("status") != "gift")
    metro_units = sum(it["units"] for it in metro_items if it.get("status") != "gift")

    # 批次需夜数（公交 20/晚、地铁 10/晚，公交与地铁并行安装）
    import math as _math
    bus_nights = _math.ceil(bus_units / config.BUS_PER_NIGHT) if bus_units else 0
    metro_nights = _math.ceil(metro_units / config.METRO_PER_NIGHT) if metro_units else 0
    nights_needed = max(bus_nights, metro_nights)

    # 安装窗口从实际批次数推导（含雨备），保证所有批次日期 < go_live
    rain_buffer = config.RAIN_BUFFER_NIGHTS
    install_start = go_live - timedelta(days=nights_needed + rain_buffer)
    # 最后安装夜 = install_start + (nights_needed - 1) = go_live - rain_buffer - 1
    # 余下 rain_buffer 天 + 最后一天（go_live 前一天）留作雨备，绝不越过 go-live
    last_install = install_start + timedelta(days=max(0, nights_needed - 1))

    # 阶段（往前倒推，严格不重叠；P3 制作在安装起始前完成，P4 夜间安装覆盖实际安装窗口）
    p3_end = install_start - timedelta(days=1)          # 制作截止 = 安装前 1 天
    p3_start = p3_end - timedelta(days=5)               # 制作 6 天
    p2_end = p3_start - timedelta(days=1)
    p2_start = p2_end - timedelta(days=2)               # 内容审批 3 天
    p1_end = p2_start - timedelta(days=1)
    p1_start = p1_end - timedelta(days=5)               # 设计定稿 6 天
    phases = [
        {"id": "P1", "name": "设计定稿", "start": p1_start.isoformat(), "end": p1_end.isoformat(), "owner": "创意/客户"},
        {"id": "P2", "name": "内容审批", "start": p2_start.isoformat(), "end": p2_end.isoformat(), "owner": "客户/法务"},
        {"id": "P3", "name": "制作", "start": p3_start.isoformat(), "end": p3_end.isoformat(), "owner": "制作组"},
        {"id": "P4", "name": "夜间安装", "start": install_start.isoformat(), "end": last_install.isoformat(), "owner": "运营"},
        {"id": "P5", "name": "上刊", "start": request.start_date, "end": request.start_date, "owner": "运营"},
        {"id": "P6", "name": "监测", "start": request.start_date, "end": request.end_date, "owner": "运营"},
        {"id": "P7", "name": "下刊", "start": _d(take_down, 1), "end": _d(take_down, 2), "owner": "运营"},
    ]

    # 产能元数据
    night_capacity = {
        "bus_per_night": config.BUS_PER_NIGHT,
        "metro_per_night": config.METRO_PER_NIGHT,
        "nights": nights_needed,
        "rain_buffer_nights": rain_buffer,
    }

    batches: List[Dict[str, Any]] = []
    bid = 0
    bus_sorted = sorted(bus_items, key=lambda x: (-x.get("score", 0), x["id"]))
    metro_sorted = sorted(metro_items, key=lambda x: (-x.get("score", 0), x["id"]))
    bus_units_list = [it for it in bus_sorted for _ in range(it["units"])]
    metro_units_list = [it for it in metro_sorted for _ in range(it["units"])]

    def chunks(lst, n):
        return [lst[i:i + n] for i in range(0, len(lst), n)]

    bus_chunks = chunks(bus_units_list, config.BUS_PER_NIGHT)
    metro_chunks = chunks(metro_units_list, config.METRO_PER_NIGHT)

    def _emit(ch, media, crew, day):
        nonlocal bid
        bid += 1
        items = []
        seen = set()
        for it in ch:
            if it["id"] not in seen:
                items.append(it["id"]); seen.add(it["id"])
        return {"id": f"B{bid}", "date": day.isoformat(), "window": "23:00-05:00",
                "media": media, "units": len(ch), "crew": crew, "items": items,
                "rain_backup": (day + timedelta(days=3)).isoformat()}

    # 公交与地铁按夜并行：第 k 夜同时上公交与地铁各自的第 k 批
    for k in range(nights_needed):
        day = install_start + timedelta(days=k)
        if k < len(bus_chunks):
            batches.append(_emit(bus_chunks[k], "bus", "公交班组", day))
        if k < len(metro_chunks):
            batches.append(_emit(metro_chunks[k], "metro", "地铁班组", day))

    # 不变量：每个批次日期 < go_live；批次 units 总和 == 付费 units
    for b in batches:
        bd = date.fromisoformat(b["date"])
        assert bd < go_live, f"批次 {b['id']} 日期 {b['date']} 越过上刊日 {go_live}"
    batch_units = sum(b["units"] for b in batches)
    assert batch_units == bus_units + metro_units, \
        f"批次 units 总和 {batch_units} != 付费 units {bus_units + metro_units}"

    monitoring = [
        {"name": "上刊证明", "due": "上刊当日/次日", "sla": "带报头日期照片", "owner": "运营"},
        {"name": "上刊监测报告", "due": "上刊后 5 个工作日", "sla": "近/远/多角度照片", "owner": "运营"},
        {"name": "下刊监测报告", "due": "下刊后 5 个工作日", "sla": "下刊照片", "owner": "运营"},
        {"name": "月度报告", "due": "每月结束后", "sla": "播放/展示证明", "owner": "运营"},
    ]

    return {
        "go_live": request.start_date,
        "take_down": request.end_date,
        "total_days": total_days,
        "phases": phases,
        "batches": batches,
        "night_capacity": night_capacity,
        "monitoring": monitoring,
        "compensation": {"rule": "误一补二", "note": "延迟按损失天数×广告价值双倍补偿；合同口径"},
        "risks": ["雨天停工顺延", "夜间施工上限", "库存被占自动替换"],
    }


__all__ = ["build_schedule"]
