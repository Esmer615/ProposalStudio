# -*- coding: utf-8 -*-
"""命令行入口：本地演示 / 调试 / 批量跑 brief。

示例：
    .venv\\Scripts\\python.exe -m agent.cli --brief "客户是上海乐高乐园，预算200万，暑期8周，公交+地铁，要覆盖亲子家庭"
    .venv\\Scripts\\python.exe -m agent.cli --brief-file docs/brief.txt --allow-defaults --json out.json
    .venv\\Scripts\\python.exe -m agent.cli --skills
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

from .runtime import ProposalAgent
from .skills import load_default_registry


def _utf8_stdio() -> None:
    """Windows 终端默认 GBK，中文/百分比符号会炸；强制 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _read_text_arg(value: Optional[str]) -> str:
    if not value:
        return ""
    if value == "-":
        return sys.stdin.read()
    if os.path.isfile(value):
        with open(value, encoding="utf-8") as f:
            return f.read()
    return value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent.cli",
        description="提案分析 Agent：接收客户需求 -> 设计场景 -> 调用确定性引擎 -> 输出分析",
    )
    p.add_argument("-b", "--brief", help="客户需求文本；传 - 从 stdin 读，传路径则读文件")
    p.add_argument("--brief-file", help="客户需求文件路径（UTF-8）")
    p.add_argument("--request-file", help="结构化 PlanRequest JSON 文件")
    p.add_argument("--request-json", help="结构化 PlanRequest JSON 字符串")
    p.add_argument("--allow-defaults", action="store_true", help="缺少字段时用默认值并列出假设（默认严格提问）")
    p.add_argument("--max-scenarios", type=int, default=4, help="最多对比场景数（1–6，默认 4）")
    p.add_argument("--quick", action="store_true", help="只跑基准方案 + 弹性，不做场景对比")
    p.add_argument("--no-elasticity", action="store_true", help="不计算九档预算弹性")
    p.add_argument("--llm", choices=["auto", "off"], default="auto", help="auto=有 DEEPSEEK_API_KEY 就用 DeepSeek；off=强制规则")
    p.add_argument("--include-plan-artifacts", action="store_true", help="输出中附带完整 PlanResponse（体积大）")
    p.add_argument("--json", dest="json_out", help="把完整 AgentAnalysis 写到 JSON 文件")
    p.add_argument("--markdown", dest="md_out", help="把提案话术写到 Markdown 文件")
    p.add_argument("--print", dest="print_mode", choices=["markdown", "json", "none"], default="markdown")
    p.add_argument("--skills", action="store_true", help="打印技能清单后退出")
    p.add_argument("--skills-json", action="store_true", help="以 JSON 打印技能清单后退出")
    return p


def main(argv: Optional[list] = None) -> int:
    _utf8_stdio()
    args = build_parser().parse_args(argv)

    if args.skills or args.skills_json:
        reg = load_default_registry()
        manifest = reg.manifest()
        if args.skills_json:
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
        else:
            print(f"技能根目录：{manifest['root']}")
            print(f"加载顺序：{' -> '.join(manifest['load_order'])}")
            for s in manifest["skills"]:
                print(f"- {s['name']} (v{s['version']}, stage={s['stage']}, order={s['order']})")
                print(f"  {s['description']}")
            errors = manifest.get("validation_errors") or []
            if errors:
                print("\n校验错误：")
                for e in errors:
                    print(f"- {e}")
                return 1
        return 0

    structured: Dict[str, Any] = {}
    if args.request_file:
        with open(args.request_file, encoding="utf-8") as f:
            structured = json.load(f)
    elif args.request_json:
        structured = json.loads(args.request_json)

    brief_text = _read_text_arg(args.brief_file or args.brief)
    if not brief_text and not structured:
        print("缺少输入：用 --brief / --brief-file / --request-file 提供需求。", file=sys.stderr)
        return 1

    options: Dict[str, Any] = {
        "allow_defaults": bool(args.allow_defaults),
        "max_scenarios": args.max_scenarios,
        "mode": "quick" if args.quick else "full",
        "include_elasticity": not args.no_elasticity,
        "llm": args.llm,
        "include_plan_artifacts": bool(args.include_plan_artifacts),
    }
    payload = {"brief_text": brief_text, "request": structured, "options": options}
    result = ProposalAgent().run(payload)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    if args.md_out:
        with open(args.md_out, "w", encoding="utf-8") as f:
            f.write((result.get("narrative") or {}).get("markdown") or "")

    if args.print_mode == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.print_mode == "markdown":
        print((result.get("narrative") or {}).get("markdown") or "")

    if result.get("status") == "error":
        return 1
    if result.get("status") == "needs_clarification":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
