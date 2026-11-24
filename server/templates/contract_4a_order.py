# -*- coding: utf-8 -*-
"""模板 3：4A 户外排期表 / 订单（A4 横版）。

依据：`docs/03-合同三份-脱敏版等9个文件/03-合同三份-脱敏版/M3-4A订单-脱敏版.pdf`
严格复刻原版 `Proposed Outdoor Spot Plan 户外排期表` 15 列中英双语排期表结构、
顶部元信息条、3 条 Remark 备注及底部甲乙方签字盖章区，动态填入本次方案全部明细与报价。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .common import e, extract_run_context, num


def _fmt_slash_date(iso: str) -> str:
    parts = str(iso or "").split("-")
    if len(parts) == 3:
        try:
            return f"{int(parts[0])}/{int(parts[1])}/{int(parts[2])}"
        except ValueError:
            pass
    return str(iso or "—")


def build_4a_order_html(run: Dict[str, Any]) -> str:
    ctx = extract_run_context(run)
    venue = ctx["venue_name"]
    start_s = _fmt_slash_date(ctx["start_date"])
    end_s = _fmt_slash_date(ctx["end_date"])
    disc_pct_off = round((1.0 - ctx["discount"]) * 100.0, 1)
    disc_label = f"{int(round(ctx['discount'] * 100))}%（{disc_pct_off:g}% Off）"

    rows: List[str] = []
    total_qty = 0

    for item in ctx["bus"]:
        u = int(item.get("units") or 1)
        total_qty += u
        gross_y = float(item.get("gross_wan") or 0) * 10000.0
        net_y = float(item.get("net_wan") or 0) * 10000.0
        prod_y = float(item.get("production_wan") or 0) * 10000.0
        tot_y = float(item.get("total_wan") or 0) * 10000.0
        loc = f"{item.get('line') or ''}路（{item.get('district') or '上海'}）"
        mtype = str(item.get("media_type") or "大三侧")
        remark = f"{item.get('level') or ''}级；{item.get('company') or '公交车身'}；日夜营运"
        rows.append(
            f"<tr>"
            f"<td>公交车身</td>"
            f"<td>上海</td>"
            f'<td class="tl">{e(loc)}</td>'
            f"<td>{e(mtype)}</td>"
            f"<td>详见MR</td>"
            f"<td>/</td>"
            f"<td>{e(start_s)}</td>"
            f"<td>{e(end_s)}</td>"
            f"<td>{u}</td>"
            f'<td class="tl">{e(remark)}</td>'
            f'<td class="tr">{num(gross_y, 2)}</td>'
            f"<td>{e(disc_label)}</td>"
            f'<td class="tr">{num(net_y, 2)}</td>'
            f'<td class="tr">{num(prod_y, 2)}</td>'
            f'<td class="tr"><b>{num(tot_y, 2)}</b></td>'
            f"</tr>"
        )

    for item in ctx["metro"]:
        u = int(item.get("units") or 1)
        total_qty += u
        gross_y = float(item.get("gross_wan") or 0) * 10000.0
        net_y = float(item.get("net_wan") or 0) * 10000.0
        prod_y = float(item.get("production_wan") or 0) * 10000.0
        tot_y = float(item.get("total_wan") or 0) * 10000.0
        loc = f"{item.get('station') or ''}站 {item.get('exit') or ''}（{item.get('district') or '上海'}）"
        remark = f"{item.get('level') or ''}级；全天候展示；照明随地铁运营时间"
        rows.append(
            f"<tr>"
            f"<td>地铁出入口</td>"
            f"<td>上海</td>"
            f'<td class="tl">{e(loc)}</td>'
            f"<td>地铁出入口</td>"
            f"<td>详见MR</td>"
            f"<td>/</td>"
            f"<td>{e(start_s)}</td>"
            f"<td>{e(end_s)}</td>"
            f"<td>{u}</td>"
            f'<td class="tl">{e(remark)}</td>'
            f'<td class="tr">{num(gross_y, 2)}</td>'
            f"<td>{e(disc_label)}</td>"
            f'<td class="tr">{num(net_y, 2)}</td>'
            f'<td class="tr">{num(prod_y, 2)}</td>'
            f'<td class="tr"><b>{num(tot_y, 2)}</b></td>'
            f"</tr>"
        )

    for g in (ctx["quote"].get("gift_items") or []):
        g_gross = float(g.get("gross_wan") or 0) * 10000.0
        rows.append(
            f'<tr class="gift-row">'
            f"<td>赠送媒体</td>"
            f"<td>上海</td>"
            f'<td class="tl">{e(g.get("name") or g.get("id"))}</td>'
            f"<td>Gift 赠媒</td>"
            f"<td>详见MR</td>"
            f"<td>/</td>"
            f"<td>{e(start_s)}</td>"
            f"<td>{e(end_s)}</td>"
            f"<td>1</td>"
            f'<td class="tl">合同等值配赠资源（不计付费KPI）</td>'
            f'<td class="tr">{num(g_gross, 2)}</td>'
            f"<td>100% Off</td>"
            f'<td class="tr">0.00</td>'
            f'<td class="tr">0.00</td>'
            f'<td class="tr">0.00</td>'
            f"</tr>"
        )

    if ctx["agency_fee_wan"] > 0:
        ag_y = ctx["agency_fee_wan"] * 10000.0
        rows.append(
            f"<tr>"
            f"<td>4A服务费</td>"
            f"<td>上海</td>"
            f'<td class="tl">4A 代理服务费（15%）</td>'
            f"<td>Agency Fee</td>"
            f"<td>/</td>"
            f"<td>/</td>"
            f"<td>{e(start_s)}</td>"
            f"<td>{e(end_s)}</td>"
            f"<td>1</td>"
            f'<td class="tl">按折后媒体净价口径计提</td>'
            f'<td class="tr">—</td>'
            f"<td>/</td>"
            f'<td class="tr">{num(ag_y, 2)}</td>'
            f'<td class="tr">0.00</td>'
            f'<td class="tr"><b>{num(ag_y, 2)}</b></td>'
            f"</tr>"
        )

    # 底部合计行
    rows.append(
        f'<tr class="sum-row">'
        f'<td colspan="8"><b>Total 合计（方案编号：{e(ctx["run_id"])} · 数据版本：{e(ctx["data_version"])}）</b></td>'
        f"<td><b>{total_qty}</b></td>"
        f'<td class="tl">含增值税专用发票（6%）</td>'
        f'<td class="tr"><b>{num(ctx["rate_card_wan"] * 10000.0, 2)}</b></td>'
        f"<td><b>{e(disc_label)}</b></td>"
        f'<td class="tr"><b>{num((ctx["media_net_wan"] + ctx["agency_fee_wan"]) * 10000.0, 2)}</b></td>'
        f'<td class="tr"><b>{num(ctx["production_wan"] * 10000.0, 2)}</b></td>'
        f'<td class="tr"><b>{num(ctx["total_paid_yuan"], 2)}</b></td>'
        f"</tr>"
    )

    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Proposed Outdoor Spot Plan 户外排期表 · {e(venue)}</title>
<style>{ORDER_CSS}</style>
</head>
<body>
<div class="sheet">
  <table class="spot-tbl">
    <thead>
      <tr class="title-row">
        <th colspan="15">Proposed Outdoor Spot Plan 户外排期表</th>
      </tr>
      <tr class="meta-hdr">
        <th colspan="3">Planed Month 月份</th>
        <th colspan="6">Client 客户</th>
        <th colspan="2">Market 地区</th>
        <th colspan="4">Campaign Period 广告周期</th>
      </tr>
      <tr class="meta-val">
        <td colspan="3"><b>{e(ctx["planned_month"])}</b></td>
        <td colspan="6"><b>{e(venue)}（{e(ctx["customer_label"])} · 编号 {e(ctx["contract_no"])}）</b></td>
        <td colspan="2"><b>上海</b></td>
        <td colspan="4"><b>{e(start_s)} - {e(end_s)}（{e(ctx["weeks"])}周）</b></td>
      </tr>
      <tr class="col-hdr">
        <th rowspan="2" style="width:5.5%">Media<br>名称</th>
        <th style="width:4%">MARKET</th>
        <th rowspan="2" style="width:12%">Location<br>位置</th>
        <th rowspan="2" style="width:6.5%">Type<br>型式</th>
        <th rowspan="2" style="width:5.5%">Display Size<br>尺寸(厘米)</th>
        <th rowspan="2" style="width:5%">Digital Size<br>秒数/频次</th>
        <th colspan="2" style="width:11%">Campaign Period</th>
        <th rowspan="2" style="width:4%">Qty<br>数量(个)</th>
        <th rowspan="2" style="width:12.5%">Remark<br>备注</th>
        <th rowspan="2" style="width:7%">Ratecard<br>刊例价(RMB)</th>
        <th rowspan="2" style="width:6.5%">Discount Off<br>折扣</th>
        <th rowspan="2" style="width:7%">Net Cost<br>净价(RMB)</th>
        <th rowspan="2" style="width:6.5%">Production Cost<br>制作费</th>
        <th rowspan="2" style="width:7%">Total Cost<br>总价</th>
      </tr>
      <tr class="col-hdr">
        <th>地区</th>
        <th>开始日期</th>
        <th>结束日期</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>

  <div class="remarks">
    <div><b>Remark:</b></div>
    <div>1. 安装制作安装周期：按购买数量在 2-3 个夜间窗口内完成人工上画（夜间 23:00-05:00，含雨备顺延窗口），画面具有时效性，不得提前上刊或推迟下刊；</div>
    <div>2. 本排期表仅为定位协议，具体条款约定内容以双方签署的《{ctx["campaign_year"]}年户外广告投放及制作框架合同书》为准，具体发布数量、金额以本排期表为准；</div>
    <div>3. 本排期表经双方盖章后生效。</div>
  </div>

  <div class="sign-row">
    <div class="sign-box">
      <div><b>甲方：</b>{e(venue)}（4A 代理方）</div>
      <div><b>地址：</b>__________________________________________</div>
      <div><b>授权代表签字：</b>__________________________________</div>
      <div><b>盖章：</b></div>
    </div>
    <div class="sign-box">
      <div><b>乙方：</b><span class="ul">上海新云传媒股份有限公司</span></div>
      <div><b>地址：</b>__________________________________________</div>
      <div><b>授权代表签字：</b>__________________________________</div>
      <div><b>盖章：</b></div>
    </div>
  </div>
</div>
</body>
</html>'''


ORDER_CSS = r'''
@page { size: A4 landscape; margin: 11mm 10mm 11mm 10mm; }
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0; background: #fff; color: #111;
  font-family: "Microsoft YaHei", "PingFang SC", "SimSun", sans-serif;
  font-size: 7.8pt; line-height: 1.4;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.spot-tbl { width: 100%; border-collapse: collapse; border: 1.4pt solid #111; }
.spot-tbl thead { display: table-header-group; }
.spot-tbl tr { page-break-inside: avoid; }
.spot-tbl th, .spot-tbl td {
  border: 0.6pt solid #333; padding: 1.3mm 1.2mm; text-align: center; vertical-align: middle;
}
.title-row th {
  font-size: 11.5pt; font-weight: 700; padding: 2mm; background: #fff; letter-spacing: 0.04em;
}
.meta-hdr th { background: #f2f2f2; font-weight: 600; font-size: 7.4pt; }
.meta-val td { background: #fff; font-size: 8.2pt; padding: 1.6mm; }
.col-hdr th { background: #f7f7f7; font-weight: 600; font-size: 7.2pt; line-height: 1.25; }
.spot-tbl td.tl { text-align: left; }
.spot-tbl td.tr { text-align: right; font-variant-numeric: tabular-nums; }
.gift-row td { background: #faf6ef; color: #555; }
.sum-row td { background: #f2ede3; font-size: 8.2pt; padding: 1.8mm 1.4mm; }
.remarks { margin-top: 4mm; font-size: 7.6pt; line-height: 1.65; color: #222; page-break-inside: avoid; }
.sign-row {
  display: grid; grid-template-columns: 1fr 1fr; gap: 22mm;
  margin-top: 7mm; font-size: 9pt; line-height: 2.3; page-break-inside: avoid;
}
.ul { text-decoration: underline; }
'''
