# -*- coding: utf-8 -*-
"""PM Skill 加载与校验

PM 只写 Markdown（YAML frontmatter + 正文），不需要会编程。
本模块负责：
  1. 解析 frontmatter
  2. 严格校验字段（缺字段/类型错 -> 明确报错，绝不静默）
  3. 转换成求解器 Config + 效果模型 ReachConfig
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict

# 允许的行业枚举（与赛题一致）
INDUSTRIES = {"银行保险", "食品饮料", "保健品", "私立医院", "乐园"}

# 必填字段 -> (类型, 校验函数)
REQUIRED: Dict[str, Any] = {
    "industry": (str, lambda v: v in INDUSTRIES),
    "target_population": (int, lambda v: 100_000 <= v <= 50_000_000),
    "reach_k": (float, lambda v: 50 <= v <= 5000),
    "high_share": (list, lambda v: len(v) == 2 and 0 <= v[0] <= v[1] <= 1),
    "level_weights": (dict, lambda v: all(k in ("S", "A++", "A+", "AA") for k in v)),
}

# 可选字段 -> (类型, 默认值)
OPTIONAL: Dict[str, Any] = {
    "budget_default": (float, 100.0),
    "compliance_forbidden": (list, []),
    "region_weights": (dict, {}),
    "media_preference": (dict, {"bus": 1.0, "metro": 0.0}),
    "messaging": (list, []),
}


class SkillError(ValueError):
    """Skill 格式错误（面向 PM 的可读报错）"""


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 --- 包裹的 YAML frontmatter（无 PyYAML 依赖的简化实现）"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        raise SkillError("缺少 frontmatter：文件必须以 --- 开头，并以 --- 结束")
    head, body = m.group(1), m.group(2)
    data: Dict[str, Any] = {}
    stack = [data]
    cur_indent = 0
    for raw in head.split("\n"):
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()

        # 列表项
        if line.startswith("- "):
            val = _coerce(line[2:].strip())
            if not isinstance(stack[-1], list):
                raise SkillError(f"列表项出现在非列表上下文: {line}")
            stack[-1].append(val)
            continue

        if ":" not in line:
            raise SkillError(f"无法解析的行（缺少冒号）: {line}")
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()

        while indent < cur_indent and len(stack) > 1:
            stack.pop()
            cur_indent -= 2

        if val == "":
            # 可能是下一层 map，也可能是 """ - """ 列表；先建 dict，稍后按需转
            stack[-1][key] = {}
            stack.append(stack[-1][key])
            cur_indent = indent + 2
        else:
            stack[-1][key] = _coerce(val)
    return data, body


def _coerce(raw: str):
    """把 YAML 标量转成 Python 值"""
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [_coerce(x.strip()) for x in inner.split(",")] if inner else []
    if raw.startswith("{") and raw.endswith("}"):
        inner = raw[1:-1].strip()
        out = {}
        if inner:
            for pair in inner.split(","):
                k, _, v = pair.partition(":")
                out[k.strip()] = _coerce(v.strip())
        return out
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    low = raw.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def load_skill(path: str) -> dict:
    """读一个 skill 文件并校验，返回规范化的 dict"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    data, body = _parse_frontmatter(text)

    errors = []
    for key, (typ, check) in REQUIRED.items():
        if key not in data:
            errors.append(f"缺必填字段 `{key}`（类型 {typ.__name__}）")
            continue
        v = data[key]
        # int 可以合法填入 float 字段（YAML 里写 320 不必写成 320.0）
        typ_ok = isinstance(v, typ) or (typ is float and isinstance(v, int) and not isinstance(v, bool))
        if not typ_ok or (isinstance(v, bool) and typ is not bool):
            errors.append(f"字段 `{key}` 类型错误：需要 {typ.__name__}，实际 {type(v).__name__}")
        elif not check(v):
            errors.append(f"字段 `{key}` 值不合法：{v!r}")
    if errors:
        raise SkillError(f"{os.path.basename(path)} 校验失败：\n  - " + "\n  - ".join(errors))

    for key, (typ, default) in OPTIONAL.items():
        data.setdefault(key, default)

    data["messaging"] = _extract_messaging(body) or data.get("messaging", [])
    data["_source"] = os.path.basename(path)
    return data


def _extract_messaging(body: str) -> list:
    """从正文「## 话术要点」小节提取列表项"""
    m = re.search(r"##\s*话术要点\s*\n(.*?)(?=\n##|\Z)", body, re.S)
    if not m:
        return []
    return [ln.strip()[1:].strip()
            for ln in m.group(1).split("\n")
            if ln.strip().startswith("-")]


def skill_to_config(skill: dict, budget: float | None = None):
    """skill -> (bus_optimizer.Config, effects_model.ReachConfig)"""
    from bus_optimizer import Config
    from effects_model import ReachConfig

    cfg = Config(
        budget=float(budget if budget is not None else skill["budget_default"]),
        weight=skill["level_weights"],
        high_share_lo=float(skill["high_share"][0]),
        high_share_hi=float(skill["high_share"][1]),
    )
    eff = ReachConfig(
        target_population=float(skill["target_population"]),
        k=float(skill["reach_k"]),
    )
    return cfg, eff


__all__ = ["load_skill", "skill_to_config", "SkillError", "INDUSTRIES"]