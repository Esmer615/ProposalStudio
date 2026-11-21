# -*- coding: utf-8 -*-
"""引擎集中配置常量（数据 / 等级映射 / 曝光代理 / 折扣 / 排期 / 效果）。

本文件是所有“业务假设”的单一事实来源（single source of truth）：
- 对应文档都标注 source / assumption，便于答辩逐条摊开。
- 地铁 lineLevel 2=A++ / 3=A+ 为显式假设，集中于此（契约 §2.6 要求）。
"""
from __future__ import annotations

import os

# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CONFIG_DIR = os.path.join(DATA_DIR, "config")
VENUE_DIR = os.path.join(CONFIG_DIR, "venues")
SNAPSHOT_DIR = os.path.join(DATA_DIR, "snapshots")
PROCESSED_DIR = os.path.join(DATA_DIR, "processed")
GEO_DIR = os.path.join(DATA_DIR, "geo")

# --------------------------------------------------------------------------- #
# 公交 / 地铁 等级映射（显式假设）
# --------------------------------------------------------------------------- #
# 公交：lineLevel -> 等级  （1=S, 2=A++, 3=A+, 5=AA, 6=unknown）
BUS_LEVEL_MAP = {
    1: "S",
    2: "A++",
    3: "A+",
    5: "AA",
    6: "unknown",
}
# 地铁：2=A++ / 3=A+ （合同口径的“假设”，页面需标注）
METRO_LEVEL_MAP = {
    2: "A++",
    3: "A+",
}
# level 顺序（用于稳定排序 / 配比）
LEVEL_ORDER = ("S", "A++", "A+", "AA", "unknown")

# --------------------------------------------------------------------------- #
# 曝光代理（人次/天，按等级；线路级客流经验值，非实测）
# --------------------------------------------------------------------------- #
# 公交：S 58000 / A++ 48000 / A+ 38000 / AA 不进入曝光主线（被排除）
BUS_EXPOSURE = {"S": 58000, "A++": 48000, "A+": 38000, "AA": 0, "unknown": 0}
# 地铁：A++ 90000 / A+ 55000（每口）
METRO_EXPOSURE = {"A++": 90000, "A+": 55000}

# --------------------------------------------------------------------------- #
# 效果模型参数
# --------------------------------------------------------------------------- #
REACH_CAP = 0.82          # 物理媒体到达率上限（contract 明确 0.82）
VIEW_RATE_BUS = 0.60
VIEW_RATE_METRO = 0.50
K_EFF_DUAL_FACTOR = 1.10   # 双媒体时 k_eff = k * 1.10

# --------------------------------------------------------------------------- #
# 刊例价与折扣（首选项 data/config/rate_card_2027.json；此为内置回退）
# --------------------------------------------------------------------------- #
DEFAULT_RATE_CARD = {
    "bus": {"S": 6.0, "A++": 5.0, "A+": 4.0},
    "metro": {"A++": 30.0, "A+": 20.0},
    "production_bus_per_vehicle_wan": 0.75,
    "production_metro_per_gate_wan": 0.03,
}
# 折扣档位（全单刊例总额落档；88/83/78/73/68%）
DISCOUNT_TIERS = [
    {"label": "88%", "min_gross_wan": 0, "max_gross_wan": 199, "rate": 0.88},
    {"label": "83%", "min_gross_wan": 200, "max_gross_wan": 349, "rate": 0.83},
    {"label": "78%", "min_gross_wan": 350, "max_gross_wan": 499, "rate": 0.78},
    {"label": "73%", "min_gross_wan": 500, "max_gross_wan": 699, "rate": 0.73},
    {"label": "68%", "min_gross_wan": 700, "max_gross_wan": None, "rate": 0.68},
]
# 折扣不动点初值（合约：start 88%）
DISCOUNT_START = 0.88
AGENCY_FEE_RATE = 0.15      # 仅 4a
GIFT_RATE = 0.05            # 满额赠：折后 5% 等值点位

# --------------------------------------------------------------------------- #
# 求解约束
# --------------------------------------------------------------------------- #
BUS_MAX_UNITS_PER_LINE = 4        # 单线最多投放车辆（防止“一条线包圆”）
METRO_MAX_UNITS_PER_EXIT = 2      # 单口最多口数（契约：0..min(free,2)）
BUS_MIN_LINES = 4
BUS_MAX_LINES = 35
METRO_MIN_STATIONS = 2
METRO_MAX_STATIONS = 24
BUS_COMPANY_CAP = 15              # 单运营公司车辆上限
BUS_INSTALL_NIGHTS = 10
METRO_INSTALL_NIGHTS = 10
BUS_PER_NIGHT = 20
METRO_PER_NIGHT = 10
RAIN_BUFFER_NIGHTS = 2

# 等级配比硬约束（可随 media 规模自动放宽）
BUS_HIGH_SHARE_LO = 0.35   # bus S+A++ 占比下限
BUS_HIGH_SHARE_HI = 0.80   # bus S+A++ 占比上限
METRO_HIGH_SHARE_LO = 0.20  # metro A++ 占比下限
METRO_HIGH_SHARE_HI = 0.90  # metro A++ 占比上限

# 槽位衰减（同点重复投放的边际递减）
SLOT_DECAY = 0.72

# --------------------------------------------------------------------------- #
# 确定性参数
# --------------------------------------------------------------------------- #
CP_SAT_SEED = 42
CP_SAT_WORKERS = 1
CP_SAT_TIME_LIMIT_MS = 600
SOLVE_TIME_LIMIT_MS = 600

# 候选预过滤上限（性能保护：bus 430 条 / metro 861 条 → 预过滤 top N）
PREFILTER_BUS = 100
PREFILTER_METRO = 120

# --------------------------------------------------------------------------- #
# 公交运营公司 -> 地理区域代理（当 real geo 缺失时，schematic）
# --------------------------------------------------------------------------- #
COMPANY_REGION = {
    "巴士一公司": "杨浦-虹口",
    "巴士二公司": "黄浦-静安",
    "巴士三公司": "长宁-普陀",
    "巴士四公司": "徐汇-闵行",
    "巴士五公司": "宝山-闸北",
    "杨高公交": "杨浦-浦东",
    "上南公交": "浦东-上南",
    "南汇公交": "浦东-南汇",
    "金高公交": "浦东-金桥",
    "春秋国旅": "观光",
    "巴士旅游": "观光",
}

# 地铁 districtname 方括号代码 -> 区县（best-effort，schematic）
# 红豆地铁快照仅存 [1]..[22] 代码，无人类可读区县；按上海行政区顺序近似映射。
METRO_DISTRICT_CODE_MAP = {
    "[1]": "黄浦区",
    "[2]": "徐汇区",
    "[3]": "长宁区",
    "[4]": "静安区",
    "[5]": "普陀区",
    "[6]": "虹口区",
    "[7]": "杨浦区",
    "[8]": "闵行区",
    "[9]": "宝山区",
    "[10]": "嘉定区",
    "[11]": "浦东新区",
    "[12]": "金山区",
    "[13]": "松江区",
    "[14]": "青浦区",
    "[15]": "奉贤区",
    "[16]": "崇明区",
    "[17]": "浦东新区",
    "[18]": "浦东新区",
    "[19]": "浦东新区",
    "[20]": "浦东新区",
    "[21]": "闵行区",
    "[22]": "宝山区",
}


def bus_region(company: str) -> str:
    return COMPANY_REGION.get(company, "其他")


def metro_district(code: str) -> str:
    c = (code or "").strip()
    return METRO_DISTRICT_CODE_MAP.get(c, "浦东新区")
