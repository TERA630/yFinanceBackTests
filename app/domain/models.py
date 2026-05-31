"""Domain models for Backtest A screening results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ReasonItem:
    category: str
    message: str
    is_hard: bool = False
    priority: int = 99


@dataclass
class ScreenResult:
    code: str
    name: str
    symbol: str
    trade_date: str
    day_open: Optional[float]
    day_high: Optional[float]
    day_low: Optional[float]
    day_close: Optional[float]
    ma5: Optional[float]
    ma25: Optional[float]
    ma75: Optional[float]
    dev5: Optional[float]
    dev25: Optional[float]
    roa_pct: Optional[float]
    rsi: Optional[float]
    momentum_pct: Optional[float]
    per: Optional[float]
    pbr: Optional[float]
    sales_growth_pct: Optional[float]
    avg_turnover_20d: Optional[float]
    near_high_ratio: Optional[float]
    ma25_slope_pct: Optional[float]
    ma75_slope_pct: Optional[float]
    day_change_pct: Optional[float]
    volume_ratio_20d: Optional[float]
    close_position_pct: Optional[float]
    prev_close: Optional[float]
    passed: bool
    near_pass: bool
    score: int
    reason_items: List[ReasonItem] = field(default_factory=list)
    primary_category: Optional[str] = None
    primary_reason: Optional[str] = None
    secondary_reasons: List[str] = field(default_factory=list)
    watch_status: Optional[str] = None
    entry_limit_low: Optional[float] = None
    entry_limit_high: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_percent_b: Optional[float] = None
    two_day_gain_pct: Optional[float] = None
