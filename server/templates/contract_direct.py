# -*- coding: utf-8 -*-
"""模板 2：直客广告发布合同（A4 竖版）。

依据：`docs/03-合同三份-脱敏版等9个文件/03-合同三份-脱敏版/M3-直客合同-脱敏版.pdf`
严格保留原版公文格式、右上角 FLAIR MEDIA 新云传媒页眉、合同总价/合同编号方框、甲乙方信息表、
第一条发布详情表（动态填入本次方案全部公交/地铁入选点位与价格），以及第二至第八条完整原文条款。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from .common import asset_uri, e, extract_run_context, num, rmb_upper


def _shift_date(iso_date: str, days: int) -> str:
    try:
        d = date.fromisoformat(iso_date[:10]) + timedelta(days=days)
        return f"{d.year} 年 {d.month:02d} 月 {d.day:02d} 日"
    except ValueError:
        return "____ 年 __ 月 __ 日"


def build_direct_contract_html(run: Dict[str, Any]) -> str:
    ctx = extract_run_context(run)
    venue = ctx["venue_name"]
    media_list = ctx["media_list"]
    if media_list == ["bus"]:
        doc_title = "公交广告发布合同"
    elif media_list == ["metro"]:
        doc_title = "地铁媒体广告发布合同"
    else:
        doc_title = "户外媒体广告发布合同"

    total_yuan = ctx["total_paid_yuan"]
    prepay_yuan = round(total_yuan * 0.5, 2)
    final_yuan = round(total_yuan - prepay_yuan, 2)
    prepay_date = _shift_date(ctx["start_date"], -15)
    material_date = _shift_date(ctx["start_date"], -20)
    final_date = _shift_date(ctx["end_date"], 30)

    # 构建第一条发布详情行：公交 + 地铁 + 赠媒
    rows: List[str] = []
    total_units = 0
    sum_gross_yuan = 0.0
    sum_net_yuan = 0.0
    sum_prod_yuan = 0.0
    period_label = f"{ctx['weeks']} 周"

    for item in ctx["bus"]:
        u = int(item.get("units") or 1)
        gross_y = float(item.get("gross_wan") or 0) * 10000.0
        net_y = float(item.get("net_wan") or 0) * 10000.0
        prod_y = float(item.get("production_wan") or 0) * 10000.0
        total_units += u
        sum_gross_yuan += gross_y
        sum_net_yuan += net_y
        sum_prod_yuan += prod_y
        rows.append(
            f"<tr>"
            f"<td>{e(item.get('level'))}</td>"
            f"<td>{e(item.get('line') or item.get('name'))}路</td>"
            f"<td>{u} 辆</td>"
            f"<td>{e(item.get('media_type') or '大三侧')}</td>"
            f"<td>{e(period_label)}</td>"
            f'<td class="tr">{num(gross_y, 0)}</td>'
            f'<td class="tr">{num(net_y, 0)}</td>'
            f'<td class="tr">{num(prod_y, 0)}</td>'
            f"</tr>"
        )

    for item in ctx["metro"]:
        u = int(item.get("units") or 1)
        gross_y = float(item.get("gross_wan") or 0) * 10000.0
        net_y = float(item.get("net_wan") or 0) * 10000.0
        prod_y = float(item.get("production_wan") or 0) * 10000.0
        total_units += u
        sum_gross_yuan += gross_y
        sum_net_yuan += net_y
        sum_prod_yuan += prod_y
        loc = f"{item.get('station') or ''}站 {item.get('exit') or ''}".strip() or str(item.get("name") or "—")
        rows.append(
            f"<tr>"
            f"<td>{e(item.get('level'))}</td>"
            f"<td>{e(loc)}</td>"
            f"<td>{u} 口</td>"
            f"<td>{e(item.get('media_type') or '地铁出入口')}</td>"
            f"<td>{e(period_label)}</td>"
            f'<td class="tr">{num(gross_y, 0)}</td>'
            f'<td class="tr">{num(net_y, 0)}</td>'
            f'<td class="tr">{num(prod_y, 0)}</td>'
            f"</tr>"
        )

    for g in (ctx["quote"].get("gift_items") or []):
        g_gross = float(g.get("gross_wan") or 0) * 10000.0
        rows.append(
            f'<tr class="gift-row">'
            f"<td>赠媒</td>"
            f"<td>{e(g.get('name') or g.get('id'))}</td>"
            f"<td>1 项</td>"
            f"<td>等值赠送</td>"
            f"<td>{e(period_label)}</td>"
            f'<td class="tr">{num(g_gross, 0)}</td>'
            f'<td class="tr">0（赠送）</td>'
            f'<td class="tr">0</td>'
            f"</tr>"
        )

    if ctx["agency_fee_wan"] > 0:
        ag_y = ctx["agency_fee_wan"] * 10000.0
        rows.append(
            f"<tr>"
            f"<td>服务费</td>"
            f"<td>4A 代理服务费（15%）</td>"
            f"<td>1 项</td>"
            f"<td>服务费</td>"
            f"<td>{e(period_label)}</td>"
            f'<td class="tr">—</td>'
            f'<td class="tr">{num(ag_y, 0)}</td>'
            f'<td class="tr">0</td>'
            f"</tr>"
        )

    unit_summary = []
    bus_u = sum(int(x.get("units") or 1) for x in ctx["bus"])
    metro_u = sum(int(x.get("units") or 1) for x in ctx["metro"])
    if bus_u:
        unit_summary.append(f"{bus_u} 辆")
    if metro_u:
        unit_summary.append(f"{metro_u} 口")
    unit_sum_text = " + ".join(unit_summary) or f"{total_units} 单元"

    # 每台/点位更换画面参考单价
    replace_fee = "7,500" if bus_u else "300"
    replace_unit = "辆" if bus_u else "口"
    logo_uri = asset_uri("logo-red.png")

    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{e(doc_title)} · {e(venue)}</title>
<style>{DIRECT_CONTRACT_CSS}</style>
</head>
<body>
<table class="page-shell">
<thead>
  <tr>
    <td class="hdr-cell">
      <div class="doc-header">
        <img src="{logo_uri}" alt="FLAIR MEDIA 新云传媒">
      </div>
    </td>
  </tr>
</thead>
<tbody>
<tr>
<td class="body-cell">
<div class="doc-body">
  <h1 class="contract-title">{e(doc_title)}</h1>

  <div class="meta-box-wrap">
    <table class="meta-box">
      <tr><td class="lbl">合同总价：</td><td class="val">人民币 {num(total_yuan, 2)} 元（{num(ctx["total_paid_wan"], 2)} 万元）</td></tr>
      <tr><td class="lbl">合同编号：</td><td class="val">{e(ctx["contract_no"])}</td></tr>
    </table>
  </div>

  <table class="party-box">
    <tr>
      <td style="width:68%">
        <div><b>甲方：</b>{e(venue)}（以实际签约主体为准）</div>
        <div><b>地址：</b>______________________________________________</div>
        <div><b>电话：</b>________________________</div>
        <div class="party-sep"></div>
        <div><b>乙方：</b><span class="ul">上海新云传媒股份有限公司</span></div>
        <div><b>地址：</b>上海市浦东新区（以签约盖章页登记地址为准）</div>
        <div><b>电话：</b>________________________</div>
      </td>
      <td style="width:32%;vertical-align:top">
        <div><b>广告品牌/项目：</b></div>
        <div style="margin-top:3mm;font-weight:700">{e(venue)}</div>
        <div style="margin-top:2mm;font-size:8.5pt;color:#555">行业：{e(ctx["industry"])}</div>
        <div style="margin-top:1mm;font-size:8.5pt;color:#555">方案编号：{e(ctx["run_id"])}</div>
      </td>
    </tr>
  </table>

  <p class="indent">本着平等、互惠、互利的原则，甲乙双方经友好协商，就甲方委托乙方发布户外广告事宜，签订本合同。</p>

  <h2>第一条：发布详情</h2>
  <table class="detail-tbl">
    <thead>
      <tr>
        <th rowspan="2" style="width:10%">线路类型</th>
        <th rowspan="2" style="width:22%">发布线路/点位</th>
        <th rowspan="2" style="width:10%">发布数量</th>
        <th rowspan="2" style="width:12%">媒体形式</th>
        <th rowspan="2" style="width:10%">发布期限</th>
        <th colspan="3">广告费用（人民币：元）</th>
      </tr>
      <tr>
        <th style="width:12%">发布费刊例</th>
        <th style="width:12%">发布费</th>
        <th style="width:12%">制作安装费</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
      <tr class="sum-row">
        <td colspan="2"><b>合计：</b></td>
        <td><b>{e(unit_sum_text)}</b></td>
        <td colspan="2">适用折扣：{e((ctx["quote"].get("discount_tier") or {}).get("label") or f"{int(round(ctx['discount']*100))}%")}</td>
        <td class="tr"><b>{num(ctx["rate_card_wan"] * 10000.0, 0)}</b></td>
        <td class="tr"><b>{num(ctx["media_net_wan"] * 10000.0, 0)}</b></td>
        <td class="tr"><b>{num(ctx["production_wan"] * 10000.0, 0)}</b></td>
      </tr>
      <tr class="final-row">
        <td colspan="2"><b>本合同最终执行总价<br>（优惠价）：</b></td>
        <td colspan="6" class="final-price">
          人民币（小写）：<b>￥{num(total_yuan, 2)} 元</b>（{num(ctx["total_paid_wan"], 2)} 万元）<br>
          人民币（大写）：<b>{e(rmb_upper(total_yuan))}</b>
        </td>
      </tr>
    </tbody>
  </table>

  <p class="indent">发布日期：{e(ctx["weeks"])} 周（{e(ctx["start_date"])} 至 {e(ctx["end_date"])}，共 {e(ctx["total_days"])} 天）。</p>
  <p class="indent">实际发布日期以乙方提供合同内最后一辆车/最后一个点位的施工照当日起开始计算（施工照夜间拍摄次日白天提供），如分批次发布则以乙方提供每批次最后一辆车/最后一个点位的施工照当日起开始计算，同时乙方出具相应的上画报告；如因甲方原因未能在合同约定的发布时间完成上画，甲方自行承担相应责任，逾期达 10 个工作日，则广告发布期按合同约定发布期的第 10 个工作日起计算，且乙方有权单方解除合同。</p>
  <p class="indent">除合同包含的 <u>1</u> 次制作安装外，甲方如需另行更换画面，则由乙方负责制作及安装，按先付款后制作原则，甲方应以 <u>{replace_fee}</u> 元/{replace_unit}的制作安装费支付给乙方，乙方在收到甲方的制作费后安排制作，否则广告制作日期顺延。</p>

  <h2>第二条：付款时间（需要详细标注付款时间）</h2>
  <p class="clause">1、甲方在合同签定、广告正式上刊前 <u>15</u> 天之内，即 <u>{e(prepay_date)}</u> 前应向乙方支付合同金额的 <u>50</u>%，即人民币 <u>{num(prepay_yuan, 2)}</u> 元作为预付款，乙方在收到甲方预付款后安排制作，甲方逾期付款则乙方广告制作日期相应顺延；若甲方逾期支付达 10 个工作日的，乙方有权不保留原约定媒体发布位置，并有权采取暂停广告、顺延广告发布及单方解除合同等措施。</p>
  <p class="clause">2、甲方在广告正式发布并验收后 <u>1</u> 个月内，即 <u>{e(final_date)}</u> 前向乙方支付合同金额的 <u>50</u>%，即人民币 <u>{num(final_yuan, 2)}</u> 元。</p>

  <p class="indent">乙方应开具增值税 <u>专用</u> 发票（增值税税率为 6%）给甲方，如需开具增值税专用发票请填写以下开票信息：</p>
  <table class="invoice-tbl">
    <tr>
      <td style="width:50%">
        <div><b>甲方名称：</b>{e(venue)}</div>
        <div><b>纳税人识别号：</b>__________________________</div>
        <div><b>地址、电话：</b>____________________________</div>
        <div><b>开户银行及账号：</b>________________________</div>
      </td>
      <td style="width:50%">
        <div><b>乙方名称：</b>上海新云传媒股份有限公司</div>
        <div><b>纳税人识别号：</b>__________________________</div>
        <div><b>地址、电话：</b>____________________________</div>
        <div><b>开户银行及账号：</b>________________________</div>
      </td>
    </tr>
  </table>

  <h2>第三条：甲方的权利和义务</h2>
  <p class="clause">1、甲方应保证广告画面内容符合《中华人民共和国广告法》及有关法律、法规的规定。</p>
  <p class="clause">2、甲方应严格按本合同约定的付款方式，按时向乙方支付各项费用，不得拖延。甲方逾期付款超过三十天（除首付款外），乙方有权解除合同。合同自乙方解除合同通知书送达到甲方时合同解除。</p>
  <p class="clause">3、本合同签订后，甲方应在 <u>{e(material_date)}</u> 之前，将甲方的营业执照复印件、发布广告客户的营业执照复印件、商标注册证明及审批时所需一切证明文件（包括但不限于医疗广告许可证、卫生许可证、肖像权、售楼证、地名委托证书等），及广告画面的设计稿或设计元素提交给乙方。</p>
  <p class="clause">4、甲方应在收到乙方广告小样后两天内完成审核确认工作，甲方逾期审核视为甲方对乙方制作的广告小样已经确认。设计的样稿必须由甲方签字或盖章书面确认方能进行制作、发布。</p>
  <p class="clause">5、广告制作及安装完毕后，乙方应以书面形式通知甲方进行验收，甲方应在收到乙方验收通知后两天内完成验收工作；甲方如逾期验收，则视为甲方验收合格。</p>
  <p class="clause">6、如果甲方违背本条第 1、2、3、4、5 条款导致广告发布迟延的，则广告发布日期仍按本合同约定的广告发布日开始计算，甲方仍应承担本合同约定的广告发布日至实际广告发布日止的广告发布费。</p>
  <p class="clause">7、如因甲方提供的广告画面因内容失实及相关等问题而导致的一切法律责任，由甲方承担。</p>
  <p class="clause">8、甲方不负任何广告位的安全责任。</p>

  <h2>第四条：乙方的权利和义务</h2>
  <p class="clause">1、乙方有权审核甲方所发布的广告设计稿（附加），有权拒绝发布违反《中华人民共和国广告法》及相关法律法规规定的广告。</p>
  <p class="clause">2、甲方逾期付款，乙方有权撤下广告画面，甲方付清应付款后，乙方再行恢复广告画面。因广告画面撤下、再次上刊产生的费用及广告画面撤下期间的广告发布费均由甲方承担。</p>
  <p class="clause">3、乙方保证用于甲方发布广告的车辆车貌完好、点位设施正常，确保画面效果。</p>
  <p class="clause">4、由于公交及户外媒体特殊性，如遇车辆碰擦、损坏广告画面、车辆调动等原因而导致广告无法正常发布造成发布日期减少的，乙方负责及时修复，并按损一补一的方式补偿给甲方。</p>
  <p class="clause">5、如发布媒体因政府干预或遇节假日停运等原因导致乙方无法如期发布本合同所规定广告，乙方有权将该发布期顺延。</p>
  <p class="clause">6、如遇自然条件影响，比如地震、雨天、暴风雨等，无法实施广告安装的，则发布期限顺延。</p>
  <p class="clause">7、若甲方自乙方盖章签出合同之日起 15 个工作日内未签回合同，则乙方有权将合同中所约定的广告媒体出售给第三方。</p>

  <h2>第五条：违约责任及争议处理</h2>
  <p class="clause">1、甲乙双方应严格履行本合同的各项条款，如有违反则构成违约。甲方逾期付款，应按应付款 3‰/日向乙方支付迟延履行金。</p>
  <p class="clause">2、本合同签订后，任何一方违反本合同之规定，导致广告不能发布或提前终止，或因一方违约导致对方单方面解除合同的，违约方应向守约方支付违约金，违约金为合同总金额的 20%。</p>
  <p class="clause">3、如因本合同发生纠纷，甲乙双方应友好协商解决，协商不成，可向乙方住所地上海市浦东新区人民法院提起诉讼。</p>

  <h2>第六条：免责条款</h2>
  <p class="clause">1、由于台风、地震和天气等不可抗拒的自然力因素，致使本合同未履行或未完全履行，甲乙双方均不承担违约责任。</p>
  <p class="clause">2、由于政府出台的有关新规定或其他新政策，致使本合同不能履行，则合同提前终止，甲、乙双方均不承担违约责任。甲、乙双方按实际发布天数结清广告款。</p>

  <h2>第七条：保密责任</h2>
  <p class="clause">1、本合同及相关内容和信息属商业机密，甲乙双方未经另一方书面许可，均不能向任何第三方泄漏，否则视为违约。</p>

  <h2>第八条：其他</h2>
  <p class="clause">1、合同履行期间，任何一方发给另一方的通知及书面文件均应签章。所有通知、书面文件及发票均以送达至双方所在地。任何一方物件送至对方合同上的地址，均视为送达，否则由此引起的法律后果由未通知方负责。各方地址与联系方式如下：</p>
  <table class="invoice-tbl">
    <tr>
      <td style="width:50%">
        <div><b>甲方联系人：</b>____________________________</div>
        <div><b>联系地址：</b>______________________________</div>
        <div><b>联系电话 / 邮箱：</b>_______________________</div>
      </td>
      <td style="width:50%">
        <div><b>乙方联系人：</b>上海新云传媒项目经理</div>
        <div><b>联系地址：</b>上海市浦东新区</div>
        <div><b>联系电话 / 邮箱：</b>_______________________</div>
      </td>
    </tr>
  </table>
  <p class="clause">2、未尽事宜，双方可另行协商。</p>
  <p class="clause">3、本合同一式四份，双方各执二份，具有同等法律效力。</p>
  <p class="clause">4、本合同经甲乙双方签章后生效。</p>

  <div class="sign-grid">
    <div class="sign-col">
      <div><b>甲方：</b>{e(venue)}</div>
      <div><b>签署人：</b>__________________________</div>
      <div><b>盖章：</b></div>
      <div class="sign-date"><b>日期：</b>{ctx["campaign_year"]} 年 ____ 月 ____ 日</div>
    </div>
    <div class="sign-col">
      <div><b>乙方：</b>上海新云传媒股份有限公司</div>
      <div><b>签署人：</b>__________________________</div>
      <div><b>盖章：</b></div>
      <div class="sign-date"><b>日期：</b>{ctx["campaign_year"]} 年 ____ 月 ____ 日</div>
    </div>
  </div>
</div>
</td>
</tr>
</tbody>
</table>
</body>
</html>'''


DIRECT_CONTRACT_CSS = r'''
@page {
  size: A4 portrait;
  margin: 10mm 20mm 16mm 20mm;
  @bottom-center {
    content: counter(page);
    font-family: "SimSun", "Songti SC", serif;
    font-size: 9pt;
    color: #333;
  }
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0; background: #fff; color: #111;
  font-family: "SimSun", "STSong", "Noto Serif SC", "Microsoft YaHei", serif;
  font-size: 10.2pt; line-height: 1.7;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.page-shell { width: 100%; border-collapse: collapse; border: 0; }
.page-shell > thead { display: table-header-group; }
.page-shell > thead td.hdr-cell { padding: 0 0 5mm 0; border: 0; }
.page-shell > tbody td.body-cell { padding: 0; border: 0; }
.doc-header {
  display: flex; justify-content: flex-end; align-items: flex-end;
  border-bottom: 0.75pt solid #666; padding-bottom: 1.5mm;
}
.doc-header img { height: 10.5mm; }
.contract-title {
  text-align: center; font-size: 16pt; font-weight: 700;
  letter-spacing: 0.12em; margin: 0 0 6mm;
  font-family: "Microsoft YaHei", "SimHei", sans-serif;
}
.meta-box-wrap { display: flex; justify-content: flex-end; margin-bottom: 5mm; }
.meta-box { border: 1pt solid #222; border-collapse: collapse; min-width: 78mm; font-size: 9.5pt; }
.meta-box td { padding: 1.4mm 2.5mm; }
.meta-box .lbl { font-weight: 700; white-space: nowrap; }
.party-box { width: 100%; border-collapse: collapse; margin-bottom: 4mm; font-size: 9.8pt; }
.party-box td { border: 0.8pt solid #222; padding: 2.5mm 3.5mm; line-height: 1.7; }
.party-sep { border-top: 0.5pt dashed #999; margin: 2mm 0; }
.ul { text-decoration: underline; }
h2 {
  font-family: "Microsoft YaHei", "SimHei", sans-serif;
  font-size: 10.8pt; font-weight: 700; margin: 5mm 0 2mm;
  page-break-after: avoid;
}
p { margin: 1.4mm 0; text-align: justify; }
p.indent { text-indent: 2em; }
p.clause { padding-left: 1.6em; text-indent: -1.6em; }
.detail-tbl {
  width: 100%; border-collapse: collapse; margin: 2.5mm 0 3.5mm;
  font-size: 8.8pt; line-height: 1.45;
}
.detail-tbl thead { display: table-header-group; }
.detail-tbl tr { page-break-inside: avoid; }
.detail-tbl th, .detail-tbl td {
  border: 0.7pt solid #222; padding: 1.4mm 1.8mm; text-align: center;
}
.detail-tbl th { background: #f2f2f2; font-weight: 700; }
.detail-tbl td.tr { text-align: right; font-variant-numeric: tabular-nums; }
.detail-tbl .gift-row td { background: #fbf8f2; color: #555; }
.detail-tbl .sum-row td { background: #f7f7f7; }
.detail-tbl .final-row td { background: #fff; padding: 2.2mm 2.5mm; }
.detail-tbl .final-price { text-align: left; font-size: 9.6pt; line-height: 1.65; }
.invoice-tbl { width: 100%; border-collapse: collapse; margin: 2.5mm 0 4mm; font-size: 9.3pt; }
.invoice-tbl td { border: 0.7pt solid #444; padding: 2.5mm 3mm; line-height: 1.85; vertical-align: top; }
.sign-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 14mm;
  margin-top: 10mm; page-break-inside: avoid;
}
.sign-col { line-height: 2.3; font-size: 10pt; }
.sign-date { margin-top: 8mm; }
'''
