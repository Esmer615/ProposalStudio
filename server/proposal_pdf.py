# -*- coding: utf-8 -*-
"""模板化投放提案 PDF（本地）：run 数据 → A4 HTML → 本机 Chrome 打印 → 本地 PDF。

设计依据：`docs/03-合同三份-脱敏版等9个文件` 的历史销售提案样本（FLAIR MEDIA 提案结构）
与直客合同/4A 框架/4A 订单的签约要点。所有数字只来自 run payload，不在 PDF 里重算。
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPORT_DIR = PROJECT_ROOT / "data" / "exports" / "proposals"
PUBLIC_DIR = PROJECT_ROOT / "web" / "public" / "proposals"
DIST_DIR = PROJECT_ROOT / "web" / "dist" / "proposals"
DISTRICTS_PATH = PROJECT_ROOT / "data" / "geo" / "shanghai_districts.geojson"

CHROME_CANDIDATES = [
    os.environ.get("CHROME_PATH"),
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]


def _chrome() -> Optional[str]:
    for path in CHROME_CANDIDATES:
        if path and Path(path).is_file():
            return str(path)
    return None


def _e(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return html.escape(str(value))


def _num(value: Any, digits: int = 0) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _pct(value: Any, digits: int = 1) -> str:
    try:
        v = float(value)
        if abs(v) <= 1:
            v *= 100
        return f"{v:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _date(value: Any) -> str:
    return str(value or "—").replace("T", " ")[:10]


def _table(headers: List[str], rows: List[List[Any]], cls: str = "") -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{c if isinstance(c, str) and c.startswith('<') else _e(c)}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return f'<table class="tbl {cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _svg_map(plan: Dict[str, Any]) -> str:
    """A simple WGS84 Shanghai outline + xinyun route geometry + selected points."""
    districts = _load_districts()
    routes_bus = ((plan.get("coverage") or {}).get("map_layers") or {}).get("bus_routes") or []
    routes_metro = ((plan.get("coverage") or {}).get("map_layers") or {}).get("metro_routes") or []
    metro_points = ((plan.get("plan") or {}).get("metro") or [])
    venue = (plan.get("venue") or {})
    coords: List[List[float]] = []
    for geom in districts:
        for ring in geom:
            coords.extend(ring)
    for route in routes_bus + routes_metro:
        coords.extend((route.get("geometry") or {}).get("path") or [])
    if not coords:
        return '<div class="map-empty">本次 run 无线路几何</div>'
    lngs = [float(p[0]) for p in coords if isinstance(p, (list, tuple)) and len(p) >= 2]
    lats = [float(p[1]) for p in coords if isinstance(p, (list, tuple)) and len(p) >= 2]
    min_lng, max_lng = min(lngs), max(lngs)
    min_lat, max_lat = min(lats), max(lats)
    pad_lng = max(0.02, (max_lng - min_lng) * 0.04)
    pad_lat = max(0.02, (max_lat - min_lat) * 0.04)
    min_lng -= pad_lng; max_lng += pad_lng
    min_lat -= pad_lat; max_lat += pad_lat
    w, h = 900.0, 520.0

    def xy(lng: float, lat: float) -> str:
        x = (float(lng) - min_lng) / (max_lng - min_lng) * w
        y = (max_lat - float(lat)) / (max_lat - min_lat) * h
        return f"{x:.1f},{y:.1f}"

    district_paths = []
    for geom in districts:
        parts = []
        for ring in geom:
            if len(ring) < 3:
                continue
            parts.append("M" + " L".join(xy(p[0], p[1]) for p in ring) + " Z")
        if parts:
            district_paths.append(f'<path d="{" ".join(parts)}"/>')

    def polylines(routes: List[Dict[str, Any]], cls: str) -> str:
        out = []
        for route in routes:
            path = (route.get("geometry") or {}).get("path") or []
            if len(path) < 2:
                continue
            step = max(1, len(path) // 140)
            pts = [xy(p[0], p[1]) for p in path[::step]]
            if pts[-1] != xy(path[-1][0], path[-1][1]):
                pts.append(xy(path[-1][0], path[-1][1]))
            out.append(f'<polyline class="{cls}" points="{" ".join(pts)}"/>')
        return "".join(out)

    point_markup = []
    for item in metro_points:
        p = (item.get("geo") or {}).get("coords") or {}
        if p.get("lng") is None:
            continue
        point_markup.append(f'<circle class="point" cx="{xy(p["lng"], p["lat"]).split(",")[0]}" cy="{xy(p["lng"], p["lat"]).split(",")[1]}" r="3.2"/>')
    vcoords = venue.get("coords") or {}
    venue_markup = ""
    if vcoords.get("lng") is not None:
        vx, vy = xy(vcoords["lng"], vcoords["lat"]).split(",")
        venue_markup = f'<polygon class="venue" points="{float(vx):.1f},{float(vy)-9:.1f} {float(vx)+9:.1f},{float(vy):.1f} {float(vx):.1f},{float(vy)+9:.1f} {float(vx)-9:.1f},{float(vy):.1f}"/>'

    return f'''<svg class="map-svg" viewBox="0 0 {int(w)} {int(h)}" role="img" aria-label="上海场馆、地铁点位与方案公交/地铁线路示意">
  <rect width="{int(w)}" height="{int(h)}" fill="#f5f1e8"/>
  <g class="districts">{"".join(district_paths)}</g>
  <g class="bus-lines">{polylines(routes_bus, "bus-line")}</g>
  <g class="metro-lines">{polylines(routes_metro, "metro-line")}</g>
  <g class="metro-points">{"".join(point_markup)}</g>
  {venue_markup}
</svg>'''


@lru_cache(maxsize=1)
def _load_districts() -> List[List[List[tuple]]]:
    try:
        raw = json.loads(DISTRICTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: List[List[List[tuple]]] = []
    for feature in raw.get("features") or []:
        geom = feature.get("geometry") or {}
        if geom.get("type") == "Polygon":
            out.append([[tuple(p) for p in ring] for ring in geom.get("coordinates") or []])
        elif geom.get("type") == "MultiPolygon":
            for poly in geom.get("coordinates") or []:
                out.append([[tuple(p) for p in ring] for ring in poly])
    return out


def _sheet(inner: str, cls: str = "", run_id: str = "", data_version: str = "") -> str:
    foot = f'''<div class="page-foot"><span>FLAIR MEDIA · 上海新云传媒股份有限公司</span><span>提案 {_e(run_id)} · 数据版本 {_e(data_version)}</span></div>'''
    return f'<section class="sheet {cls}">{inner}{foot}</section>'


def _head(no: str, title: str, lead: str = "") -> str:
    return f'''<div class="sec-head"><span class="sec-no">{_e(no)}</span><div><h2>{_e(title)}</h2>{f'<p class="lead">{_e(lead)}</p>' if lead else ''}</div></div>'''


def _build_html(run: Dict[str, Any]) -> str:
    plan = run.get("plan") or {}
    inputs = plan.get("inputs") or {}
    request = (run.get("inputs") or {}).get("request") or {}
    meta = plan.get("meta") or {}
    body = plan.get("plan") or {}
    summary = body.get("summary") or {}
    hyp = plan.get("hypothesis") or {}
    strategy = plan.get("strategy") or {}
    quote = plan.get("quote") or {}
    effects = plan.get("effects") or {}
    schedule = plan.get("schedule") or {}
    validation = plan.get("validation") or {}
    coverage = plan.get("coverage") or {}
    layers = coverage.get("map_layers") or {}
    routes_bus = layers.get("bus_routes") or []
    routes_metro = layers.get("metro_routes") or []
    bus = [x for x in body.get("bus") or [] if isinstance(x, dict) and x.get("status") != "replaced"]
    metro = [x for x in body.get("metro") or [] if isinstance(x, dict) and x.get("status") != "replaced"]
    run_id = str(run.get("run_id") or "")
    data_version = meta.get("data_version") or "—"
    inventory_ts = meta.get("inventory_ts") or "—"
    venue = inputs.get("venue_name") or (plan.get("venue") or {}).get("name") or "项目场馆"
    budget = inputs.get("budget_wan") or request.get("budget_wan") or quote.get("budget_wan") or "—"
    start = inputs.get("start_date") or request.get("start_date") or "—"
    end = inputs.get("end_date") or "—"
    weeks = inputs.get("weeks") or request.get("weeks") or "—"
    customer = inputs.get("customer_type_label") or ("4A 代理" if (inputs.get("customer_type") == "4a") else "直客")
    media = " + ".join("公交车身" if m == "bus" else "地铁出入口" for m in (inputs.get("media") or request.get("media") or []))
    generated = datetime.now().strftime("%Y-%m-%d")
    rstatus = (run.get("data") or {}).get("routes") or {}
    route_summary = rstatus.get("summary") or {}
    revenue = quote.get("total_paid_wan")
    elasticity = run.get("elasticity") or plan.get("elasticity") or {}
    points = elasticity.get("points") or []
    checks = validation.get("checks") or []
    passed = sum(1 for c in checks if c.get("passed"))
    limitations = validation.get("limitations") or []
    bus_sorted = sorted(bus, key=lambda x: float(x.get("total_wan") or 0), reverse=True)
    metro_sorted = sorted(metro, key=lambda x: float(x.get("total_wan") or 0), reverse=True)
    bus_rows = [[
        x.get("name") or x.get("line") or "—",
        x.get("level") or "—",
        x.get("district") or "—",
        x.get("free_count") if x.get("free_count") is not None else "—",
        _num(x.get("total_wan"), 2),
    ] for x in bus_sorted[:16]]
    metro_rows = [[
        x.get("name") or f"{x.get('station') or ''} {x.get('exit') or ''}".strip() or "—",
        x.get("level") or "—",
        x.get("district") or "—",
        x.get("free_count") if x.get("free_count") is not None else "—",
        _num(x.get("total_wan"), 2),
    ] for x in metro_sorted[:10]]
    hyp_rows = "".join(
        f'<div class="hyp-item"><span>{_e(f.get("id"))}</span><div><b>{_e(f.get("label"))}</b><p>{_e(f.get("value"))}</p></div></div>'
        for f in (hyp.get("fields") or [])
    )
    roles = "".join(
        f'<div class="role"><span class="role-mark">{"B" if r.get("media") == "bus" else "M"}</span><b>{_e(r.get("role") or r.get("media"))}</b><small>目标占比 {_pct(r.get("share_target")) if r.get("share_target") is not None else "—"}</small></div>'
        for r in (strategy.get("media_roles") or [])
    )
    gift = "；".join(_e(g.get("name") or g.get("id")) for g in quote.get("gift_items") or []) or "无"
    phases = schedule.get("phases") or []
    phase_rows = [[_e(p.get("name")), _e(p.get("owner")), f'{_e(p.get("start"))} → {_e(p.get("end"))}'] for p in phases]
    batches = schedule.get("batches") or []
    batch_rows = [[_e(b.get("id")), _e(f'{b.get("date") or ""} {b.get("window") or ""}'.strip()), _e("公交" if b.get("media") == "bus" else "地铁"), _e(b.get("units")), _e(b.get("rain_backup"))] for b in batches]
    nc = schedule.get("night_capacity") or {}
    mon = (schedule.get("monitoring") or [{}])[0]
    route_lines = "、".join(_e(r.get("lineName") or r.get("line")) for r in (routes_bus + routes_metro)) or "—"
    media_mix = summary.get("media_mix") or {}
    bus_pct = float(media_mix.get("bus_pct") or 0)
    metro_pct = float(media_mix.get("metro_pct") or 0)
    contract_type = "4A 框架合同 + 4A 订单" if (inputs.get("customer_type") == "4a") else "户外媒体发布合同（直客）"
    clauses = [
        ("第一条 · 发布详情", "以本提案媒体清单及双方确认的施工排期为准；实际发布日以乙方提供每批次最后一辆/最后一个点位的施工照次日起算。"),
        ("第二条 · 付款与发票", "甲方按合同约定支付预付款与尾款；乙方开具增值税专用发票（税率 6%）。逾期付款的，广告制作/发布日期相应顺延。"),
        ("第三条 · 甲方权利义务", "甲方保证广告内容合法并提交营业执照、商标/肖像等证明；收到小样后 2 个工作日内确认，逾期视为确认；按约定验收。"),
        ("第四条 · 乙方权利义务", "乙方审核广告内容、保证车辆/点位状态；因车辆碰撞、损坏、调线等导致不能正常发布的，按“损一补一”处理；政府管制/恶劣天气顺延。"),
        ("第五条 · 违约责任", "甲方逾期付款按应付未付款 3‰/日支付违约金；任何一方单方违约/提前终止，按合同总额 20% 承担违约责任；争议由乙方所在地（上海市浦东新区）法院管辖。"),
        ("第六条 · 不可抗力", "台风、地震、政府新规等不可抗力导致不能履行的，双方不承担违约责任，按实际发布天数结算。"),
        ("第七条 · 保密", "双方对合同内容、价格、客户资料等商业信息保密，未经书面许可不得向第三方披露。"),
        ("第八条 · 其他", "未尽事宜另行协商；合同一式四份，双方各执二份，签字盖章后生效。"),
    ]
    clause_html = "".join(f'<div class="clause"><b>{_e(t)}</b><p>{_e(v)}</p></div>' for t, v in clauses)
    checks_html = "".join(f'<span class="check {"ok" if c.get("passed") else "bad"}">{_e(c.get("id"))} {_e(c.get("name"))}</span>' for c in checks[:10])
    elasticity_html = ""
    if points:
        erows = [[_num(p.get("budget_wan")), _num((p.get("impressions") or 0) / 10000, 1), _pct(p.get("reach")), _num(p.get("frequency"), 1), _num(p.get("cpm_yuan"), 1)] for p in points]
        elasticity_html = f'<h3>预算弹性（九档）</h3>{_table(["预算(万)", "曝光(万)", "Reach", "Frequency", "CPM(元)"], erows, "compact")}'
    else:
        elasticity_html = '<p class="note">本次 run 未计算预算弹性；不影响提案中的确定性报价与曝光结果。</p>'
    sources = "；".join(coverage.get("sources") or []) or "红豆广告媒体管理系统 2027 月度快照；公开 POI/地图近似数据"

    cover = f'''<section class="sheet cover">
  <div class="cover-top"><div class="brand">FLAIR<span>MEDIA</span></div><div class="brand-cn">上海新云传媒股份有限公司</div></div>
  <div class="cover-main">
    <div class="kicker">2027 OUT-OF-HOME MEDIA PROPOSAL</div>
    <h1>品牌户外媒体<br>投放提案</h1>
    <p class="cover-client">{_e(venue)} · 2027 暑期</p>
    <div class="cover-rule"></div>
    <p class="cover-meta">预算 {_e(budget)} 万 · 档期 {_e(start)} → {_e(end)} · {_e(weeks)} 周<br>{_e(media)} · {_e(customer)} · 提案编号 {_e(run_id)}</p>
  </div>
  <div class="cover-bottom"><span>CONFIDENTIAL · 本提案仅供客户内部评估</span><span>{_e(generated)}</span></div>
</section>'''

    toc = _sheet(f'''{_head("目录", "CONTENTS", "从需求理解到媒介执行与合同要点")}
      <div class="toc">
        <div><span>01</span><b>项目理解与策略</b><em>需求、目标人群、媒介角色</em></div>
        <div><span>02</span><b>媒介方案与覆盖</b><em>公交/地铁线路、点位与示意地图</em></div>
        <div><span>03</span><b>排期与执行</b><em>上刊、监测、雨备与补偿</em></div>
        <div><span>04</span><b>投资与报价</b><em>刊例、折扣、赠媒与预算</em></div>
        <div><span>05</span><b>效果预估与校验</b><em>曝光、Reach、CPM 与自检</em></div>
        <div><span>06</span><b>合同与签约要点</b><em>直客 / 4A 签约路径与关键条款</em></div>
      </div>
      <div class="about">
        <h3>关于新云</h3>
        <p>上海新云传媒股份有限公司成立于 1997 年，深耕城市核心商圈与交通出行场景，提供公交、地铁、户外等媒体资源与品牌营销服务。本提案由新云媒介提案台基于确定性引擎生成，媒体库存来自红豆广告媒体管理系统，线路几何来自新云 AI线路。</p>
      </div>''', "plain", run_id, data_version)

    section1 = _sheet(f'''{_head("01", "项目理解与策略", "从客户目标到人群、交通与媒介角色")}
      <div class="kpi-row">
        <div><span>项目预算</span><b>{_e(budget)}<small>万</small></b></div>
        <div><span>投放周期</span><b>{_e(weeks)}<small>周</small></b></div>
        <div><span>付费单元</span><b>{_e(summary.get("bus_units", 0) + summary.get("metro_units", 0))}<small>个</small></b></div>
        <div><span>效果预估</span><b>{_num((effects.get("impressions") or 0) / 10000, 1)}<small>万人次</small></b></div>
      </div>
      <div class="hyp">{hyp_rows}</div>
      <div class="quote-line">{_e(hyp.get("one_liner") or "以社区家庭与亲子出行为核心，公交做广度、地铁做心智。" )}</div>
      <div class="two">
        <div class="card"><h3>策略主线</h3><p>{_e(strategy.get("one_liner") or "以场馆为核心，按人群与出行轨迹配置公交+地铁组合。")}</p></div>
        <div class="card"><h3>人群与交通</h3><p>{_e((strategy.get("audience") or {}).get("primary") or "亲子家庭")}；{_e((strategy.get("transport") or {}).get("note") or "地铁+公交组合覆盖。")}</p></div>
      </div>
      <div class="roles">{roles}</div>''', "", run_id, data_version)

    section2 = _sheet(f'''{_head("02", "媒介方案与覆盖", "公交车身 + 地铁出入口 · 真实库存点位")}
      <div class="map-wrap">{_svg_map(plan)}</div>
      <div class="map-legend"><span><i class="bus"></i>公交线路</span><span><i class="metro"></i>地铁线路</span><span><i class="point"></i>选中点位</span><span>场馆 ◆</span></div>
      <div class="two">
        <div class="card"><h3>媒体配比</h3><div class="mix"><span style="width:{max(0, min(100, bus_pct * 100)):.1f}%"></span><i style="width:{max(0, min(100, metro_pct * 100)):.1f}%"></i></div><p>公交 {_pct(bus_pct)} · 地铁 {_pct(metro_pct)}（按折后媒体费）</p></div>
        <div class="card"><h3>规模</h3><p>公交 {_e(summary.get("bus_lines", 0))} 条 / {_e(summary.get("bus_units", 0))} 辆；地铁 {_e(summary.get("metro_stations", 0))} 站 / {_e(summary.get("metro_units", 0))} 口；总付费单元 {_e(summary.get("bus_units", 0) + summary.get("metro_units", 0))}。</p></div>
      </div>
      <p class="note">示意地图使用方案中的新云 AI线路 2023-05 轨迹快照（公交/地铁）与选中地铁口；仅用于可视化，不参与报价、库存、Reach 或评分。</p>''', "", run_id, data_version)

    section3 = _sheet(f'''{_head("02", "媒介线路与点位", f"公交 {len(bus)} 条 · 地铁 {len(metro)} 个出入口；展示金额优先项")}
      <h3>公交车身 · 金额前 {min(16, len(bus))} 条</h3>
      {_table(["线路/形式", "等级", "区县", "可售", "折后(万)"], bus_rows, "compact")}
      <h3>地铁出入口 · 金额前 {min(10, len(metro))} 个</h3>
      {_table(["站点/出入口", "等级", "区县", "可售", "折后(万)"], metro_rows, "compact")}
      <p class="note">完整点位、评分分解、选点理由与替代项见在线结果页。线路几何状态：公交 {_e(len(routes_bus))} 条 / 地铁 {_e(len(routes_metro))} 条（新云 AI线路 · 2023-05 快照）。</p>''', "", run_id, data_version)

    section4 = _sheet(f'''{_head("03", "排期与执行", "施工、上刊、监测与补刊承诺")}
      <h3>阶段排期</h3>
      {_table(["阶段", "责任方", "日期"], phase_rows, "compact")}
      <h3>安装批次</h3>
      {_table(["批次", "时间", "媒体", "单元", "雨备"], batch_rows, "compact")}
      <div class="two">
        <div class="card"><h3>夜间产能</h3><p>公交 {_e(nc.get("bus_per_night", "—"))} 辆 / 夜；地铁 {_e(nc.get("metro_per_night", "—"))} 口 / 夜；施工 {_e(nc.get("nights", "—"))} 夜，雨备 {_e(nc.get("rain_buffer_nights", "—"))} 夜。</p></div>
        <div class="card"><h3>监测与补偿</h3><p>上刊 / 下刊：{_e(schedule.get("go_live", "—"))} → {_e(schedule.get("take_down", "—"))}；{_e(mon.get("name") or "上刊监测")} · {_e(mon.get("sla") or mon.get("due") or "以合同为准")}；{_e((schedule.get("compensation") or {}).get("rule") or "误一补二")}。</p></div>
      </div>''', "", run_id, data_version)

    section5 = _sheet(f'''{_head("04", "投资与报价", "刊例 → 折扣 → 折后媒体费 → 制作费 → 应付总价")}
      <div class="quote-grid">
        <div class="card">
          {_table(["项目", "金额/比例"], [["刊例总额 (万)", _num(quote.get("rate_card_total_wan"), 2)], ["折扣", _e((quote.get("discount_tier") or {}).get("label") or _pct(quote.get("discount")))], ["折后媒体费 (万)", _num(quote.get("media_net_wan"), 2)], ["制作费 (万)", _num(quote.get("production_wan"), 2)], ["4A 服务费 (万)", _num(quote.get("agency_fee_wan"), 2)], ["应付总价 (万)", _num(quote.get("total_paid_wan"), 2)]], "compact")}
        </div>
        <div class="card">
          <h3>预算使用</h3><p class="big">{_e(_num(revenue, 2))} <small>万 / {_e(budget)} 万</small></p>
          <p>使用率 {_pct(summary.get("budget_utilization") if summary.get("budget_utilization") is not None else quote.get("budget_utilization"))}；余量 {_num(quote.get("budget_slack_wan"), 2)} 万。</p>
          <p>逐行分摊：{[('通过' if (quote.get('allocation_check') or {}).get('passed') else '待核对')][0]}；误差 {_num((quote.get('allocation_check') or {}).get('diff'), 2)} 万。</p>
          <p class="note">赠媒：{gift}（等值，不计付费 KPI）。</p>
        </div>
      </div>
      <p class="note">以上金额来自确定性引擎报价；制作费按 {_e(((quote.get("notes") or [None])[0]) or "合同约定")}；正式价格以双方签署合同为准。</p>''', "", run_id, data_version)

    section6 = _sheet(f'''{_head("05", "效果预估与校验", "曝光/GRP/Reach/Frequency/CPM 为模型估算")}
      <div class="kpi-row">
        <div><span>有效曝光</span><b>{_num((effects.get("impressions") or 0) / 10000, 1)}<small>万人次</small></b></div>
        <div><span>Reach</span><b>{_pct(effects.get("reach_pct") or effects.get("reach"))}</b></div>
        <div><span>Frequency</span><b>{_num(effects.get("frequency"), 1)}</b></div>
        <div><span>CPM</span><b>{_num(effects.get("cpm_yuan"), 2)}<small>元</small></b></div>
      </div>
      <div class="two">
        <div class="card"><h3>分媒体归因</h3>{_table(["媒体", "曝光占比", "CPM(元)"], [[("公交" if m.get("media") == "bus" else "地铁"), _pct(m.get("share")), _num(m.get("cpm_yuan"), 1)] for m in effects.get("by_media") or []], "compact")}</div>
        <div class="card"><h3>模型校验</h3><p>{_e(passed)} / {_e(len(checks))} 项检查通过；{("存在 blocker，请回结果页复核" if any((not c.get("passed") and c.get("level") == "blocker") for c in checks) else "无 blocker")}。</p><div class="checks">{checks_html}</div></div>
      </div>
      {elasticity_html}
      <p class="note">已知局限：{_e("；".join(limitations[:4]) or "曝光/触达为估算；折扣档位待赞助方确认；POI/公交几何为近似示意。")}</p>''', "", run_id, data_version)

    section7 = _sheet(f'''{_head("06", "合同与签约要点", f"签约路径：{contract_type}")}
      {_table(["签约要素", "内容"], [
        ["甲方", _e(venue) + "（以实际签约主体为准）"],
        ["乙方", "上海新云传媒股份有限公司"],
        ["媒体形式", _e(media)],
        ["发布期限", f"{_e(start)} → {_e(end)}"],
        ["合同金额", f"{_num(revenue, 2)} 万元（含制作费 {_num(quote.get('production_wan'), 2)} 万元）"],
        ["发票", "增值税专用发票，税率 6%（按国家当期政策）"],
        ["争议", "乙方所在地（上海市浦东新区）法院"],
      ], "compact")}
      <div class="clauses">{clause_html}</div>
      <p class="note">本页为提案阶段的合同要点模板，正式条款以双方签署的《{_e(contract_type)}》为准；直客/4A 的合同主体、付款比例、施工窗口与验收标准在签约时确认。</p>''', "", run_id, data_version)

    section8 = _sheet(f'''{_head("附录", "数据来源、版本与声明", "本提案的每个数字都可回溯到 run payload")}
      {_table(["项目", "内容"], [
        ["run_id", _e(run_id)], ["数据版本", _e(data_version)], ["库存快照", _e(str(inventory_ts).replace("T", " ")[:16])],
        ["生成日期", _e(generated)], ["数据来源", _e(sources)],
        ["线路几何", f"公交 {_e(len(routes_bus))} 条 / 地铁 {_e(len(routes_metro))} 条；{_e(rstatus.get('status') or '—')}；2023-05 快照"],
        ["线路摘要", _e(route_lines)],
      ], "compact")}
      <div class="disclaimer"><b>估算声明</b><p>曝光、GRP、Reach、Frequency、CPM 为模型估算，非实测触达；不承诺入园人数、销量或财务回报。公交/地铁线路几何为 2023-05 新云 AI线路近似轨迹，仅用于可视化，不参与报价、库存、Reach 或评分。数据缺失或降级时，提案页与 PDF 均显式标注，不静默换月、不伪造线路。</p></div>
      <div class="sign"><div><span>甲方（客户）</span><i></i><small>签署人 / 日期</small></div><div><span>乙方（新云传媒）</span><i></i><small>签署人 / 日期</small></div></div>
      <p class="note">提案生成：新云媒介提案台 · {_e(generated)} · {_e(run_id)}</p>''', "", run_id, data_version)

    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>投放提案 · {_e(venue)}</title>
<style>{CSS}</style></head><body>{cover}{toc}{section1}{section2}{section3}{section4}{section5}{section6}{section7}{section8}</body></html>'''


CSS = r'''
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #fff; color: #1c1e1a; font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif; font-size: 9.6pt; line-height: 1.6; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.sheet { width: 210mm; height: 297mm; padding: 16mm 15mm 13mm; background: #fbf8f2; position: relative; overflow: hidden; page-break-after: always; }
.sheet:last-child { page-break-after: auto; }
.cover { padding: 0; background: #171915; color: #f5f0e7; }
.cover-top { padding: 18mm 18mm 0; display: flex; justify-content: space-between; align-items: flex-end; }
.brand { font-size: 22pt; font-weight: 800; letter-spacing: .12em; color: #f5f0e7; }
.brand span { color: #c53a30; margin-left: 8px; font-weight: 400; }
.brand-cn { font-size: 8.5pt; letter-spacing: .18em; color: #b9b3a7; }
.cover-main { padding: 38mm 18mm 0; }
.kicker { font-size: 8pt; letter-spacing: .24em; color: #c53a30; font-weight: 700; }
.cover h1 { margin: 8mm 0 6mm; font-size: 34pt; line-height: 1.18; font-weight: 700; letter-spacing: -.02em; }
.cover-client { font-size: 15pt; color: #e6dfd2; margin: 0 0 8mm; }
.cover-rule { width: 30mm; height: 2px; background: #c53a30; margin-bottom: 7mm; }
.cover-meta { font-size: 10pt; line-height: 2; color: #cfc8bb; }
.cover-bottom { position: absolute; left: 18mm; right: 18mm; bottom: 14mm; display: flex; justify-content: space-between; font-size: 7.5pt; letter-spacing: .08em; color: #8e897f; border-top: 1px solid #353830; padding-top: 4mm; }
.sec-head { display: flex; gap: 6mm; align-items: flex-start; margin-bottom: 7mm; border-bottom: 1px solid #d9d1c3; padding-bottom: 4mm; }
.sec-no { font-size: 22pt; font-weight: 700; color: #c53a30; line-height: 1; min-width: 14mm; }
.sec-head h2 { margin: 0; font-size: 20pt; letter-spacing: -.02em; line-height: 1.2; }
.lead { margin: 2mm 0 0; color: #706b61; font-size: 9pt; }
.page-foot { position: absolute; left: 15mm; right: 15mm; bottom: 7mm; display: flex; justify-content: space-between; font-size: 7pt; color: #8f887b; border-top: 1px solid #ddd5c7; padding-top: 2.5mm; letter-spacing: .04em; }
.toc { display: grid; gap: 4mm; margin-top: 6mm; }
.toc > div { display: grid; grid-template-columns: 16mm 1fr auto; align-items: baseline; gap: 4mm; padding: 3mm 0; border-bottom: 1px solid #e2dacd; }
.toc span { font-size: 12pt; color: #c53a30; font-weight: 700; }
.toc b { font-size: 12pt; }
.toc em { font-style: normal; color: #827b6e; font-size: 8.5pt; }
.about { margin-top: 10mm; background: #f0e9dc; padding: 6mm; border-left: 3px solid #c53a30; }
h3 { font-size: 10.5pt; margin: 5mm 0 2.5mm; color: #24271f; }
h3:first-child { margin-top: 0; }
p { margin: 2mm 0; }
.kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 3mm; margin: 4mm 0 6mm; }
.kpi-row > div { background: #fffdf8; border: 1px solid #e0d7c8; padding: 4mm; border-radius: 2mm; }
.kpi-row span { display: block; font-size: 8pt; color: #7d7669; margin-bottom: 2mm; }
.kpi-row b { font-size: 17pt; color: #1c1e1a; font-weight: 700; }
.kpi-row small { font-size: 8pt; color: #7d7669; font-weight: 400; margin-left: 1mm; }
.hyp { display: grid; grid-template-columns: 1fr 1fr; gap: 0 7mm; margin-top: 2mm; }
.hyp-item { display: grid; grid-template-columns: 9mm 1fr; gap: 3mm; padding: 3mm 0; border-top: 1px solid #e0d7c8; }
.hyp-item > span { color: #c53a30; font-weight: 700; font-size: 8.5pt; }
.hyp-item b { display: block; font-size: 8.5pt; color: #7d7669; font-weight: 500; }
.hyp-item p { margin: .8mm 0 0; font-size: 9pt; }
.quote-line { margin: 5mm 0; background: #f0e9dc; padding: 4mm 5mm; border-left: 3px solid #c53a30; font-size: 10pt; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 5mm; margin-top: 4mm; }
.card { background: #fffdf8; border: 1px solid #e0d7c8; padding: 4mm 5mm; border-radius: 2mm; }
.card p { font-size: 9pt; color: #4c4a42; }
.roles { display: grid; gap: 2mm; margin-top: 5mm; }
.role { display: grid; grid-template-columns: 8mm 1fr auto; gap: 3mm; align-items: center; border-top: 1px solid #e0d7c8; padding-top: 2.5mm; }
.role-mark { width: 6mm; height: 6mm; display: grid; place-items: center; background: #2e5b44; color: #fff; border-radius: 1.2mm; font-size: 7pt; }
.role small { color: #7d7669; font-size: 8pt; }
.tbl { width: 100%; border-collapse: collapse; font-size: 8.2pt; }
.tbl th { text-align: left; color: #7d7669; font-weight: 500; font-size: 7.6pt; padding: 2mm 2mm; border-bottom: 1px solid #bdb4a5; white-space: nowrap; }
.tbl td { padding: 1.8mm 2mm; border-bottom: 1px solid #e4dccd; }
.tbl.compact td, .tbl.compact th { padding: 1.45mm 1.7mm; }
.map-wrap { border: 1px solid #e0d7c8; background: #f5f1e8; padding: 2mm; }
.map-svg { width: 100%; height: auto; display: block; }
.districts path { fill: #f1ebe0; stroke: #d4cbba; stroke-width: 1; }
.bus-line { fill: none; stroke: #2e5b44; stroke-width: 1.6; opacity: .62; }
.metro-line { fill: none; stroke: #a8794a; stroke-width: 1.8; stroke-dasharray: 5 3; opacity: .85; }
.metro-points .point { fill: #c53a30; stroke: #fff; stroke-width: 1; }
.venue { fill: #c53a30; stroke: #fff; stroke-width: 1.2; }
.map-legend { display: flex; gap: 6mm; flex-wrap: wrap; font-size: 8pt; color: #6f695e; margin: 2mm 0 0; }
.map-legend i { display: inline-block; width: 8mm; height: 1.2mm; vertical-align: middle; margin-right: 1.5mm; }
.map-legend i.bus { background: #2e5b44; } .map-legend i.metro { background: #a8794a; } .map-legend i.point { width: 3mm; height: 3mm; border-radius: 50%; background: #c53a30; }
.mix { display: flex; height: 5mm; background: #e7dfd1; border-radius: 1mm; overflow: hidden; margin: 2mm 0 1mm; }
.mix span { background: #2e5b44; } .mix i { background: #a8794a; }
.note { color: #756e61; font-size: 7.8pt; line-height: 1.6; }
.checks { display: flex; flex-wrap: wrap; gap: 1.5mm; margin-top: 2mm; }
.check { font-size: 7pt; padding: 1mm 1.6mm; background: #f1ece2; border-radius: 1mm; color: #5d574c; }
.check.ok::before { content: "✓ "; color: #2e5b44; } .check.bad::before { content: "! "; color: #c53a30; }
.quote-grid { display: grid; grid-template-columns: 1.15fr .85fr; gap: 5mm; }
.big { font-size: 18pt; font-weight: 700; margin: 2mm 0; }
.big small { font-size: 9pt; font-weight: 400; color: #7d7669; }
.clauses { margin-top: 4mm; display: grid; grid-template-columns: 1fr 1fr; gap: 3mm 6mm; }
.clause { border-top: 1px solid #e0d7c8; padding-top: 2mm; }
.clause b { font-size: 8.5pt; color: #c53a30; }
.clause p { margin: 1mm 0 0; font-size: 7.8pt; color: #4c4a42; line-height: 1.5; }
.disclaimer { background: #fffdf8; border: 1px solid #e0d7c8; padding: 4mm 5mm; margin-top: 5mm; }
.sign { display: grid; grid-template-columns: 1fr 1fr; gap: 12mm; margin-top: 8mm; }
.sign span { font-size: 9pt; font-weight: 600; } .sign i { display: block; border-bottom: 1px solid #9d9486; height: 12mm; margin: 3mm 0 2mm; } .sign small { color: #7d7669; font-size: 8pt; }
'''


def build_html(run: Dict[str, Any]) -> str:
    return _build_html(run)


def generate_proposal_pdf(run: Dict[str, Any]) -> Path:
    run_id = re.sub(r"[^A-Za-z0-9_-]+", "_", str(run.get("run_id") or "proposal"))
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = EXPORT_DIR / f"{run_id}.html"
    pdf_path = EXPORT_DIR / f"{run_id}.pdf"
    if pdf_path.is_file() and pdf_path.stat().st_size > 1000 and not os.environ.get("PROPOSAL_PDF_FORCE"):
        for target in (PUBLIC_DIR, DIST_DIR):
            try:
                target.mkdir(parents=True, exist_ok=True)
                dest = target / f"{run_id}.pdf"
                if not dest.is_file():
                    shutil.copyfile(pdf_path, dest)
            except OSError:
                pass
        return pdf_path
    html_path.write_text(_build_html(run), encoding="utf-8")
    chrome = _chrome()
    if not chrome:
        raise RuntimeError("未找到 Chrome/Edge，无法打印 PDF")
    tmp_pdf = EXPORT_DIR / f".{run_id}.pdf.tmp"
    if tmp_pdf.exists():
        tmp_pdf.unlink()
    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
        "--no-pdf-header-footer", "--print-to-pdf-no-header",
        f"--print-to-pdf={tmp_pdf}", "--virtual-time-budget=4000",
        html_path.as_uri(),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if not tmp_pdf.exists() or tmp_pdf.stat().st_size < 1000:
        raise RuntimeError(f"PDF 打印失败：{(proc.stderr or proc.stdout or '')[:300]}")
    os.replace(tmp_pdf, pdf_path)
    for target in (PUBLIC_DIR, DIST_DIR):
        try:
            target.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pdf_path, target / f"{run_id}.pdf")
        except OSError:
            pass
    return pdf_path


__all__ = ["build_html", "generate_proposal_pdf"]


if __name__ == "__main__":
    import sys
    from agent.orchestration import get_run

    run_id = sys.argv[1] if len(sys.argv) > 1 else ""
    run = get_run(run_id) if run_id else None
    if not run:
        print("usage: python -m server.proposal_pdf <run_id>")
        raise SystemExit(2)
    print(generate_proposal_pdf(run))
