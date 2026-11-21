# -*- coding: utf-8 -*-
"""共享请求模型与常量。

这是 Lead 冻结的契约层：引擎/API/前端共用 docs/契约-v1.md。
内部求解模型可以有自己的 dataclass，但对外字段不得偏离本文件与契约文档。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

INDUSTRY = "乐园"

VENUES: Dict[str, Dict[str, Any]] = {
    "lego_shanghai": {
        "name": "上海乐高乐园",
        "district": "金山区",
        "short": "乐高",
    },
    "disney_shanghai": {
        "name": "上海迪士尼度假区",
        "district": "浦东新区",
        "short": "迪士尼",
    },
    "haichang_shanghai": {
        "name": "上海海昌海洋公园",
        "district": "浦东新区",
        "short": "海昌",
    },
}

MEDIA_LABELS = {"bus": "公交车身", "metro": "地铁出入口"}
MEDIA_TYPES = tuple(MEDIA_LABELS.keys())
CUSTOMER_TYPES = {"direct": "直客", "4a": "4A代理"}

BUDGET_MIN_WAN = 100.0
BUDGET_MAX_WAN = 500.0
DEFAULT_BUDGET_WAN = 500.0
DEFAULT_START_DATE = "2027-07-01"
DEFAULT_WEEKS = 8
ALLOWED_WEEKS = (2, 4, 6, 8, 12)

LEVEL_ORDER = ("S", "A++", "A+", "AA", "unknown")


class PlanError(Exception):
    """带错误码的引擎异常；server 会转成统一错误对象。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field: Optional[str] = None,
        suggestions: Optional[List[str]] = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.suggestions = suggestions or []
        self.recoverable = recoverable

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "field": self.field,
                "suggestions": self.suggestions,
                "recoverable": self.recoverable,
            }
        }


@dataclass
class PlanRequest:
    """对外请求（docs/契约-v1.md §1）。"""

    venue: str = "lego_shanghai"
    budget_wan: float = DEFAULT_BUDGET_WAN
    media: List[str] = field(default_factory=lambda: ["bus", "metro"])
    start_date: str = DEFAULT_START_DATE
    weeks: int = DEFAULT_WEEKS
    customer_type: str = "direct"
    industry: str = INDUSTRY
    locks: Dict[str, List[str]] = field(default_factory=lambda: {"include": [], "exclude": []})
    brief_text: Optional[str] = None

    # ------------------------------------------------------------------ #
    # 构造 / 校验
    # ------------------------------------------------------------------ #
    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "PlanRequest":
        raw = raw or {}
        locks = raw.get("locks") or {}
        req = cls(
            venue=str(raw.get("venue") or "lego_shanghai"),
            budget_wan=float(raw.get("budget_wan", DEFAULT_BUDGET_WAN)),
            media=list(raw.get("media") or ["bus", "metro"]),
            start_date=str(raw.get("start_date") or DEFAULT_START_DATE),
            weeks=int(raw.get("weeks", DEFAULT_WEEKS)),
            customer_type=str(raw.get("customer_type") or "direct"),
            industry=str(raw.get("industry") or INDUSTRY),
            locks={
                "include": [str(x) for x in (locks.get("include") or [])],
                "exclude": [str(x) for x in (locks.get("exclude") or [])],
            },
            brief_text=(str(raw["brief_text"]) if raw.get("brief_text") else None),
        )
        req.normalize()
        req.validate()
        return req

    def normalize(self) -> None:
        # 媒体去重排序，保证缓存键稳定
        seen = []
        for m in self.media:
            m = str(m).strip().lower()
            if m and m not in seen:
                seen.append(m)
        order = {m: i for i, m in enumerate(MEDIA_TYPES)}
        self.media = sorted(seen, key=lambda m: order.get(m, 99))

    def validate(self) -> None:
        if self.industry != INDUSTRY:
            raise PlanError(
                "VALIDATION_ERROR",
                f"当前版本仅支持行业：{INDUSTRY}",
                field="industry",
                suggestions=[INDUSTRY],
            )
        if self.venue not in VENUES:
            raise PlanError(
                "VALIDATION_ERROR",
                f"未知场馆：{self.venue}",
                field="venue",
                suggestions=list(VENUES.keys()),
            )
        if not (BUDGET_MIN_WAN <= self.budget_wan <= BUDGET_MAX_WAN):
            raise PlanError(
                "VALIDATION_ERROR",
                f"预算必须在 {BUDGET_MIN_WAN:.0f}–{BUDGET_MAX_WAN:.0f} 万之间",
                field="budget_wan",
                suggestions=["100", "200", "500"],
            )
        if not self.media:
            raise PlanError(
                "VALIDATION_ERROR",
                "至少选择一种媒体",
                field="media",
                suggestions=["bus", "metro", "bus+metro"],
            )
        bad = [m for m in self.media if m not in MEDIA_TYPES]
        if bad:
            raise PlanError(
                "VALIDATION_ERROR",
                f"未知媒体类型：{', '.join(bad)}",
                field="media",
                suggestions=list(MEDIA_TYPES),
            )
        try:
            start = date.fromisoformat(self.start_date)
        except ValueError:
            raise PlanError(
                "VALIDATION_ERROR",
                "start_date 必须是 YYYY-MM-DD",
                field="start_date",
                suggestions=[DEFAULT_START_DATE],
            )
        if start.year != 2027:
            raise PlanError(
                "VALIDATION_ERROR",
                "当前赛题档期限定在 2027 年内",
                field="start_date",
                suggestions=["2027-07-01"],
            )
        if self.weeks not in ALLOWED_WEEKS:
            raise PlanError(
                "VALIDATION_ERROR",
                f"weeks 必须是 {ALLOWED_WEEKS} 之一",
                field="weeks",
                suggestions=[str(w) for w in ALLOWED_WEEKS],
            )
        if self.customer_type not in CUSTOMER_TYPES:
            raise PlanError(
                "VALIDATION_ERROR",
                "customer_type 必须是 direct 或 4a",
                field="customer_type",
                suggestions=list(CUSTOMER_TYPES.keys()),
            )

    # ------------------------------------------------------------------ #
    # 派生字段
    # ------------------------------------------------------------------ #
    @property
    def end_date(self) -> str:
        d = date.fromisoformat(self.start_date) + timedelta(days=self.weeks * 7 - 1)
        return d.isoformat()

    @property
    def months(self) -> int:
        """计费月数：按覆盖的自然月向上取整，最少 1 个月。"""
        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        return max(1, (end.year - start.year) * 12 + end.month - start.month + 1)

    @property
    def venue_name(self) -> str:
        return VENUES[self.venue]["name"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "industry": self.industry,
            "venue": self.venue,
            "venue_name": self.venue_name,
            "budget_wan": self.budget_wan,
            "media": list(self.media),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "weeks": self.weeks,
            "months": self.months,
            "customer_type": self.customer_type,
            "customer_type_label": CUSTOMER_TYPES[self.customer_type],
            "locks": {"include": list(self.locks["include"]), "exclude": list(self.locks["exclude"])},
        }

    def cache_key(self) -> str:
        import json

        payload = {
            "v": 1,
            "venue": self.venue,
            "budget": round(self.budget_wan, 2),
            "media": self.media,
            "start": self.start_date,
            "weeks": self.weeks,
            "customer_type": self.customer_type,
            "locks": self.locks,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "INDUSTRY",
    "VENUES",
    "MEDIA_LABELS",
    "MEDIA_TYPES",
    "CUSTOMER_TYPES",
    "BUDGET_MIN_WAN",
    "BUDGET_MAX_WAN",
    "DEFAULT_BUDGET_WAN",
    "DEFAULT_START_DATE",
    "DEFAULT_WEEKS",
    "ALLOWED_WEEKS",
    "LEVEL_ORDER",
    "PlanError",
    "PlanRequest",
]
