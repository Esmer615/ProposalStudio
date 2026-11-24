# -*- coding: utf-8 -*-
"""新云传媒官方 PDF 模板包（基于比赛资料包 4 份真实样本提取）。

包含：
- `sales_proposal`: 历史销售提案样本（16:9 横版 FLAIR MEDIA 提案）
- `contract_direct`: M3-直客合同（A4 竖版 户外/公交广告发布合同）
- `contract_4a_order`: M3-4A订单（A4 横版 Proposed Outdoor Spot Plan 户外排期表）
- `contract_4a_framework`: M3-4A框架（A4 竖版 年度户外广告投放及制作框架合同书 + 附件一）
"""
from .common import DOC_SPECS, VALID_DOC_TYPES, render_html_to_pdf
from .sales_proposal import build_sales_proposal_html
from .contract_direct import build_direct_contract_html
from .contract_4a_order import build_4a_order_html
from .contract_4a_framework import build_4a_framework_html

__all__ = [
    "DOC_SPECS",
    "VALID_DOC_TYPES",
    "render_html_to_pdf",
    "build_sales_proposal_html",
    "build_direct_contract_html",
    "build_4a_order_html",
    "build_4a_framework_html",
]
