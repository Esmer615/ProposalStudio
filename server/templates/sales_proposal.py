# -*- coding: utf-8 -*-
"""模板 1：历史销售提案样本（16:9 横版 FLAIR MEDIA 销售提案 PPT 式 PDF）。

依据：`docs/03-合同三份-脱敏版等9个文件/05-历史销售提案样本/饮用水客户-销售提案样本.pdf`
严格复刻原版 16:9 幻灯片视觉体系（黑金封面、横纹白底目录/章节分隔、新云简介、企业优势六边形、
三大/七类户外媒体资源、巴士/地铁策略与方案覆盖地图、双栏线路甄选表、赠送媒体实景展示、
服务能力三栏卡片、黑金封底），并把本次 run 的真实确定性数据直接填入对应动态页。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

from .common import asset_uri, build_coverage_map_svg, e, extract_run_context, num, pct


def _slide_header(title: str, subtitle: str = "", show_logo: bool = True) -> str:
    logo = f'<img class="top-logo" src="{asset_uri("logo-red.png")}" alt="FLAIR MEDIA">' if show_logo else ""
    t_html = f'<span class="hdr-title">{e(title)}</span>' if title else ""
    sub = f'<span class="hdr-sub">{e(subtitle)}</span>' if subtitle else ""
    return f'''<div class="slide-hdr">
  <div class="hdr-left">
    <span class="hdr-line"></span>
    <span class="hdr-diamond-out"></span>
    <span class="hdr-diamond-in"></span>
    {t_html}
    {sub}
  </div>
  {logo}
</div>'''


def _divider_slide(num_str: str, title: str, img_file: str) -> str:
    return f'''<section class="slide divider">
  <div class="div-left">
    <img src="{asset_uri(img_file)}" alt="{e(title)}">
  </div>
  <div class="div-right">
    <img class="top-logo" src="{asset_uri("logo-red.png")}" alt="FLAIR MEDIA">
    <div class="div-text">
      <div class="div-no">{e(num_str)}</div>
      <div class="div-title">{e(title)}</div>
    </div>
  </div>
</section>'''


def _bus_table_slides(ctx: Dict[str, Any]) -> str:
    bus = ctx["bus"]
    if not bus:
        return ""
    by_line_imp = ctx["by_line_imp"]
    days = max(1, int(ctx["total_days"] or 14))
    summary = ctx["summary"]
    effects = ctx["effects"]
    bus_units = int(summary.get("bus_units") or sum(int(x.get("units") or 1) for x in bus))
    bus_imp = 0.0
    for m in effects.get("by_media") or []:
        if m.get("media") == "bus":
            bus_imp = float(m.get("impressions") or 0)
    if bus_imp <= 0:
        bus_imp = sum(by_line_imp.get(str(x.get("id") or ""), 0.0) for x in bus)
    daily_total = bus_imp / days
    monthly_total = daily_total * 30.0

    # 每页左右双栏，左栏最多 20 行、右栏最多 17 行（右栏底部留红框汇总）
    per_page = 36
    total_pages = max(1, math.ceil(len(bus) / per_page))
    slides: List[str] = []

    def _row_html(item: Dict[str, Any], include_city: bool = False, city_span: int = 0) -> str:
        line = str(item.get("line") or item.get("name") or "—")
        level = str(item.get("level") or "—")
        units = int(item.get("units") or 1)
        rate_yuan = float(item.get("unit_price_wan") or 0) * 10000.0
        prod_unit = (float(item.get("production_wan") or 0) * 10000.0) / max(1, units)
        item_imp = float(by_line_imp.get(str(item.get("id") or ""), 0.0))
        daily_per_unit_wan = (item_imp / days / max(1, units)) / 10000.0 if item_imp > 0 else 0.0
        monthly_per_unit_wan = daily_per_unit_wan * 30.0
        city_td = f'<td class="city-cell" rowspan="{city_span}">上海</td>' if include_city and city_span > 0 else ""
        return (
            f"<tr>{city_td}"
            f"<td>{e(line)}</td>"
            f"<td>{e(level)}</td>"
            f'<td class="qty">{units}</td>'
            f"<td>{num(rate_yuan, 0)}</td>"
            f"<td>{num(prod_unit, 0)}</td>"
            f"<td>{num(daily_per_unit_wan, 2) if daily_per_unit_wan > 0 else '—'}</td>"
            f"<td>{num(monthly_per_unit_wan, 1) if monthly_per_unit_wan > 0 else '—'}</td>"
            f"</tr>"
        )

    for p_idx in range(total_pages):
        chunk = bus[p_idx * per_page : (p_idx + 1) * per_page]
        split_at = min(20, max(1, math.ceil(len(chunk) * 0.54)))
        left_items = chunk[:split_at]
        right_items = chunk[split_at:]

        left_rows = "".join(
            _row_html(it, include_city=(i == 0), city_span=len(left_items))
            for i, it in enumerate(left_items)
        )
        right_rows = "".join(_row_html(it, include_city=False) for it in right_items)

        page_tag = f"（{p_idx + 1}/{total_pages}）" if total_pages > 1 else ""
        title = f"巴士媒体-线路甄选：{bus_units}辆公交车身线路，目标区域强势覆盖{page_tag}"

        summary_box = f'''<div class="reach-callout">
  <div><b>{bus_units}辆</b>公交车估算日触达人次约：<span>{num(daily_total, 0)} 人次</span></div>
  <div>估算月触达人次约：<span>{num(monthly_total, 0)} 人次</span>（周期有效曝光 {num(bus_imp / 10000.0, 1)} 万人次）</div>
</div>'''

        right_table = ""
        if right_items:
            right_table = f'''<table class="line-tbl">
  <thead>
    <tr>
      <th>线路</th><th>线路级别</th><th>投放数量<br>(辆)</th><th>媒体刊例<br>(元/辆/月)</th>
      <th>制作费<br>(元/辆)</th><th>日触达人次<br>(万/天/辆)</th><th>月触达人次<br>(万/月/辆)</th>
    </tr>
  </thead>
  <tbody>{right_rows}</tbody>
</table>'''

        slides.append(f'''<section class="slide lined">
  {_slide_header(title, show_logo=False)}
  <div class="dual-tables">
    <div class="col-left">
      <table class="line-tbl">
        <thead>
          <tr>
            <th>城市</th><th>线路</th><th>线路级别</th><th>投放数量<br>(辆)</th><th>媒体刊例<br>(元/辆/月)</th>
            <th>制作费<br>(元/辆)</th><th>日触达人次<br>(万/天/辆)</th><th>月触达人次<br>(万/月/辆)</th>
          </tr>
        </thead>
        <tbody>{left_rows}</tbody>
      </table>
    </div>
    <div class="col-right">
      {right_table}
      {summary_box}
    </div>
  </div>
</section>''')
    return "".join(slides)


def _metro_table_slides(ctx: Dict[str, Any]) -> str:
    metro = ctx["metro"]
    if not metro:
        return ""
    summary = ctx["summary"]
    effects = ctx["effects"]
    by_line_imp = ctx["by_line_imp"]
    days = max(1, int(ctx["total_days"] or 14))
    metro_units = int(summary.get("metro_units") or sum(int(x.get("units") or 1) for x in metro))
    metro_stations = int(summary.get("metro_stations") or len({x.get("station") for x in metro if x.get("station")}))
    metro_imp = 0.0
    for m in effects.get("by_media") or []:
        if m.get("media") == "metro":
            metro_imp = float(m.get("impressions") or 0)
    if metro_imp <= 0:
        metro_imp = sum(by_line_imp.get(str(x.get("id") or ""), 0.0) for x in metro)

    per_page = 34
    total_pages = max(1, math.ceil(len(metro) / per_page))
    slides: List[str] = []

    def _mrow(item: Dict[str, Any], include_city: bool = False, city_span: int = 0) -> str:
        station = str(item.get("station") or item.get("name") or "—")
        exit_no = str(item.get("exit") or "—")
        district = str(item.get("district") or "—")
        level = str(item.get("level") or "—")
        units = int(item.get("units") or 1)
        rate_yuan = float(item.get("unit_price_wan") or 0) * 10000.0
        prod_yuan = float(item.get("production_wan") or 0) * 10000.0
        item_imp = float(by_line_imp.get(str(item.get("id") or ""), 0.0))
        daily_wan = (item_imp / days / max(1, units)) / 10000.0 if item_imp > 0 else 0.0
        city_td = f'<td class="city-cell" rowspan="{city_span}">上海</td>' if include_city and city_span > 0 else ""
        return (
            f"<tr>{city_td}"
            f"<td>{e(station)}</td>"
            f"<td>{e(exit_no)}</td>"
            f"<td>{e(district)}</td>"
            f"<td>{e(level)}</td>"
            f'<td class="qty">{units}</td>'
            f"<td>{num(rate_yuan, 0)}</td>"
            f"<td>{num(prod_yuan, 0)}</td>"
            f"<td>{num(daily_wan, 2) if daily_wan > 0 else '—'}</td>"
            f"</tr>"
        )

    for p_idx in range(total_pages):
        chunk = metro[p_idx * per_page : (p_idx + 1) * per_page]
        if len(chunk) <= 18:
            left_items, right_items = chunk, []
        else:
            split_at = math.ceil(len(chunk) * 0.54)
            left_items, right_items = chunk[:split_at], chunk[split_at:]

        left_rows = "".join(_mrow(it, include_city=(i == 0), city_span=len(left_items)) for i, it in enumerate(left_items))
        right_rows = "".join(_mrow(it) for it in right_items)
        page_tag = f"（{p_idx + 1}/{total_pages}）" if total_pages > 1 else ""
        title = f"地铁媒体-出入口甄选：{metro_stations}座枢纽站点 · {metro_units}个核心出入口精准拦截{page_tag}"

        summary_box = f'''<div class="reach-callout">
  <div><b>{metro_stations}座站点 / {metro_units}个出入口</b> · 估算周期有效曝光：<span>{num(metro_imp / 10000.0, 1)} 万人次</span></div>
  <div>全方案综合 Reach：<span>{pct(effects.get("reach_pct") or effects.get("reach"))}</span> · 综合 CPM：<span>{num(effects.get("cpm_yuan"), 2)} 元</span></div>
</div>'''

        if right_items:
            body_html = f'''<div class="dual-tables">
  <div class="col-left">
    <table class="line-tbl">
      <thead><tr><th>城市</th><th>站点</th><th>出入口</th><th>区县</th><th>级别</th><th>数量</th><th>刊例(元/月)</th><th>制作费(元)</th><th>日触达(万)</th></tr></thead>
      <tbody>{left_rows}</tbody>
    </table>
  </div>
  <div class="col-right">
    <table class="line-tbl">
      <thead><tr><th>站点</th><th>出入口</th><th>区县</th><th>级别</th><th>数量</th><th>刊例(元/月)</th><th>制作费(元)</th><th>日触达(万)</th></tr></thead>
      <tbody>{right_rows}</tbody>
    </table>
    {summary_box}
  </div>
</div>'''
        else:
            body_html = f'''<div class="single-table-wrap">
  <table class="line-tbl line-tbl--wide">
    <thead><tr><th>城市</th><th>地铁站点</th><th>出入口</th><th>行政区</th><th>媒体级别</th><th>投放数量(口)</th><th>媒体刊例(元/口/月)</th><th>制作费(元/口)</th><th>日触达人次(万/天)</th></tr></thead>
    <tbody>{left_rows}</tbody>
  </table>
  {summary_box}
</div>'''

        slides.append(f'<section class="slide lined">{_slide_header(title, show_logo=False)}{body_html}</section>')
    return "".join(slides)


def build_sales_proposal_html(run: Dict[str, Any]) -> str:
    ctx = extract_run_context(run)
    venue = ctx["venue_name"]
    media_list = ctx["media_list"]
    if media_list == ["bus"]:
        cover_line2 = "上海巴士媒体方案"
    elif media_list == ["metro"]:
        cover_line2 = "上海地铁媒体方案"
    else:
        cover_line2 = "上海公交+地铁媒体方案"

    summary = ctx["summary"]
    hyp = ctx["hyp"]
    strategy = ctx["strategy"]
    quote = ctx["quote"]
    effects = ctx["effects"]
    schedule = ctx["schedule"]
    elasticity_pts = (ctx["elasticity"] or {}).get("points") or []
    bus_units = int(summary.get("bus_units") or sum(int(x.get("units") or 1) for x in ctx["bus"]))
    bus_lines = int(summary.get("bus_lines") or len(ctx["bus"]))
    metro_units = int(summary.get("metro_units") or sum(int(x.get("units") or 1) for x in ctx["metro"]))
    metro_stations = int(summary.get("metro_stations") or len({x.get("station") for x in ctx["metro"] if x.get("station")}))
    media_mix = summary.get("media_mix") or {}
    bus_pct = float(media_mix.get("bus_pct") or 0)
    metro_pct = float(media_mix.get("metro_pct") or 0)
    util_pct = summary.get("budget_utilization") if summary.get("budget_utilization") is not None else (
        (ctx["total_paid_wan"] / ctx["budget_wan"]) if ctx["budget_wan"] else 0
    )

    hyp_fields = hyp.get("fields") or []
    hyp_chips = "".join(
        f'<div class="strat-item"><span class="dot-bullet"></span><div><b>{e(f.get("id"))} {e(f.get("label"))}：</b>{e(f.get("value"))}</div></div>'
        for f in hyp_fields[:6]
    )

    # 预算弹性精选行（最多 5 个关键档位，保证 16:9 页面呼吸感）
    el_rows = ""
    if elasticity_pts:
        step = max(1, len(elasticity_pts) // 5)
        picked = elasticity_pts[::step]
        if elasticity_pts[-1] not in picked:
            picked.append(elasticity_pts[-1])
        el_rows = "".join(
            f"<tr><td>{num(p.get('budget_wan'), 0)}万</td><td>{num((p.get('impressions') or 0) / 10000.0, 1)}万</td>"
            f"<td>{pct(p.get('reach'))}</td><td>{num(p.get('frequency'), 1)}</td><td>{num(p.get('cpm_yuan'), 1)}元</td></tr>"
            for p in picked[:6]
        )

    phases_rows = "".join(
        f"<tr><td>{e(p.get('name'))}</td><td>{e(p.get('owner'))}</td><td>{e(p.get('start'))} → {e(p.get('end'))}</td></tr>"
        for p in (schedule.get("phases") or [])[:7]
    )
    nc = schedule.get("night_capacity") or {}
    mon = (schedule.get("monitoring") or [{}])[0]

    gift_items = quote.get("gift_items") or []
    gift_banner = ""
    if gift_items or ctx["gift_wan"] > 0:
        gift_names = "、".join(e(g.get("name") or g.get("id")) for g in gift_items) or "核心商圈/枢纽等值资源"
        gift_banner = f'''<div class="gift-banner">
  <span>本次方案专属配赠额度：<b>{num(ctx["gift_wan"], 2)} 万元</b>（等值赠媒，不计入付费 KPI）</span>
  <small>当前配赠点位：{gift_names}</small>
</div>'''

    # 覆盖地图页标题
    cov_parts = []
    if bus_units:
        cov_parts.append(f"{bus_units}辆公交（{bus_lines}线）")
    if metro_units:
        cov_parts.append(f"{metro_units}个地铁口（{metro_stations}站）")
    cov_headline = f"投放推荐：{' + '.join(cov_parts) or '全城媒体组合'} · {venue}核心客源精准覆盖"

    slides: List[str] = []

    # P1 封面（复刻样本 P1 黑金风）
    slides.append(f'''<section class="slide cover-dark">
  <img class="cover-wave" src="{asset_uri("cover-wave.jpg")}" alt="">
  <div class="cover-vignette"></div>
  <img class="cover-logo" src="{asset_uri("logo-gold.png")}" alt="FLAIR MEDIA">
  <div class="cover-dots-top"><i></i><i class="w"></i><i></i><i class="w"></i></div>
  <div class="cover-side-text">F &nbsp;L &nbsp;A &nbsp;I &nbsp;R &nbsp;&nbsp;&nbsp;M &nbsp;E &nbsp;D &nbsp;I &nbsp;A</div>
  <div class="cover-content">
    <h1 class="gold-title">{e(venue)}<br>{e(cover_line2)}</h1>
    <div class="cover-sub-meta">
      预算 {num(ctx["budget_wan"], 0)} 万元 · 档期 {e(ctx["start_date"])} 至 {e(ctx["end_date"])}（{e(ctx["weeks"])}周） · {e(ctx["customer_label"])}
    </div>
    <div class="cover-flair-mono">FLAIR MEDIA</div>
  </div>
  <div class="cover-grid-dots">{"<span></span>" * 18}</div>
  <div class="cover-foot-right"><span class="line"></span><span>FLAIR MEDIA · {e(ctx["generated_date"])}</span></div>
</section>''')

    # P2 目录 CONTENTS（复刻样本 P2）
    slides.append(f'''<section class="slide lined toc-slide">
  <img class="top-logo abs-logo" src="{asset_uri("logo-red.png")}" alt="FLAIR MEDIA">
  <div class="toc-diamond"></div>
  <div class="toc-head">
    <div class="toc-cn">目 录</div>
    <div class="toc-en">CONTENTS</div>
  </div>
  <div class="toc-ribbon r1"></div>
  <div class="toc-ribbon r2"></div>
  <div class="toc-stair">
    <div class="toc-row s1"><span class="no">01</span><span class="lbl">公司简介</span></div>
    <div class="toc-row s2"><span class="no">02</span><span class="lbl">媒体资源</span></div>
    <div class="toc-row s3"><span class="no">03</span><span class="lbl">发布推荐</span></div>
    <div class="toc-row s4"><span class="no">04</span><span class="lbl">赠送媒体</span></div>
  </div>
</section>''')

    # P3 01 新云简介 分隔页（复刻样本 P3）
    slides.append(_divider_slide("01", "新云简介", "hq-building.jpg"))

    # P4 关于我们 ABOUT US（复刻样本 P4）
    slides.append(f'''<section class="slide lined about-slide">
  {_slide_header("", show_logo=True)}
  <div class="about-center-title">
    <h2>关于我们</h2>
    <div class="en">ABOUT US</div>
  </div>
  <div class="about-circles">
    <div class="about-line"></div>
    <div class="ac gold"><img src="{asset_uri("about-icon-1.png")}" alt="户外地标"></div>
    <div class="ac dark"><img src="{asset_uri("about-icon-2.png")}" alt="城市公交"></div>
    <div class="ac gold"><img src="{asset_uri("about-icon-3.png")}" alt="浦江游船"></div>
    <div class="ac dark"><img src="{asset_uri("about-icon-4.png")}" alt="地铁出入口"></div>
  </div>
  <div class="about-copy">
    <p>上海新云传媒股份有限公司成立于1997年，作为一家深耕城市核心商圈及交通出行领域的媒体运营商，业务涵盖品牌全生命周期，致力于提供品牌营销、创意设计、活动策划和市场分析等综合服务。</p>
    <p>媒体资源全面覆盖城市生活空间，包括LED、户外、公交、地铁媒体等，将品牌渗透到人群出行轨迹与各大功能场景中。合作客户分布于汽车、金融、地产、移动通讯、化妆服饰、互联网、快速消费品等行业领域。</p>
    <p>近年来，企业深度聚焦户外媒体的数字化传播，以资源、服务、创意、数据对媒体进行全方位赋能，深化业务规模，扩展市场格局，竭诚助力客户实现品牌价值。</p>
  </div>
</section>''')

    # P5 企业优势（复刻样本 P5）
    slides.append(f'''<section class="slide lined adv-slide">
  {_slide_header("企业优势", show_logo=True)}
  <div class="adv-headline">
    <div class="cn">助力品牌 &nbsp;引爆上海 &nbsp;辐射全国</div>
    <div class="en">EMPOWER THE BRAND IGNITE SHANGHAI RADIATING NATIONWIDE</div>
  </div>
  <div class="hex-row">
    <div class="hex gold down"><b>户外综合媒体<br>与全域布局</b><span>Comprehensive Outdoor Media<br>&amp; Omnichannel Deployment</span></div>
    <div class="hex dark up"><b>全国资源整合<br>与定制化能力</b><span>Nationwide Resource Integration<br>&amp; Customized Solutions</span></div>
    <div class="hex gold down"><b>大数据驱动<br>精准传播路径</b><span>Data-Driven Precision<br>Communication Strategies</span></div>
    <div class="hex dark up"><b>全链路高效执行<br>与专业服务</b><span>Full-Chain Efficient Execution<br>&amp; Professional Services</span></div>
    <div class="hex gold down"><b>权威资质<br>与行业贡献</b><span>Authoritative Credentials<br>&amp; Industry Contributions</span></div>
  </div>
  <div class="gold-bottom-band"></div>
</section>''')

    # P6 02 媒体资源 分隔页（复刻样本 P6）
    slides.append(_divider_slide("02", "媒体资源", "divider-cubes.jpg"))

    # P7 三大户外媒体全域覆盖（复刻样本 P7）
    slides.append(f'''<section class="slide lined three-media-slide">
  {_slide_header("三大户外媒体全域覆盖", show_logo=True)}
  <div class="three-cols">
    <div class="tm-col">
      <div class="tm-head">户外</div>
      <div class="tm-en">OUTDOOR</div>
      <div class="tm-rule"></div>
      <div class="tm-sub">大牌/LED/游船</div>
      <div class="tm-sub-en">BILLBOARD / LED / CRUISE SHIP</div>
      <div class="tm-stat"><b>10000+</b>平米媒体面积<small>OVER 10,000 M² OF MEDIA COVERAGE</small></div>
      <div class="tm-stat">遍布<b>5</b>大核心商圈<small>COVERING 5 MAJOR BUSINESS DISTRICTS</small></div>
      <div class="tm-stat">城市地标媒体<small>CITY LANDMARK MEDIA PRESENCE</small></div>
      <div class="tm-stat">品牌价值<b>可视化</b><small>VISUALIZING BRAND VALUE</small></div>
    </div>
    <div class="tm-col">
      <div class="tm-head">公交</div>
      <div class="tm-en">BUS</div>
      <div class="tm-rule"></div>
      <div class="tm-sub">单层车/双层巴士/铛铛车</div>
      <div class="tm-sub-en">SINGLE-DECK BUSES, DOUBLE-DECK BUSES, TROLLEYCAR</div>
      <div class="tm-stat">近<b>450</b>条线路<small>NEARLY 450 BUS ROUTES</small></div>
      <div class="tm-stat">近<b>5000</b>辆车<small>NEARLY 5,000 VEHICLES</small></div>
      <div class="tm-stat"><b>高密度</b>渗透出行轨迹<small>HIGH-DENSITY PRESENCE ALONG COMMUTING ROUTES</small></div>
      <div class="tm-stat">日均触达<b>3000万</b>人次<small>DAILY REACH: 30 MILLION+ IMPRESSIONS</small></div>
    </div>
    <div class="tm-col">
      <div class="tm-head">地铁</div>
      <div class="tm-en">METRO</div>
      <div class="tm-rule"></div>
      <div class="tm-sub">上海地铁全线路覆盖</div>
      <div class="tm-sub-en">FULL COVERAGE ACROSS SHANGHAI METRO LINES 1-18</div>
      <div class="tm-stat"><b>1-18</b>号线全线出入口<small>ALL LINES ENTRANCE</small></div>
      <div class="tm-stat">近<b>1000</b>个点位，网络化布局<small>NEARLY 1,000 ENTRANCES IN A GRID-STYLE LAYOUT</small></div>
      <div class="tm-stat">地铁<b>第一眼</b>媒体<small>PRIME "FIRST SIGHT" METRO LOCATIONS</small></div>
      <div class="tm-stat">日均覆盖周边<b>2500万</b>人次<small>DAILY COVERAGE: 25 MILLION+ IMPRESSIONS</small></div>
    </div>
  </div>
</section>''')

    # P8 七类户外媒体资源（复刻样本 P8）
    seven_items = [
        ("media-icon-1.png", "户外大牌", "OUTDOOR BILLBOARD", "商圈地标"),
        ("media-icon-7.png", "户外LED", "OUTDOOR LED", "商圈地标"),
        ("media-icon-4.png", "城市公交", "CITY BUS", "上海最大"),
        ("media-icon-6.png", "双层巴士", "DOUBLE-DECK BUS", "上海首创"),
        ("media-icon-5.png", "南京路铛铛车", "NANJING ROAD TROLLEYCAR", "独家运营"),
        ("media-icon-3.png", "地铁出入口", "METRO ENTRANCES", "独家运营"),
        ("media-icon-2.png", "浦江游船", "HUANGPU RIVER CRUISE", "城市地标"),
    ]
    seven_html = "".join(
        f'<div class="s7-item"><div class="s7-img"><img src="{asset_uri(img)}" alt="{cn}"></div>'
        f'<div class="s7-cn">{cn}</div><div class="s7-en">{en}</div><div class="s7-tag">{tag}</div></div>'
        for img, cn, en, tag in seven_items
    )
    slides.append(f'''<section class="slide lined seven-slide">
  {_slide_header("七类户外媒体资源", show_logo=True)}
  <div class="s7-grid">{seven_html}</div>
  <div class="gold-bottom-band"></div>
</section>''')

    # P9 03 发布推荐 分隔页（复刻样本 P9）
    slides.append(_divider_slide("03", "发布推荐", "divider-cubes.jpg"))

    # P10 项目理解与策略（复刻样本 P10 左文右斜切图 + 竖排 VALUE，填充本次方案策略与 KPI）
    slides.append(f'''<section class="slide lined value-slide">
  {_slide_header(f"{venue} · 策略洞察与媒介价值", show_logo=False)}
  <div class="value-left">
    <div class="quote-slogan">“ {e(hyp.get("one_liner") or strategy.get("one_liner") or "勾勒城市生活圈，精准引爆目标客群！")} ”</div>
    <div class="kpi-strip">
      <div><span>项目预算</span><b>{num(ctx["budget_wan"], 0)}<small>万</small></b></div>
      <div><span>估算有效曝光</span><b>{num((effects.get("impressions") or 0) / 10000.0, 1)}<small>万人次</small></b></div>
      <div><span>目标人群 Reach</span><b>{pct(effects.get("reach_pct") or effects.get("reach"))}</b></div>
      <div><span>频次 / CPM</span><b>{num(effects.get("frequency"), 1)} / {num(effects.get("cpm_yuan"), 1)}<small>元</small></b></div>
    </div>
    <div class="strat-list">
      {hyp_chips}
    </div>
  </div>
  <div class="value-right">
    <img src="{asset_uri("bus-bridge.jpg")}" alt="上海城市媒体">
    <div class="vert-word">VALUE</div>
  </div>
</section>''')

    # P11 城市媒体网络概览（复刻样本 P11 左侧 4 圆形巴士图 + 右侧上海全城网络图 + 本次方案规模卡）
    slides.append(f'''<section class="slide lined net-slide">
  {_slide_header(f"媒体组合配置 · {ctx['media_cn']}", show_logo=True)}
  <div class="net-left">
    <div class="circ c1"><img src="{asset_uri("bus-circle-1.jpg")}" alt=""></div>
    <div class="circ c2"><img src="{asset_uri("bus-circle-2.jpg")}" alt=""></div>
    <div class="circ c3"><img src="{asset_uri("bus-circle-3.jpg")}" alt=""></div>
    <div class="circ c4"><img src="{asset_uri("bus-circle-4.jpg")}" alt=""></div>
  </div>
  <div class="net-right">
    <img class="sh-net-img" src="{asset_uri("shanghai-network.jpg")}" alt="上海媒体网络">
    <div class="net-overlay-card">
      <div class="noc-title">本次方案配置概览</div>
      <div class="noc-grid">
        <div><span>公交车身</span><b>{bus_lines} 条 / {bus_units} 辆</b></div>
        <div><span>地铁出入口</span><b>{metro_stations} 站 / {metro_units} 口</b></div>
        <div><span>媒体费配比</span><b>公交 {pct(bus_pct)} · 地铁 {pct(metro_pct)}</b></div>
        <div><span>库存核对版本</span><b>{e(ctx["data_version"])}</b></div>
      </div>
      <div class="noc-note">目标人群：{e((strategy.get("audience") or {}).get("primary") or "核心家庭与城市出行客群")}；{e((strategy.get("transport") or {}).get("note") or "公交广度覆盖 + 地铁精准拦截。")}</div>
    </div>
  </div>
</section>''')

    # P12 方案覆盖地图（复刻样本 P12-14 大地图页，填充本次方案真实轨迹与点位）
    slides.append(f'''<section class="slide lined map-slide">
  {_slide_header(cov_headline, show_logo=True)}
  <div class="map-frame">
    {build_coverage_map_svg(ctx)}
    <div class="map-float-legend">
      <span><i class="lg-bus"></i>方案公交线路（{len(ctx["routes_bus"])} 条真实轨迹）</span>
      <span><i class="lg-metro"></i>方案地铁线路（{len(ctx["routes_metro"])} 条）</span>
      <span><i class="lg-pt"></i>入选地铁出入口（{metro_units} 口）</span>
      <span><i class="lg-venue"></i>目标场馆：{e(venue)}</span>
    </div>
  </div>
  <div class="map-foot-note">说明：地图轨迹来自新云传媒大数据可视化平台 AI线路（2023-05 轨迹快照），仅用于可视化展示，不参与报价、库存或效果计算；库存以红豆实时快照（{e(ctx["inventory_ts"])}）为准。</div>
</section>''')

    # P13+ 巴士线路甄选明细表（复刻样本 P15）
    slides.append(_bus_table_slides(ctx))

    # P14+ 地铁出入口甄选明细表（当包含地铁时）
    slides.append(_metro_table_slides(ctx))

    # 报价汇总、排期与预算弹性页（补充商业决策闭环）
    el_block = ""
    if el_rows:
        el_block = f'''<div class="panel-title" style="margin-top:4mm">预算弹性对比（100–500 万可伸缩）</div>
<table class="mini-tbl">
  <thead><tr><th>预算档位</th><th>有效曝光</th><th>Reach</th><th>频次</th><th>CPM</th></tr></thead>
  <tbody>{el_rows}</tbody>
</table>'''

    slides.append(f'''<section class="slide lined biz-slide">
  {_slide_header(f"投资报价、执行排期与预算弹性 · 应付总价 {num(ctx['total_paid_wan'], 2)} 万元", show_logo=True)}
  <div class="biz-cols">
    <div class="biz-col">
      <div class="panel-title">投资报价瀑布（单位：万元）</div>
      <table class="mini-tbl">
        <tbody>
          <tr><td>媒体刊例总额</td><td class="tr"><b>{num(ctx["rate_card_wan"], 2)} 万</b></td></tr>
          <tr><td>适用折扣档位</td><td class="tr"><b>{e((quote.get("discount_tier") or {}).get("label") or pct(ctx["discount"]))}</b></td></tr>
          <tr><td>折后媒体发布费</td><td class="tr"><b>{num(ctx["media_net_wan"], 2)} 万</b></td></tr>
          <tr><td>画面制作安装费</td><td class="tr"><b>{num(ctx["production_wan"], 2)} 万</b></td></tr>
          <tr><td>4A 代理服务费</td><td class="tr"><b>{num(ctx["agency_fee_wan"], 2)} 万</b></td></tr>
          <tr class="hi-row"><td><b>本方案应付总价</b></td><td class="tr"><b>{num(ctx["total_paid_wan"], 2)} 万</b></td></tr>
          <tr><td>预算使用率 / 余量</td><td class="tr">{pct(util_pct)} / 余 {num(quote.get("budget_slack_wan"), 2)} 万</td></tr>
        </tbody>
      </table>
      {el_block}
    </div>
    <div class="biz-col">
      <div class="panel-title">全周期执行排期（{e(ctx["start_date"])} → {e(ctx["end_date"])}）</div>
      <table class="mini-tbl">
        <thead><tr><th>执行阶段</th><th>责任方</th><th>时间窗口</th></tr></thead>
        <tbody>{phases_rows}</tbody>
      </table>
      <div class="sla-cards">
        <div><b>夜间施工产能</b><p>公交 {e(nc.get("bus_per_night", 20))} 辆/夜 · 地铁 {e(nc.get("metro_per_night", 10))} 口/夜<br>施工 {e(nc.get("nights", "—"))} 夜 · 雨备缓冲 {e(nc.get("rain_buffer_nights", 2))} 夜</p></div>
        <div><b>监测 SLA 与补偿承诺</b><p>{e(mon.get("name") or "上刊证明")}：{e(mon.get("due") or "上刊当日/次日")}（{e(mon.get("sla") or "带报头日期照片")}）<br>延误补偿：{e((schedule.get("compensation") or {}).get("rule") or "误一补二")}</p></div>
      </div>
      <div class="biz-note">注：以上金额均来自确定性优化引擎逐行分摊；曝光/Reach/CPM 为模型估算非实测；正式价格与条款以双方签署合同为准。</div>
    </div>
  </div>
</section>''')

    # 04 赠送媒体展示 分隔页（复刻样本 P16）
    slides.append(_divider_slide("04", "赠送媒体展示", "divider-gift.jpg"))

    # 4 张赠送媒体实景展示页（复刻样本 P17-20）
    gift_photos = [
        ("陆家嘴第一八佰伴商圈三鑫大厦LED", "gift-sanxin-led.jpg", True),
        ("人民广场商圈来福士商厦LED", "gift-raffles-led.jpg", False),
        ("陆家嘴环球金融中心LED", "gift-swfc-led.jpg", False),
        ("市中心内环内稀缺资源双层观光巴士", "gift-double-bus.jpg", False),
    ]
    for g_title, g_img, show_banner in gift_photos:
        slides.append(f'''<section class="slide lined gift-slide">
  {_slide_header(g_title, show_logo=False)}
  {gift_banner if show_banner else ""}
  <div class="gift-photo-wrap {"with-banner" if show_banner and gift_banner else ""}">
    <img src="{asset_uri(g_img)}" alt="{e(g_title)}">
  </div>
</section>''')

    # 服务能力 Service capability（复刻样本 P21）
    slides.append(f'''<section class="slide lined cap-slide">
  {_slide_header("服务能力", "Service capability", show_logo=False)}
  <div class="cap-grid">
    <div class="cap-card">
      <div class="cap-h">服务客户</div>
      <div class="cap-en">Serve customers</div>
      <div class="cap-item"><b>行业头部</b><span>Industry Leaders</span></div>
      <div class="cap-item"><b>年营收百亿级企业</b><span>Enterprises with Annual Revenue in the Billions</span></div>
    </div>
    <div class="cap-card">
      <div class="cap-h">合作体量</div>
      <div class="cap-en">Cooperation volume</div>
      <div class="cap-item"><b>支撑千万级投放需求</b><span>Capable of Supporting Multi-Million RMB Advertising Campaigns</span></div>
      <div class="cap-item"><b>全国市场营销战略</b><span>Nationwide Marketing Strategies</span></div>
    </div>
    <div class="cap-card">
      <div class="cap-h">专业佐证</div>
      <div class="cap-en">Professional evidence</div>
      <div class="cap-item"><b>匹配高标准传播要求</b><span>Meeting the Highest Standards of Communication Excellence</span></div>
      <div class="cap-item"><b>全域行业认可</b><span>Recognized Across the Entire Industry Landscape</span></div>
    </div>
  </div>
</section>''')

    # 封底（复刻样本 P22 黑金风）
    slides.append(f'''<section class="slide cover-dark">
  <img class="cover-wave" src="{asset_uri("cover-wave.jpg")}" alt="">
  <div class="cover-vignette"></div>
  <img class="cover-logo" src="{asset_uri("logo-gold.png")}" alt="FLAIR MEDIA">
  <div class="cover-dots-top"><i></i><i class="w"></i><i></i><i class="w"></i></div>
  <div class="cover-side-text">F &nbsp;L &nbsp;A &nbsp;I &nbsp;R &nbsp;&nbsp;&nbsp;M &nbsp;E &nbsp;D &nbsp;I &nbsp;A</div>
  <div class="cover-content closing-content">
    <div class="gold-title closing-title">期待合作！</div>
    <div class="cover-sub-meta">提案编号 {e(ctx["run_id"])} · 数据版本 {e(ctx["data_version"])} · 库存快照 {e(ctx["inventory_ts"])}</div>
  </div>
  <div class="cover-grid-dots">{"<span></span>" * 18}</div>
  <div class="cover-foot-right"><span class="line"></span><span>FLAIR MEDIA · 上海新云传媒股份有限公司</span></div>
</section>''')

    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{e(venue)} · 上海户外媒体投放方案 · FLAIR MEDIA</title>
<style>{PROPOSAL_CSS}</style>
</head>
<body>
{"".join(slides)}
</body>
</html>'''


PROPOSAL_CSS = r'''
@page { size: 338.67mm 190.5mm; margin: 0; }
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0; background: #fff; color: #363636;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.slide {
  width: 338.67mm; height: 190.5mm; position: relative; overflow: hidden;
  page-break-after: always; background: #fbfbfb;
}
.slide:last-child { page-break-after: auto; }
.slide.lined {
  background-color: #fbfbfb;
  background-image: repeating-linear-gradient(
    to bottom,
    rgba(225, 225, 225, 0.28) 0px,
    rgba(225, 225, 225, 0.28) 6mm,
    rgba(255, 255, 255, 0.7) 6mm,
    rgba(255, 255, 255, 0.7) 12mm
  );
}

/* ===== 黑金封面 / 封底 ===== */
.cover-dark { background: #050505; color: #fff; }
.cover-wave { position: absolute; right: 0; top: 0; height: 100%; width: 48%; object-fit: cover; opacity: 0.92; }
.cover-vignette {
  position: absolute; inset: 0;
  background: linear-gradient(90deg, #050505 0%, #050505 56%, rgba(5,5,5,0.65) 68%, rgba(5,5,5,0.05) 86%);
}
.cover-logo { position: absolute; left: 12mm; top: 8mm; height: 16mm; z-index: 3; }
.cover-dots-top { position: absolute; right: 13mm; top: 10mm; display: flex; gap: 5mm; z-index: 3; }
.cover-dots-top i { width: 5mm; height: 5mm; border-radius: 50%; background: #c28d57; display: block; }
.cover-dots-top i.w { background: #ffffff; }
.cover-side-text {
  position: absolute; left: 13mm; top: 52mm; writing-mode: vertical-rl;
  font-size: 9pt; letter-spacing: 0.35em; color: #9c7d5e; z-index: 3;
}
.cover-content { position: absolute; left: 31mm; top: 52mm; z-index: 3; max-width: 195mm; }
.gold-title {
  margin: 0; font-size: 46pt; line-height: 1.24; font-weight: 800; letter-spacing: 0.02em;
  background: linear-gradient(115deg, #ffffff 10%, #f5dfbe 52%, #c58d58 95%);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.cover-sub-meta { margin-top: 8mm; font-size: 13pt; color: #d6c4ae; letter-spacing: 0.04em; }
.cover-flair-mono { margin-top: 15mm; font-family: "Courier New", monospace; font-size: 22pt; letter-spacing: 0.22em; color: #e2be96; }
.closing-content { top: 72mm; }
.closing-title { font-size: 54pt; }
.cover-grid-dots {
  position: absolute; left: 12mm; bottom: 8mm; width: 40mm; display: grid;
  grid-template-columns: repeat(6, 1fr); gap: 3.5mm; z-index: 3;
}
.cover-grid-dots span { width: 2mm; height: 2mm; border-radius: 50%; background: #c28d57; display: block; }
.cover-foot-right {
  position: absolute; right: 13mm; bottom: 9mm; z-index: 3; display: flex; align-items: center; gap: 6mm;
  font-size: 11pt; color: #f5f5f5; letter-spacing: 0.06em;
}
.cover-foot-right .line { width: 22mm; height: 1px; background: #c28d57; display: inline-block; }

/* ===== 页眉 ===== */
.slide-hdr {
  height: 22mm; padding: 5mm 12mm 0 0; display: flex; justify-content: space-between; align-items: center;
  position: relative; z-index: 4;
}
.hdr-left { display: flex; align-items: center; }
.hdr-line { width: 12mm; height: 1px; background: #b4b4b4; display: inline-block; }
.hdr-diamond-out {
  width: 9mm; height: 9mm; border: 1px solid #b4b4b4; transform: rotate(45deg);
  margin-left: 1mm; display: inline-block;
}
.hdr-diamond-in {
  width: 9mm; height: 9mm; background: #c28d57; transform: rotate(45deg);
  margin-left: -4.5mm; display: inline-block;
}
.hdr-title { margin-left: 7mm; font-size: 14pt; font-weight: 700; color: #333; white-space: nowrap; }
.hdr-sub { margin-left: 4mm; font-size: 11pt; color: #8c8c8c; font-family: Georgia, serif; }
.top-logo { height: 12mm; }
.abs-logo { position: absolute; right: 10mm; top: 7mm; z-index: 5; }

/* ===== 目录页 ===== */
.toc-diamond {
  position: absolute; left: 24mm; top: 3mm; width: 20mm; height: 20mm;
  background: #c28d57; transform: rotate(45deg);
}
.toc-head { position: absolute; left: 18mm; top: 28mm; }
.toc-cn { font-size: 30pt; font-weight: 400; color: #4a4a4a; letter-spacing: 0.12em; }
.toc-en { font-size: 26pt; font-weight: 300; color: #c28d57; letter-spacing: 0.08em; margin-top: 1mm; }
.toc-stair { position: relative; z-index: 3; }
.toc-row { position: absolute; display: flex; flex-direction: column; }
.toc-row .no { font-family: Georgia, "Times New Roman", serif; font-style: italic; font-size: 32pt; color: #c28d57; line-height: 1; }
.toc-row .lbl { font-size: 22pt; color: #4a4a4a; margin-top: 2mm; }
.toc-row.s1 { left: 196mm; top: 26mm; }
.toc-row.s2 { left: 156mm; top: 66mm; }
.toc-row.s3 { left: 116mm; top: 106mm; }
.toc-row.s4 { left: 76mm; top: 146mm; }
.toc-ribbon {
  position: absolute; border: 14mm solid rgba(194, 141, 87, 0.35); border-radius: 12mm;
  transform: rotate(45deg); z-index: 1;
}
.toc-ribbon.r1 { width: 120mm; height: 120mm; right: 56mm; bottom: -66mm; border-color: rgba(194, 141, 87, 0.25); }
.toc-ribbon.r2 { width: 135mm; height: 135mm; right: -12mm; bottom: -56mm; border-color: rgba(194, 141, 87, 0.55); }

/* ===== 章节分隔页 ===== */
.divider { display: flex; background: #f8f8f8; }
.div-left { width: 52%; height: 100%; position: relative; overflow: hidden; }
.div-left img {
  width: 100%; height: 100%; object-fit: cover;
  clip-path: polygon(0 0, 42% 0, 88% 50%, 42% 100%, 0 100%);
}
.div-right { width: 48%; position: relative; display: flex; align-items: center; justify-content: flex-end; padding-right: 22mm; }
.div-right .top-logo { position: absolute; right: 10mm; top: 7mm; }
.div-text { text-align: right; }
.div-no { font-family: Georgia, "Times New Roman", serif; font-style: italic; font-size: 48pt; color: #c28d57; line-height: 1; }
.div-title { font-size: 38pt; color: #4a4a4a; margin-top: 4mm; letter-spacing: 0.04em; }

/* ===== 关于我们 ===== */
.about-center-title { text-align: center; margin-top: -12mm; }
.about-center-title h2 { margin: 0; font-size: 28pt; color: #3c3c3c; letter-spacing: 0.06em; }
.about-center-title .en { font-size: 13pt; font-weight: 700; color: #444; letter-spacing: 0.08em; margin-top: 1mm; }
.about-circles {
  position: relative; width: 260mm; margin: 14mm auto 12mm; display: flex;
  justify-content: center; gap: 14mm; align-items: center;
}
.about-line { position: absolute; left: 0; right: 0; top: 50%; height: 2px; background: #4a4a4a; z-index: 1; }
.ac {
  width: 34mm; height: 34mm; border-radius: 50%; display: grid; place-items: center;
  position: relative; z-index: 2; box-shadow: 0 0 0 3.5mm #fbfbfb, 0 0 0 4.5mm #4a4a4a;
}
.ac.gold { background: #c5905b; }
.ac.dark { background: #3f3f3f; }
.ac img { max-width: 21mm; max-height: 21mm; object-fit: contain; }
.about-copy { width: 282mm; margin: 0 auto; font-size: 14.5pt; line-height: 1.9; color: #3a3a3a; }
.about-copy p { margin: 0 0 3mm; }

/* ===== 企业优势 ===== */
.adv-headline { text-align: center; margin-top: 2mm; }
.adv-headline .cn { font-size: 28pt; font-weight: 700; color: #c28d57; letter-spacing: 0.08em; }
.adv-headline .en { font-size: 11.5pt; font-weight: 700; color: #7a7a7a; letter-spacing: 0.06em; margin-top: 2mm; }
.hex-row {
  display: flex; justify-content: center; align-items: center; gap: 5mm;
  margin-top: 14mm; position: relative; z-index: 3;
}
.hex {
  width: 54mm; height: 60mm; display: flex; flex-direction: column; justify-content: center; align-items: center;
  text-align: center; padding: 6mm; color: #fff;
  clip-path: polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%);
}
.hex.gold { background: linear-gradient(160deg, #deb589, #c08852); }
.hex.dark { background: linear-gradient(160deg, #a6a6a6, #4b4b4b); }
.hex.up { transform: translateY(-9mm); }
.hex.down { transform: translateY(7mm); }
.hex b { font-size: 14pt; line-height: 1.35; }
.hex span { font-size: 7.5pt; opacity: 0.92; margin-top: 3mm; line-height: 1.3; font-style: italic; }
.gold-bottom-band { position: absolute; left: 0; right: 0; bottom: 0; height: 34mm; background: #c28d57; z-index: 1; }

/* ===== 三大户外媒体 ===== */
.three-cols { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14mm; padding: 10mm 22mm 0; }
.tm-head { font-size: 28pt; font-weight: 300; color: #c28d57; }
.tm-en { font-size: 10pt; font-weight: 700; color: #c28d57; letter-spacing: 0.1em; margin-top: 1mm; }
.tm-rule { height: 1px; background: #666; width: 42mm; margin: 3mm 0 3.5mm; }
.tm-sub { font-size: 11.5pt; color: #555; }
.tm-sub-en { font-size: 6.5pt; color: #c28d57; font-style: italic; margin-bottom: 8mm; }
.tm-stat { margin-bottom: 8mm; font-size: 14pt; color: #555; }
.tm-stat b { font-size: 18pt; color: #c28d57; font-weight: 700; }
.tm-stat small { display: block; font-size: 7.5pt; color: #666; font-weight: 700; margin-top: 1.5mm; letter-spacing: 0.03em; }

/* ===== 七类户外媒体 ===== */
.s7-grid {
  display: grid; grid-template-columns: repeat(7, 1fr); gap: 4mm; padding: 14mm 12mm 0;
  position: relative; z-index: 3; align-items: end;
}
.s7-item { text-align: center; }
.s7-img { height: 42mm; display: flex; align-items: flex-end; justify-content: center; margin-bottom: 5mm; }
.s7-img img { max-width: 100%; max-height: 40mm; object-fit: contain; }
.s7-cn { font-size: 12pt; font-weight: 700; color: #3c3c3c; }
.s7-en { font-size: 6.5pt; color: #8c8c8c; margin: 1mm 0 4mm; min-height: 8mm; }
.s7-tag { font-size: 15pt; font-weight: 700; color: #c28d57; }

/* ===== 策略洞察与价值页（样本 P10） ===== */
.value-left { width: 57%; padding: 4mm 10mm 0 18mm; position: relative; z-index: 3; }
.quote-slogan { font-size: 17pt; font-weight: 700; color: #3a3a3a; line-height: 1.45; margin-bottom: 6mm; }
.kpi-strip { display: grid; grid-template-columns: repeat(4, 1fr); gap: 3mm; margin-bottom: 6mm; }
.kpi-strip > div {
  background: #fff; border: 1px solid #e2d5c3; border-top: 2.5px solid #c28d57;
  padding: 3mm 3.2mm; border-radius: 1.5mm;
}
.kpi-strip span { display: block; font-size: 8pt; color: #7a7368; margin-bottom: 1mm; }
.kpi-strip b { font-size: 13.5pt; color: #b42322; white-space: nowrap; }
.kpi-strip small { font-size: 8pt; color: #555; font-weight: 400; margin-left: 0.8mm; }
.strat-list { display: grid; gap: 3.2mm; }
.strat-item { display: flex; align-items: flex-start; gap: 3mm; font-size: 10.5pt; line-height: 1.5; color: #3f3f3f; }
.dot-bullet { width: 2.6mm; height: 2.6mm; border-radius: 50%; background: #c28d57; margin-top: 2mm; flex-shrink: 0; }
.value-right { position: absolute; right: 0; top: 0; width: 46%; height: 100%; overflow: hidden; }
.value-right img { width: 100%; height: 100%; object-fit: cover; clip-path: polygon(22% 0, 100% 0, 100% 100%, 0 100%); }
.vert-word {
  position: absolute; right: 4mm; top: 20mm; writing-mode: vertical-rl;
  font-family: Georgia, serif; font-size: 56pt; font-weight: 800; letter-spacing: 0.08em;
  color: rgba(255, 255, 255, 0.86); text-shadow: 0 2px 10px rgba(0,0,0,0.28);
}

/* ===== 媒体网络概览（样本 P11） ===== */
.net-left { position: absolute; left: 8mm; top: 26mm; width: 132mm; height: 152mm; }
.circ { position: absolute; border-radius: 50%; overflow: hidden; border: 2mm solid #c28d57; box-shadow: 0 4px 12px rgba(0,0,0,0.12); }
.circ img { width: 100%; height: 100%; object-fit: cover; }
.circ.c1 { width: 104mm; height: 104mm; left: 0; top: 26mm; }
.circ.c2 { width: 52mm; height: 52mm; left: 78mm; top: 4mm; }
.circ.c3 { width: 34mm; height: 34mm; left: 100mm; top: 72mm; }
.circ.c4 { width: 24mm; height: 24mm; left: 88mm; top: 114mm; }
.net-right { position: absolute; left: 136mm; right: 10mm; top: 22mm; bottom: 8mm; }
.sh-net-img { width: 100%; height: 100%; object-fit: cover; border: 1px solid #e4dccf; }
.net-overlay-card {
  position: absolute; right: 5mm; bottom: 5mm; width: 118mm;
  background: rgba(255, 255, 255, 0.94); border: 1.5px solid #c28d57; padding: 4.5mm 5.5mm;
}
.noc-title { font-size: 11pt; font-weight: 700; color: #b42322; margin-bottom: 3mm; }
.noc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2.5mm 4mm; }
.noc-grid span { display: block; font-size: 7.5pt; color: #777; }
.noc-grid b { font-size: 10pt; color: #222; }
.noc-note { margin-top: 3mm; font-size: 8pt; color: #555; border-top: 1px solid #eadfce; padding-top: 2mm; line-height: 1.45; }

/* ===== 覆盖地图页（样本 P12-14） ===== */
.map-frame {
  position: relative; margin: 2mm 14mm 0; height: 152mm;
  border: 1.5px solid #9dbbd4; background: #dcebf7; overflow: hidden;
}
.cov-map { width: 100%; height: 100%; display: block; }
.cov-map .dist { fill: #f7f4ec; stroke: #c5bfb2; stroke-width: 1; }
.cov-map .dist-lbl { font-size: 11px; fill: #8b7d6b; text-anchor: middle; font-weight: 600; }
.map-float-legend {
  position: absolute; right: 4mm; bottom: 4mm; background: rgba(255,255,255,0.92);
  border: 1px solid #c28d57; padding: 2.5mm 4mm; display: flex; gap: 5mm; font-size: 8.5pt; color: #333;
}
.map-float-legend i { display: inline-block; vertical-align: middle; margin-right: 1.5mm; }
.lg-bus { width: 7mm; height: 1.2mm; background: #c83e37; }
.lg-metro { width: 7mm; height: 1.2mm; border-top: 2px dashed #c28d57; }
.lg-pt { width: 3mm; height: 3mm; border-radius: 50%; background: #b42322; }
.lg-venue { width: 3mm; height: 3mm; background: #b42322; transform: rotate(45deg); }
.map-foot-note { margin: 2.5mm 14mm 0; font-size: 8pt; color: #666; }

/* ===== 双栏线路明细表（复刻样本 P15） ===== */
.dual-tables {
  display: grid; grid-template-columns: 1.07fr 0.93fr; gap: 4mm;
  padding: 2mm 6mm 0; height: 162mm; align-items: start;
}
.single-table-wrap { padding: 3mm 12mm 0; }
.line-tbl { width: 100%; border-collapse: collapse; font-size: 8.2pt; background: #fff; }
.line-tbl--wide { font-size: 9.2pt; }
.line-tbl th {
  background: #cfa170; color: #1f1a14; font-weight: 700; text-align: center;
  border: 0.7px solid #444; padding: 1.6mm 1.2mm; line-height: 1.2;
}
.line-tbl td {
  border: 0.7px solid #555; padding: 1.25mm 1.2mm; text-align: center; color: #1c1c1c;
}
.line-tbl td.qty { color: #d61f1f; font-weight: 700; }
.line-tbl td.city-cell { font-weight: 700; background: #faf6f0; }
.reach-callout {
  margin-top: 4mm; border: 1.5px solid #4a7ebb; background: #fff;
  padding: 3.5mm 5mm; text-align: center; font-size: 11.5pt; line-height: 1.65; color: #c41e1e;
}
.reach-callout span { font-weight: 800; font-size: 13pt; }

/* ===== 报价排期弹性页 ===== */
.biz-cols { display: grid; grid-template-columns: 0.96fr 1.04fr; gap: 9mm; padding: 4mm 14mm 0; }
.panel-title {
  font-size: 11.5pt; font-weight: 700; color: #333; border-left: 3.5px solid #c28d57;
  padding-left: 3mm; margin-bottom: 3mm;
}
.mini-tbl { width: 100%; border-collapse: collapse; font-size: 9.5pt; background: #fff; }
.mini-tbl th { background: #cfa170; color: #1f1a14; padding: 2mm 3mm; text-align: left; border: 0.7px solid #9d8b74; }
.mini-tbl td { padding: 2mm 3mm; border: 0.7px solid #dfd3c2; }
.mini-tbl .tr { text-align: right; }
.mini-tbl .hi-row td { background: #fbf1e4; color: #b42322; font-size: 10.5pt; }
.sla-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 4mm; margin-top: 5mm; }
.sla-cards > div { background: #fff; border: 1px solid #dfd3c2; border-top: 2.5px solid #c28d57; padding: 3.5mm 4.5mm; }
.sla-cards b { font-size: 10pt; color: #333; }
.sla-cards p { margin: 2mm 0 0; font-size: 8.8pt; color: #555; line-height: 1.55; }
.biz-note { margin-top: 4mm; font-size: 8pt; color: #777; line-height: 1.5; }

/* ===== 赠送媒体页（样本 P17-20） ===== */
.gift-banner {
  margin: 1mm 18mm 2mm; padding: 2.5mm 5mm; background: #fbf1e4;
  border-left: 4px solid #b42322; display: flex; justify-content: space-between; align-items: center;
  font-size: 10pt; color: #333;
}
.gift-banner b { color: #b42322; font-size: 11.5pt; }
.gift-banner small { color: #666; font-size: 8.8pt; }
.gift-photo-wrap { margin: 2mm 18mm 0; height: 158mm; overflow: hidden; }
.gift-photo-wrap.with-banner { height: 145mm; }
.gift-photo-wrap img { width: 100%; height: 100%; object-fit: cover; display: block; }

/* ===== 服务能力页（样本 P21） ===== */
.cap-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 11mm; padding: 14mm 14mm 0; }
.cap-card {
  border: 1px solid #d4a678; border-radius: 6mm; background: rgba(255,255,255,0.75);
  padding: 10mm 9mm; height: 132mm;
}
.cap-h { font-size: 32pt; font-weight: 300; color: #4a4a4a; letter-spacing: 0.06em; }
.cap-en { font-family: "Courier New", monospace; font-size: 10.5pt; color: #8c7a66; margin-top: 2mm; margin-bottom: 16mm; }
.cap-item { margin-bottom: 11mm; padding-left: 6mm; position: relative; }
.cap-item::before {
  content: ""; position: absolute; left: 0; top: 3mm; width: 3mm; height: 3mm; background: #c28d57;
}
.cap-item b { display: block; font-size: 16pt; color: #c28d57; font-weight: 500; }
.cap-item span { display: block; font-size: 8.5pt; color: #a89989; font-style: italic; margin-top: 1.5mm; }
'''
