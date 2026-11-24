# -*- coding: utf-8 -*-
"""PDF 模板公共工具：数据抽取、格式化、人民币大写、品牌素材 URI、上海覆盖地图 SVG、Chrome 无头打印。"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
DISTRICTS_PATH = PROJECT_ROOT / "data" / "geo" / "shanghai_districts.geojson"

DOC_SPECS: Dict[str, Dict[str, str]] = {
    "proposal": {
        "key": "proposal",
        "title": "销售提案方案（PPT 版）",
        "short_label": "下载销售提案 PDF",
        "source_sample": "05-历史销售提案样本/饮用水客户-销售提案样本.pdf",
        "filename_prefix": "proposal",
        "orientation": "landscape-16x9",
    },
    "contract_direct": {
        "key": "contract_direct",
        "title": "直客广告发布合同",
        "short_label": "下载直客合同 PDF",
        "source_sample": "03-合同三份-脱敏版/M3-直客合同-脱敏版.pdf",
        "filename_prefix": "contract-direct",
        "orientation": "portrait-a4",
    },
    "contract_4a_order": {
        "key": "contract_4a_order",
        "title": "4A 户外排期表（订单）",
        "short_label": "下载 4A 排期订单 PDF",
        "source_sample": "03-合同三份-脱敏版/M3-4A订单-脱敏版.pdf",
        "filename_prefix": "contract-4a-order",
        "orientation": "landscape-a4",
    },
    "contract_4a_framework": {
        "key": "contract_4a_framework",
        "title": "4A 年度框架合同书",
        "short_label": "下载 4A 框架合同 PDF",
        "source_sample": "03-合同三份-脱敏版/M3-4A框架-脱敏版.pdf",
        "filename_prefix": "contract-4a-framework",
        "orientation": "portrait-a4",
    },
}

VALID_DOC_TYPES = tuple(DOC_SPECS.keys())

CHROME_CANDIDATES = [
    os.environ.get("CHROME_PATH"),
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]


def find_chrome() -> Optional[str]:
    for path in CHROME_CANDIDATES:
        if path and Path(path).is_file():
            return str(path)
    return None


def asset_uri(name: str) -> str:
    """返回本地模板素材的 file:// URI（Chrome 无头打印直接读取，速度快且体积小）。"""
    p = ASSETS_DIR / name
    if p.is_file():
        return p.resolve().as_uri()
    return ""


def e(value: Any, fallback: str = "—") -> str:
    if value is None or value == "":
        return fallback
    return html.escape(str(value))


def num(value: Any, digits: int = 0) -> str:
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def pct(value: Any, digits: int = 1) -> str:
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("%"):
            return s
    try:
        v = float(value)
        if abs(v) <= 1.0:
            v *= 100.0
        return f"{v:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def rmb_upper(amount_yuan: float) -> str:
    """将人民币金额（元）转为中文大写，供合同总价使用。"""
    try:
        val = round(float(amount_yuan), 2)
    except (TypeError, ValueError):
        return "零元整"
    if val <= 0:
        return "零元整"
    digits = "零壹贰叁肆伍陆柒捌玖"
    units = ["", "拾", "佰", "仟"]
    big_units = ["", "万", "亿", "兆"]
    int_part = int(val)
    frac_part = round((val - int_part) * 100)
    jiao = frac_part // 10
    fen = frac_part % 10

    if int_part == 0:
        int_str = "零"
    else:
        groups: List[str] = []
        idx = 0
        n = int_part
        while n > 0:
            g = n % 10000
            if g > 0:
                g_str = ""
                zero_flag = False
                for i in range(4):
                    d = (g // (10 ** i)) % 10
                    if d == 0:
                        if g_str and not zero_flag:
                            g_str = "零" + g_str
                            zero_flag = True
                    else:
                        g_str = digits[d] + units[i] + g_str
                        zero_flag = False
                groups.append(g_str + big_units[idx])
            else:
                if groups and not groups[-1].startswith("零"):
                    groups.append("零")
            n //= 10000
            idx += 1
        int_str = "".join(reversed(groups)).strip("零")
        int_str = re.sub(r"零+", "零", int_str)

    if jiao == 0 and fen == 0:
        return f"{int_str}元整"
    out = f"{int_str}元"
    if jiao > 0:
        out += f"{digits[jiao]}角"
    elif fen > 0:
        out += "零"
    if fen > 0:
        out += f"{digits[fen]}分"
    return out


def extract_run_context(run: Dict[str, Any]) -> Dict[str, Any]:
    """统一抽取 run 中的确定性字段，供 4 套模板共享，不在模板层重算核心报价/指标。"""
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

    bus = [x for x in (body.get("bus") or []) if isinstance(x, dict) and x.get("status") != "replaced"]
    metro = [x for x in (body.get("metro") or []) if isinstance(x, dict) and x.get("status") != "replaced"]
    bus_sorted = sorted(bus, key=lambda x: (-float(x.get("total_wan") or 0), str(x.get("line") or "")))
    metro_sorted = sorted(metro, key=lambda x: (-float(x.get("total_wan") or 0), str(x.get("station") or "")))

    by_line_imp: Dict[str, float] = {}
    for row in effects.get("by_line") or []:
        if isinstance(row, dict) and row.get("id"):
            try:
                by_line_imp[str(row["id"])] = float(row.get("impressions") or 0)
            except (TypeError, ValueError):
                pass

    run_id = str(run.get("run_id") or "proposal")
    venue_name = str(inputs.get("venue_name") or (plan.get("venue") or {}).get("name") or "目标品牌项目")
    industry = str(inputs.get("industry") or request.get("industry") or "乐园")
    start_date = str(inputs.get("start_date") or request.get("start_date") or "2027-07-01")
    end_date = str(inputs.get("end_date") or schedule.get("take_down") or "2027-08-25")
    weeks = inputs.get("weeks") or request.get("weeks") or 8
    months = inputs.get("months") or max(1, round(float(weeks) / 4.0))
    total_days = int(schedule.get("total_days") or (effects.get("parameters") or {}).get("days") or int(weeks) * 7)
    customer_type = str(inputs.get("customer_type") or request.get("customer_type") or "direct").lower()
    customer_label = inputs.get("customer_type_label") or ("4A 代理" if customer_type == "4a" else "直客")
    media_list = list(inputs.get("media") or request.get("media") or [])
    if not media_list:
        if bus:
            media_list.append("bus")
        if metro:
            media_list.append("metro")
    media_cn = " + ".join("公交车身" if m == "bus" else "地铁出入口" for m in media_list) or "户外媒体"

    year_m = re.match(r"(\d{4})", start_date)
    campaign_year = int(year_m.group(1)) if year_m else 2027
    month_m = re.match(r"(\d{4})-(\d{2})", start_date)
    planned_month = f"{int(month_m.group(2))}月" if month_m else "7月"
    if end_date[:7] != start_date[:7] and re.match(r"\d{4}-\d{2}", end_date):
        planned_month = f"{int(start_date[5:7])}月-{int(end_date[5:7])}月"

    budget_wan = float(inputs.get("budget_wan") or request.get("budget_wan") or quote.get("budget_wan") or 0)
    total_paid_wan = float(quote.get("total_paid_wan") or 0)
    rate_card_wan = float(quote.get("rate_card_total_wan") or 0)
    media_net_wan = float(quote.get("media_net_wan") or 0)
    production_wan = float(quote.get("production_wan") or 0)
    agency_fee_wan = float(quote.get("agency_fee_wan") or 0)
    gift_wan = float(quote.get("gift_wan") or 0)
    discount = float(quote.get("discount") or 1.0)

    return {
        "run": run,
        "run_id": run_id,
        "plan": plan,
        "inputs": inputs,
        "request": request,
        "meta": meta,
        "body": body,
        "summary": summary,
        "hyp": hyp,
        "strategy": strategy,
        "quote": quote,
        "effects": effects,
        "schedule": schedule,
        "validation": validation,
        "coverage": coverage,
        "layers": layers,
        "elasticity": run.get("elasticity") or plan.get("elasticity") or {},
        "routes_bus": layers.get("bus_routes") or [],
        "routes_metro": layers.get("metro_routes") or [],
        "routes_meta": (run.get("data") or {}).get("routes") or {},
        "bus": bus_sorted,
        "metro": metro_sorted,
        "by_line_imp": by_line_imp,
        "venue_name": venue_name,
        "industry": industry,
        "start_date": start_date,
        "end_date": end_date,
        "weeks": weeks,
        "months": months,
        "total_days": total_days,
        "campaign_year": campaign_year,
        "planned_month": planned_month,
        "customer_type": customer_type,
        "customer_label": customer_label,
        "media_list": media_list,
        "media_cn": media_cn,
        "budget_wan": budget_wan,
        "total_paid_wan": total_paid_wan,
        "total_paid_yuan": round(total_paid_wan * 10000.0, 2),
        "rate_card_wan": rate_card_wan,
        "media_net_wan": media_net_wan,
        "production_wan": production_wan,
        "agency_fee_wan": agency_fee_wan,
        "gift_wan": gift_wan,
        "discount": discount,
        "data_version": str(meta.get("data_version") or "—"),
        "inventory_ts": str(meta.get("inventory_ts") or "—").replace("T", " ")[:16],
        "generated_date": datetime.now().strftime("%Y-%m-%d"),
        "contract_no": f"XY-{campaign_year}-{run_id[:8].upper()}",
    }


@lru_cache(maxsize=1)
def _load_districts() -> List[Tuple[str, List[List[Tuple[float, float]]]]]:
    try:
        raw = json.loads(DISTRICTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: List[Tuple[str, List[List[Tuple[float, float]]]]] = []
    for feature in raw.get("features") or []:
        props = feature.get("properties") or {}
        name = str(props.get("name") or props.get("NAME") or "")
        geom = feature.get("geometry") or {}
        if geom.get("type") == "Polygon":
            rings = [[(float(p[0]), float(p[1])) for p in ring] for ring in (geom.get("coordinates") or [])]
            out.append((name, rings))
        elif geom.get("type") == "MultiPolygon":
            for poly in geom.get("coordinates") or []:
                rings = [[(float(p[0]), float(p[1])) for p in ring] for ring in poly]
                out.append((name, rings))
    return out


def build_coverage_map_svg(ctx: Dict[str, Any], width: float = 1120.0, height: float = 560.0) -> str:
    """高清晰上海覆盖矢量地图（参考历史提案样本 P12-14 风格，带区县名、彩色公交线、地铁线、地铁口与场馆）。"""
    districts = _load_districts()
    routes_bus = ctx["routes_bus"]
    routes_metro = ctx["routes_metro"]
    metro_points = ctx["metro"]
    venue = (ctx["plan"].get("venue") or {})
    vcoords = venue.get("coords") or {}

    # 聚焦上海主城区 + 选中线路与场馆包络盒
    focus_coords: List[Tuple[float, float]] = []
    for route in routes_bus + routes_metro:
        for p in (route.get("geometry") or {}).get("path") or []:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                focus_coords.append((float(p[0]), float(p[1])))
    for item in metro_points:
        p = (item.get("geo") or {}).get("coords") or {}
        if p.get("lng") is not None and p.get("lat") is not None:
            focus_coords.append((float(p["lng"]), float(p["lat"])))
    if vcoords.get("lng") is not None and vcoords.get("lat") is not None:
        focus_coords.append((float(vcoords["lng"]), float(vcoords["lat"])))

    if len(focus_coords) >= 2:
        min_lng = min(p[0] for p in focus_coords)
        max_lng = max(p[0] for p in focus_coords)
        min_lat = min(p[1] for p in focus_coords)
        max_lat = max(p[1] for p in focus_coords)
        # 扩展一些视角以展示完整上海城区脉络
        span_lng = max(0.24, (max_lng - min_lng) * 1.28)
        span_lat = max(0.18, (max_lat - min_lat) * 1.28)
        cx = (min_lng + max_lng) / 2.0
        cy = (min_lat + max_lat) / 2.0
        # 匹配画布宽高比（考虑上海纬度 cos(31.2°) ≈ 0.855）
        target_ratio = (width / height) / 0.855
        if span_lng / span_lat < target_ratio:
            span_lng = span_lat * target_ratio
        else:
            span_lat = span_lng / target_ratio
        min_lng, max_lng = cx - span_lng / 2.0, cx + span_lng / 2.0
        min_lat, max_lat = cy - span_lat / 2.0, cy + span_lat / 2.0
    else:
        min_lng, max_lng = 121.05, 121.92
        min_lat, max_lat = 30.82, 31.46

    def xy(lng: float, lat: float) -> Tuple[float, float]:
        x = (lng - min_lng) / (max_lng - min_lng) * width
        y = (max_lat - lat) / (max_lat - min_lat) * height
        return x, y

    district_paths: List[str] = []
    district_labels: List[str] = []
    seen_labels = set()
    for dname, rings in districts:
        parts: List[str] = []
        pts_all: List[Tuple[float, float]] = []
        for ring in rings:
            if len(ring) < 3:
                continue
            coords_xy = [xy(p[0], p[1]) for p in ring]
            pts_all.extend(coords_xy)
            parts.append("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in coords_xy) + " Z")
        if parts:
            district_paths.append(f'<path class="dist" d="{" ".join(parts)}"/>')
            if dname and dname not in seen_labels and pts_all:
                seen_labels.add(dname)
                ax = sum(p[0] for p in pts_all) / len(pts_all)
                ay = sum(p[1] for p in pts_all) / len(pts_all)
                if 20 < ax < width - 20 and 16 < ay < height - 16:
                    district_labels.append(f'<text class="dist-lbl" x="{ax:.1f}" y="{ay:.1f}">{e(dname)}</text>')

    palette = ["#c83e37", "#7e4fa3", "#2b6cb0", "#b87a3d", "#2d7a59", "#c05621", "#5a67d8", "#97266d"]
    bus_svg: List[str] = []
    label_svg: List[str] = []
    placed_labels: List[Tuple[float, float]] = []
    for idx, route in enumerate(routes_bus):
        path = (route.get("geometry") or {}).get("path") or []
        if len(path) < 2:
            continue
        step = max(1, len(path) // 130)
        sampled = path[::step]
        if sampled[-1] != path[-1]:
            sampled.append(path[-1])
        pts = [xy(float(p[0]), float(p[1])) for p in sampled]
        color = palette[idx % len(palette)]
        pts_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        bus_svg.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.1" stroke-opacity="0.82" points="{pts_str}"/>')
        # 线路标签（类似历史样本里的白底红框小标签）
        mid = pts[len(pts) // 2]
        if 35 < mid[0] < width - 45 and 20 < mid[1] < height - 20 and len(placed_labels) < 36:
            if all((mid[0] - px) ** 2 + (mid[1] - py) ** 2 > 1400 for px, py in placed_labels):
                placed_labels.append(mid)
                lbl = str(route.get("line") or route.get("lineName") or "").replace("路", "")
                bw = max(24, len(lbl) * 7.5 + 8)
                label_svg.append(
                    f'<g transform="translate({mid[0] - bw/2:.1f},{mid[1] - 8:.1f})">'
                    f'<rect width="{bw:.1f}" height="15" rx="2" fill="#ffffff" fill-opacity="0.92" stroke="{color}" stroke-width="0.9"/>'
                    f'<text x="{bw/2:.1f}" y="10.8" text-anchor="middle" font-size="8.5" font-weight="700" fill="#222">{e(lbl)}</text></g>'
                )

    metro_svg: List[str] = []
    for route in routes_metro:
        path = (route.get("geometry") or {}).get("path") or []
        if len(path) < 2:
            continue
        step = max(1, len(path) // 130)
        sampled = path[::step]
        pts = [xy(float(p[0]), float(p[1])) for p in sampled]
        pts_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        metro_svg.append(f'<polyline fill="none" stroke="#c28d57" stroke-width="2.4" stroke-dasharray="6 3" stroke-opacity="0.92" points="{pts_str}"/>')

    point_svg: List[str] = []
    for item in metro_points:
        p = (item.get("geo") or {}).get("coords") or {}
        if p.get("lng") is None or p.get("lat") is None:
            continue
        px, py = xy(float(p["lng"]), float(p["lat"]))
        if 0 <= px <= width and 0 <= py <= height:
            point_svg.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4.8" fill="#b42322" stroke="#fff" stroke-width="1.4"/>')

    venue_svg = ""
    if vcoords.get("lng") is not None and vcoords.get("lat") is not None:
        vx, vy = xy(float(vcoords["lng"]), float(vcoords["lat"]))
        vlabel = ctx["venue_name"]
        vw = max(72, len(vlabel) * 10 + 18)
        venue_svg = (
            f'<g>'
            f'<circle cx="{vx:.1f}" cy="{vy:.1f}" r="18" fill="#c28d57" fill-opacity="0.22" stroke="#c28d57" stroke-width="1.4"/>'
            f'<polygon points="{vx:.1f},{vy-9:.1f} {vx+9:.1f},{vy:.1f} {vx:.1f},{vy+9:.1f} {vx-9:.1f},{vy:.1f}" fill="#b42322" stroke="#fff" stroke-width="1.6"/>'
            f'<rect x="{vx - vw/2:.1f}" y="{vy + 12:.1f}" width="{vw:.1f}" height="18" rx="3" fill="#1c1c1c" fill-opacity="0.9"/>'
            f'<text x="{vx:.1f}" y="{vy + 24.5:.1f}" text-anchor="middle" font-size="10" font-weight="700" fill="#f7e3c6">{e(vlabel)}</text>'
            f'</g>'
        )

    return f'''<svg class="cov-map" viewBox="0 0 {int(width)} {int(height)}" role="img" aria-label="上海媒体覆盖地图">
  <rect width="{int(width)}" height="{int(height)}" fill="#dcebf7"/>
  <g>{"".join(district_paths)}</g>
  <g>{"".join(district_labels)}</g>
  <g>{"".join(metro_svg)}</g>
  <g>{"".join(bus_svg)}</g>
  <g>{"".join(point_svg)}</g>
  <g>{"".join(label_svg)}</g>
  {venue_svg}
</svg>'''


def render_html_to_pdf(html_content: str, html_path: Path, pdf_path: Path) -> Path:
    """使用本机 Chrome/Edge 无头打印 HTML 为精确分页的 PDF。"""
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("未找到 Chrome/Edge，无法打印 PDF")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html_content, encoding="utf-8")
    tmp_pdf = pdf_path.with_name(f".{pdf_path.name}.tmp")
    if tmp_pdf.exists():
        tmp_pdf.unlink()
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--allow-file-access-from-files",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        f"--print-to-pdf={tmp_pdf}",
        "--virtual-time-budget=5000",
        html_path.resolve().as_uri(),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if not tmp_pdf.exists() or tmp_pdf.stat().st_size < 1000:
        raise RuntimeError(f"PDF 打印失败：{(proc.stderr or proc.stdout or '')[:300]}")
    os.replace(tmp_pdf, pdf_path)
    return pdf_path
