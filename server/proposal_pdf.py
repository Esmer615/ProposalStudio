# -*- coding: utf-8 -*-
"""模板化 PDF 生成门面：支持新云传媒 4 套官方模板（销售提案 + 3 份合同）。

所有模板内容均提取自 `docs/03-合同三份-脱敏版等9个文件`：
- `proposal`: 05-历史销售提案样本/饮用水客户-销售提案样本.pdf（16:9 横版 FLAIR MEDIA 销售提案）
- `contract_direct`: 03-合同三份-脱敏版/M3-直客合同-脱敏版.pdf（A4 竖版直客发布合同）
- `contract_4a_order`: 03-合同三份-脱敏版/M3-4A订单-脱敏版.pdf（A4 横版 4A 户外排期表/订单）
- `contract_4a_framework`: 03-合同三份-脱敏版/M3-4A框架-脱敏版.pdf（A4 竖版 4A 年度框架合同书 + 附件一）

所有数字严格来自 run payload，不在模板层重算。
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

from server.templates import (
    DOC_SPECS,
    VALID_DOC_TYPES,
    build_4a_framework_html,
    build_4a_order_html,
    build_direct_contract_html,
    build_sales_proposal_html,
    render_html_to_pdf,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPORT_DIR = PROJECT_ROOT / "data" / "exports" / "proposals"
PUBLIC_DIR = PROJECT_ROOT / "web" / "public" / "proposals"
DIST_DIR = PROJECT_ROOT / "web" / "dist" / "proposals"

# 模板版本号：升级后自动刷新旧缓存，避免返回旧版样式 PDF
TEMPLATE_VERSION = "v2-official-4templates"

# URL slug -> 内部 doc_type 映射
SLUG_TO_DOC_TYPE: Dict[str, str] = {
    "proposal": "proposal",
    "sales-proposal": "proposal",
    "contract-direct": "contract_direct",
    "contract_direct": "contract_direct",
    "contract-4a-order": "contract_4a_order",
    "contract_4a_order": "contract_4a_order",
    "contract-4a-framework": "contract_4a_framework",
    "contract_4a_framework": "contract_4a_framework",
}

_BUILDERS = {
    "proposal": build_sales_proposal_html,
    "contract_direct": build_direct_contract_html,
    "contract_4a_order": build_4a_order_html,
    "contract_4a_framework": build_4a_framework_html,
}


def normalize_doc_type(doc_type: str) -> str:
    key = SLUG_TO_DOC_TYPE.get(str(doc_type or "proposal").strip().lower())
    if not key or key not in _BUILDERS:
        raise ValueError(f"不支持的模板类型：{doc_type}，可选：{', '.join(VALID_DOC_TYPES)}")
    return key


def build_html(run: Dict[str, Any], doc_type: str = "proposal") -> str:
    key = normalize_doc_type(doc_type)
    return _BUILDERS[key](run)


def _safe_id(run: Dict[str, Any]) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(run.get("run_id") or "proposal"))


def _paths_for(run_id: str, doc_type: str) -> tuple[Path, Path, Path]:
    if doc_type == "proposal":
        base = run_id
    else:
        slug = DOC_SPECS[doc_type]["filename_prefix"]
        base = f"{run_id}-{slug}"
    return (
        EXPORT_DIR / f"{base}.html",
        EXPORT_DIR / f"{base}.pdf",
        EXPORT_DIR / f".{base}.ver",
    )


def _sync_public_copy(pdf_path: Path, run_id: str, doc_type: str) -> None:
    if doc_type != "proposal":
        return
    for target in (PUBLIC_DIR, DIST_DIR):
        try:
            target.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pdf_path, target / f"{run_id}.pdf")
        except OSError:
            pass


def generate_document_pdf(run: Dict[str, Any], doc_type: str = "proposal", force: bool = False) -> Path:
    key = normalize_doc_type(doc_type)
    run_id = _safe_id(run)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    html_path, pdf_path, ver_path = _paths_for(run_id, key)

    force_flag = force or bool(os.environ.get("PROPOSAL_PDF_FORCE"))
    cached_ver = ver_path.read_text(encoding="utf-8").strip() if ver_path.is_file() else ""
    if (
        not force_flag
        and cached_ver == TEMPLATE_VERSION
        and pdf_path.is_file()
        and pdf_path.stat().st_size > 1000
    ):
        _sync_public_copy(pdf_path, run_id, key)
        return pdf_path

    html_content = build_html(run, key)
    render_html_to_pdf(html_content, html_path, pdf_path)
    try:
        ver_path.write_text(TEMPLATE_VERSION, encoding="utf-8")
    except OSError:
        pass
    _sync_public_copy(pdf_path, run_id, key)
    return pdf_path


def generate_proposal_pdf(run: Dict[str, Any]) -> Path:
    """兼容旧调用：默认生成 16:9 销售提案 PDF。"""
    return generate_document_pdf(run, "proposal")


def default_doc_types_for_run(run: Dict[str, Any]) -> List[str]:
    """根据客户类型确定本次 run 默认生成的文档组合（其余模板在点击时按需懒生成）。"""
    plan = run.get("plan") or {}
    inputs = plan.get("inputs") or (run.get("inputs") or {}).get("request") or {}
    ctype = str(inputs.get("customer_type") or "direct").lower()
    if ctype == "4a":
        return ["proposal", "contract_4a_order", "contract_4a_framework"]
    return ["proposal", "contract_direct"]


def generate_run_pdfs(run: Dict[str, Any], doc_types: List[str] | None = None) -> Dict[str, Path]:
    """批量生成当前 run 对应的交付 PDF 集合。"""
    targets = doc_types or default_doc_types_for_run(run)
    out: Dict[str, Path] = {}
    for dt in targets:
        out[dt] = generate_document_pdf(run, dt)
    return out


__all__ = [
    "DOC_SPECS",
    "VALID_DOC_TYPES",
    "SLUG_TO_DOC_TYPE",
    "TEMPLATE_VERSION",
    "normalize_doc_type",
    "build_html",
    "generate_document_pdf",
    "generate_proposal_pdf",
    "default_doc_types_for_run",
    "generate_run_pdfs",
]


if __name__ == "__main__":
    import sys
    from agent.orchestration import get_run

    run_id = sys.argv[1] if len(sys.argv) > 1 else ""
    doc_type = sys.argv[2] if len(sys.argv) > 2 else "all"
    run = get_run(run_id) if run_id else None
    if not run:
        print("usage: python -m server.proposal_pdf <run_id> [all|proposal|contract_direct|contract_4a_order|contract_4a_framework]")
        raise SystemExit(2)
    if doc_type == "all":
        for dt, p in generate_run_pdfs(run, list(VALID_DOC_TYPES)).items():
            print(f"{dt}: {p}")
    else:
        print(generate_document_pdf(run, doc_type))
