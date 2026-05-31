"""A7R2 domain configuration and constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set


MIN_TURNOVER_20D = 1_500_000_000
MIN_NEAR_HIGH_RATIO = 0.85
RSI_PERIOD = 14
MOMENTUM_LOOKBACK = 20
ENTRY_LIMIT_DEV_FROM_25 = 1.5

LEADER_CODES = {
    "5801", "5802", "5803", "5805",
    "4063", "6146", "6315", "6323", "6383",
    "6857", "6920", "7735", "8035",
    "6501", "6503", "6504", "7011",
}

LEADER_SALES_GROWTH_FLOOR = -5.0
GENERAL_SALES_GROWTH_FLOOR = 0.0

ROA_HARD_MIN = 3.0
ROA_PASS_MIN = 5.0
ROA_STRONG_MIN = 7.0

DEV25_SOFT_1 = 4.0
DEV25_SOFT_2 = 7.0
DEV25_HARD_MAX = 9.0
REBOUND_DEV25_MAX = -4.0

DEV5_HARD_LOW = -2.0
DEV5_SOFT_MIN = 0.0
DEV5_SOFT_MAX = 4.0
DEV5_HARD_MAX = 5.0

MIN_RSI = 44.0
MAX_RSI = 65.0
MAX_DAY_GAIN = 5.5
TWO_DAY_GAIN_HARD_MAX = 7.0
PERCENT_B_SOFT_MAX = 1.02
PERCENT_B_HARD_MAX = 1.15
PER_HARD_EXCLUDE = 70.0
PER_HARD_EXCLUDE_DEV25 = 6.0
PER_HARD_EXCLUDE_RSI = 60.0

MA25_SLOPE_MIN = 0.15
MA75_SLOPE_MIN = -0.10
NEAR_HIGH_MIN = 0.87

SOFT_FAIL_NEAR_PASS_MAX = 1
BB_PERIOD = 20
BB_STD = 2.0
HORIZONS = [1, 3, 5, 10, 20]
WINDOWS = [5, 10, 20]

CATEGORY_PRIORITY: Dict[str, int] = {
    "下降トレンド": 1,
    "押し目未完成": 2,
    "過熱": 3,
    "ファンダ注意": 4,
    "流動性不足": 5,
    "リバ候補": 6,
    "判定保留": 7,
}


@dataclass(frozen=True)
class A7R2Config:
    min_turnover_20d: int = MIN_TURNOVER_20D
    min_near_high_ratio: float = MIN_NEAR_HIGH_RATIO
    rsi_period: int = RSI_PERIOD
    momentum_lookback: int = MOMENTUM_LOOKBACK
    entry_limit_dev_from_25: float = ENTRY_LIMIT_DEV_FROM_25
    leader_codes: Set[str] = field(default_factory=lambda: set(LEADER_CODES))
    leader_sales_growth_floor: float = LEADER_SALES_GROWTH_FLOOR
    general_sales_growth_floor: float = GENERAL_SALES_GROWTH_FLOOR
    roa_hard_min: float = ROA_HARD_MIN
    roa_pass_min: float = ROA_PASS_MIN
    roa_strong_min: float = ROA_STRONG_MIN
    dev25_soft_1: float = DEV25_SOFT_1
    dev25_soft_2: float = DEV25_SOFT_2
    dev25_hard_max: float = DEV25_HARD_MAX
    rebound_dev25_max: float = REBOUND_DEV25_MAX
    dev5_hard_low: float = DEV5_HARD_LOW
    dev5_soft_min: float = DEV5_SOFT_MIN
    dev5_soft_max: float = DEV5_SOFT_MAX
    dev5_hard_max: float = DEV5_HARD_MAX
    min_rsi: float = MIN_RSI
    max_rsi: float = MAX_RSI
    max_day_gain: float = MAX_DAY_GAIN
    two_day_gain_hard_max: float = TWO_DAY_GAIN_HARD_MAX
    percent_b_soft_max: float = PERCENT_B_SOFT_MAX
    percent_b_hard_max: float = PERCENT_B_HARD_MAX
    per_hard_exclude: float = PER_HARD_EXCLUDE
    per_hard_exclude_dev25: float = PER_HARD_EXCLUDE_DEV25
    per_hard_exclude_rsi: float = PER_HARD_EXCLUDE_RSI
    ma25_slope_min: float = MA25_SLOPE_MIN
    ma75_slope_min: float = MA75_SLOPE_MIN
    near_high_min: float = NEAR_HIGH_MIN
    soft_fail_near_pass_max: int = SOFT_FAIL_NEAR_PASS_MAX
    bb_period: int = BB_PERIOD
    bb_std: float = BB_STD
    horizons: List[int] = field(default_factory=lambda: list(HORIZONS))
    windows: List[int] = field(default_factory=lambda: list(WINDOWS))
    category_priority: Dict[str, int] = field(default_factory=lambda: dict(CATEGORY_PRIORITY))
