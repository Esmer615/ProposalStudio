# -*- coding: utf-8 -*-
"""Skill 加载器：把 Our-agent-skills 变成 Agent 可渐进加载的数据。

一个 skill 是一个目录，至少包含：
    SKILL.md        人/LLM 可读的指令（YAML frontmatter + 正文）
    policy.json     确定性 Agent 用的机器可读策略（阈值/默认值/场景规则）

references/ 下的文件按需加载，避免一次性把所有细节塞进上下文。
archive/ 存放旧版技能，不参与加载。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from engine.config import PROJECT_ROOT

DEFAULT_SKILLS_ROOT = os.path.join(PROJECT_ROOT, "Our-agent-skills")
_FRONTMATTER_RE = re.compile(r"^﻿?---\s*\r?\n(.*?)\r?\n---\s*\r?\n", re.S)
_SKIP_DIRS = {"archive", "references", "__pycache__", "node_modules"}


class SkillError(Exception):
    """技能目录不合法（缺字段/路径越界/JSON 损坏）。"""


@dataclass
class SkillSpec:
    name: str
    description: str
    stage: str
    version: str
    order: int
    directory: str
    body: str
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    policy: Dict[str, Any] = field(default_factory=dict)
    references: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    guardrails: List[str] = field(default_factory=list)
    sha256: str = ""

    @property
    def skill_path(self) -> str:
        return os.path.join(self.directory, "SKILL.md")

    def prompt(self, include_references: bool = False) -> str:
        """给 LLM 的技能正文；默认只加载 SKILL.md（渐进披露）。"""
        parts = [
            f"# Skill: {self.name} (v{self.version})",
            self.body.strip(),
        ]
        if self.guardrails:
            parts.append("## 硬性约束\n" + "\n".join(f"- {g}" for g in self.guardrails))
        if include_references:
            for ref in self.references:
                try:
                    parts.append(f"## Reference: {ref}\n{self.read_reference(ref)}")
                except SkillError:
                    continue
        return "\n\n".join(p for p in parts if p.strip())

    def read_reference(self, relative_path: str) -> str:
        """读取 references/ 下的文件，拒绝路径穿越。"""
        base = os.path.realpath(self.directory)
        target = os.path.realpath(os.path.join(base, relative_path))
        if os.path.commonpath([base, target]) != base:
            raise SkillError(f"reference 路径越界：{relative_path}")
        if not os.path.isfile(target):
            raise SkillError(f"reference 不存在：{relative_path}")
        with open(target, encoding="utf-8") as f:
            return f.read()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "stage": self.stage,
            "version": self.version,
            "order": self.order,
            "directory": os.path.relpath(self.directory, PROJECT_ROOT).replace("\\", "/"),
            "references": list(self.references),
            "tools": list(self.tools),
            "outputs": list(self.outputs),
            "guardrails": list(self.guardrails),
            "policy_keys": sorted(self.policy.keys()),
            "sha256": self.sha256,
        }


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _parse_frontmatter(text: str, path: str) -> Tuple[Dict[str, Any], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise SkillError(f"{path} 缺少 YAML frontmatter（--- ... ---）")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"{path} frontmatter YAML 解析失败：{exc}") from exc
    if not isinstance(meta, dict):
        raise SkillError(f"{path} frontmatter 必须是对象")
    return meta, text[m.end():]


def _load_policy(directory: str) -> Dict[str, Any]:
    path = os.path.join(directory, "policy.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillError(f"{path} policy.json 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise SkillError(f"{path} policy.json 必须是对象")
    return data


def load_skill(directory: str) -> SkillSpec:
    skill_path = os.path.join(directory, "SKILL.md")
    text = _read_text(skill_path)
    meta, body = _parse_frontmatter(text, skill_path)

    name = str(meta.get("name") or "").strip()
    description = str(meta.get("description") or "").strip()
    stage = str(meta.get("stage") or "").strip()
    if not name:
        raise SkillError(f"{skill_path} 缺少 name")
    if not description:
        raise SkillError(f"{skill_path} 缺少 description")
    if not stage:
        raise SkillError(f"{skill_path} 缺少 stage")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
        raise SkillError(f"{skill_path} name 必须是 kebab-case：{name}")

    try:
        order = int(meta.get("order", 100))
    except (TypeError, ValueError):
        order = 100

    refs = meta.get("references") or []
    if not isinstance(refs, list):
        refs = [refs]
    refs = [str(x) for x in refs]

    policy = _load_policy(directory)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

    return SkillSpec(
        name=name,
        description=description,
        stage=stage,
        version=str(meta.get("version") or "1.0.0"),
        order=order,
        directory=os.path.abspath(directory),
        body=body.strip(),
        frontmatter=dict(meta),
        policy=policy,
        references=refs,
        tools=[str(x) for x in (meta.get("tools") or [])],
        outputs=[str(x) for x in (meta.get("outputs") or [])],
        guardrails=[str(x) for x in (meta.get("guardrails") or [])],
        sha256=sha,
    )


class SkillRegistry:
    """发现 / 加载 / 校验技能，并提供按阶段取用的接口。"""

    def __init__(self, root: Optional[str] = None) -> None:
        self.root = os.path.abspath(root or DEFAULT_SKILLS_ROOT)
        self._skills: Optional[Dict[str, SkillSpec]] = None
        self._by_stage: Dict[str, SkillSpec] = {}

    # ------------------------------------------------------------------ #
    # 发现
    # ------------------------------------------------------------------ #
    def discover(self, refresh: bool = False) -> Dict[str, SkillSpec]:
        if self._skills is not None and not refresh:
            return self._skills
        if not os.path.isdir(self.root):
            raise SkillError(f"技能根目录不存在：{self.root}")

        skills: Dict[str, SkillSpec] = {}
        for entry in sorted(os.listdir(self.root)):
            if entry in _SKIP_DIRS or entry.startswith("."):
                continue
            directory = os.path.join(self.root, entry)
            if not os.path.isdir(directory):
                continue
            if not os.path.isfile(os.path.join(directory, "SKILL.md")):
                continue
            skill = load_skill(directory)
            if skill.name in skills:
                raise SkillError(f"技能名重复：{skill.name}（{directory}）")
            skills[skill.name] = skill

        if not skills:
            raise SkillError(f"{self.root} 下没有找到 SKILL.md")

        by_stage: Dict[str, SkillSpec] = {}
        for skill in skills.values():
            if skill.stage in by_stage:
                raise SkillError(
                    f"stage 重复：{skill.stage}（{by_stage[skill.stage].name} / {skill.name}）"
                )
            by_stage[skill.stage] = skill

        self._skills = skills
        self._by_stage = by_stage
        return skills

    def ordered(self) -> List[SkillSpec]:
        return sorted(self.discover().values(), key=lambda s: (s.order, s.name))

    def stage(self, stage: str) -> SkillSpec:
        self.discover()
        try:
            return self._by_stage[stage]
        except KeyError as exc:
            raise SkillError(
                f"未知 stage：{stage}；可用：{', '.join(sorted(self._by_stage))}"
            ) from exc

    def policy(self, stage: str) -> Dict[str, Any]:
        return dict(self.stage(stage).policy or {})

    def prompt_for(self, stage: str, include_references: bool = False) -> str:
        return self.stage(stage).prompt(include_references=include_references)

    def load_reference(self, stage: str, relative_path: str) -> str:
        return self.stage(stage).read_reference(relative_path)

    # ------------------------------------------------------------------ #
    # 校验 / 清单
    # ------------------------------------------------------------------ #
    def validate(self) -> List[str]:
        errors: List[str] = []
        try:
            skills = self.discover(refresh=True)
        except SkillError as exc:
            return [str(exc)]

        orders = sorted(s.order for s in skills.values())
        if len(orders) != len(set(orders)):
            errors.append("skill order 不唯一，加载顺序不确定")

        for skill in skills.values():
            for ref in skill.references:
                try:
                    skill.read_reference(ref)
                except SkillError as exc:
                    errors.append(str(exc))
            if not skill.policy:
                errors.append(f"{skill.name} 缺少 policy.json（确定性策略）")
        return errors

    def manifest(self) -> Dict[str, Any]:
        skills = self.ordered()
        return {
            "schema_version": 1,
            "loader": "agent.skills.SkillRegistry",
            "root": os.path.relpath(self.root, PROJECT_ROOT).replace("\\", "/"),
            "load_order": [s.name for s in skills],
            "stages": [s.stage for s in skills],
            "skills": [s.to_dict() for s in skills],
            "validation_errors": self.validate(),
        }

    def summaries(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": s.name,
                "stage": s.stage,
                "version": s.version,
                "order": s.order,
                "description": s.description,
                "tools": s.tools,
                "outputs": s.outputs,
                "policy_keys": sorted(s.policy.keys()),
            }
            for s in self.ordered()
        ]


def load_default_registry() -> SkillRegistry:
    return SkillRegistry(DEFAULT_SKILLS_ROOT)


__all__ = [
    "DEFAULT_SKILLS_ROOT",
    "SkillError",
    "SkillSpec",
    "SkillRegistry",
    "load_skill",
    "load_default_registry",
]
