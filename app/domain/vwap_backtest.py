"""Pure calculations for the VWAP-maintenance backtest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


ENTRY_PREV_CLOSE = "prev_close"
ENTRY_1100 = "11:00"
ENTRY_1400 = "14:00"
ENTRY_TIMES = (ENTRY_PREV_CLOSE, ENTRY_1100, ENTRY_1400)
HORIZONS = (1, 5, 10, 15)
EXCURSION_WINDOWS = (5, 10, 15)
MA5_SLOWDOWN_IGNORE = "ignore"
MA5_SLOWDOWN_REJECT_ANY = "reject_any"
MA5_SLOWDOWN_ALLOW_ONE = "allow_one"
MA5_SLOWDOWN_ALLOW_THREE_DAYS_AGO = "allow_three_days_ago"
MA5_SLOWDOWN_ALLOW_PREVIOUS_DAY = "allow_previous_day"
MA5_SLOWDOWN_POLICIES = (
    MA5_SLOWDOWN_IGNORE,
    MA5_SLOWDOWN_REJECT_ANY,
    MA5_SLOWDOWN_ALLOW_ONE,
    MA5_SLOWDOWN_ALLOW_THREE_DAYS_AGO,
    MA5_SLOWDOWN_ALLOW_PREVIOUS_DAY,
)


@dataclass(frozen=True)
class A8BacktestConfig:
    start_date: str
    end_date: str
    dev25_min: float
    dev25_max: float
    entry_time: str
    lower_low_exclude_count: int = 0
    higher_high_exclude_count: int = 0
    require_vwap_confirmation: bool = True
    range_position_min_pct: Optional[float] = None
    require_ma5_slope_positive: bool = False
    ma5_slope_slowdown_policy: str = MA5_SLOWDOWN_IGNORE

    def validate(self) -> None:
        start = pd.Timestamp(self.start_date)
        end = pd.Timestamp(self.end_date)
        if start > end:
            raise ValueError("開始日は終了日以前にしてください。")
        if self.dev25_min >= self.dev25_max:
            raise ValueError("25日乖離率の最低値は最高値より小さくしてください。")
        if self.entry_time not in ENTRY_TIMES:
            raise ValueError(f"未対応のエントリー時刻です: {self.entry_time}")
        if not self.require_vwap_confirmation and self.entry_time == ENTRY_PREV_CLOSE:
            raise ValueError("VWAP維持確認なしでは、エントリー時刻を11:00または14:00にしてください。")
        if self.lower_low_exclude_count not in (0, 1, 2, 3):
            raise ValueError("安値切り下げ除外回数は0～3で指定してください。")
        if self.higher_high_exclude_count not in (0, 1, 2, 3):
            raise ValueError("高値更新条件は0～3で指定してください。")
        if self.range_position_min_pct is not None and self.range_position_min_pct not in (30, 40, 50, 60):
            raise ValueError("終端位置は30%、40%、50%、60%、または考慮なしで指定してください。")
        if not isinstance(self.require_ma5_slope_positive, bool):
            raise ValueError("5日線傾き条件は有効または無効で指定してください。")
        if self.ma5_slope_slowdown_policy not in MA5_SLOWDOWN_POLICIES:
            raise ValueError("5日線傾き鈍化条件は対応する選択肢から指定してください。")


# Compatibility alias for callers using the old name.
VwapBacktestConfig = A8BacktestConfig


@dataclass(frozen=True)
class EntryCandidate:
    signal_date: pd.Timestamp
    entry_date: pd.Timestamp
    previous_close: float
    ma25: float
    dev25_pct: float
    entry_price: float
    vwap: float


def calculate_vwap(rows: pd.DataFrame) -> Optional[float]:
    if rows is None or rows.empty:
        return None
    required = {"High", "Low", "Close", "Volume"}
    if not required.issubset(rows.columns):
        return None
    volume = pd.to_numeric(rows["Volume"], errors="coerce").fillna(0.0)
    total_volume = float(volume.sum())
    if total_volume <= 0:
        return None
    typical = (
        pd.to_numeric(rows["High"], errors="coerce")
        + pd.to_numeric(rows["Low"], errors="coerce")
        + pd.to_numeric(rows["Close"], errors="coerce")
    ) / 3.0
    value = float((typical * volume).sum() / total_volume)
    return None if pd.isna(value) else value


def intraday_entry(
    intraday: pd.DataFrame,
    trade_date: pd.Timestamp,
    cutoff: str,
) -> Optional[tuple[float, Optional[float]]]:
    if intraday is None or intraday.empty:
        return None
    day = intraday.loc[intraday.index.normalize() == pd.Timestamp(trade_date).normalize()]
    if day.empty:
        return None
    cutoff_time = pd.Timestamp(f"{pd.Timestamp(trade_date).date()} {cutoff}")
    # Intraday timestamps label the start of each bar. At 11:00, for example,
    # the 11:00 bar is not closed yet, so only earlier bars are usable.
    eligible = day.loc[day.index < cutoff_time]
    if eligible.empty:
        return None
    vwap = calculate_vwap(eligible)
    price = pd.to_numeric(eligible["Close"], errors="coerce").iloc[-1]
    if pd.isna(price):
        return None
    return float(price), vwap


def calculate_range_position_pct(
    low: Optional[float],
    high: Optional[float],
    price: Optional[float],
) -> Optional[float]:
    if low is None or high is None or price is None:
        return None
    if pd.isna(low) or pd.isna(high) or pd.isna(price):
        return None
    low_value = float(low)
    high_value = float(high)
    price_value = float(price)
    range_width = high_value - low_value
    if range_width <= 0:
        return None
    return (price_value - low_value) / range_width * 100.0


def is_ma5_slope_slowdown_excluded(
    current_slope_pct: Optional[float],
    previous_slope_pct: Optional[float],
    three_days_ago_slope_pct: Optional[float],
    policy: str,
) -> bool:
    if policy == MA5_SLOWDOWN_IGNORE:
        return False
    if current_slope_pct is None or previous_slope_pct is None or three_days_ago_slope_pct is None:
        return True

    slower_than_previous = current_slope_pct < previous_slope_pct
    slower_than_three_days_ago = current_slope_pct < three_days_ago_slope_pct
    if policy == MA5_SLOWDOWN_REJECT_ANY:
        return slower_than_previous or slower_than_three_days_ago
    if policy == MA5_SLOWDOWN_ALLOW_ONE:
        return slower_than_previous and slower_than_three_days_ago
    if policy == MA5_SLOWDOWN_ALLOW_THREE_DAYS_AGO:
        return slower_than_previous
    if policy == MA5_SLOWDOWN_ALLOW_PREVIOUS_DAY:
        return slower_than_three_days_ago
    raise ValueError(f"未対応の5日線傾き鈍化条件です: {policy}")


def intraday_range_position_pct(
    intraday: pd.DataFrame,
    trade_date: pd.Timestamp,
    cutoff: str,
    price: float,
) -> Optional[float]:
    if intraday is None or intraday.empty:
        return None
    day = intraday.loc[intraday.index.normalize() == pd.Timestamp(trade_date).normalize()]
    if day.empty:
        return None
    cutoff_time = pd.Timestamp(f"{pd.Timestamp(trade_date).date()} {cutoff}")
    eligible = day.loc[day.index < cutoff_time]
    if eligible.empty:
        return None
    high = pd.to_numeric(eligible["High"], errors="coerce").max()
    low = pd.to_numeric(eligible["Low"], errors="coerce").min()
    return calculate_range_position_pct(_float_or_none(low), _float_or_none(high), price)


def build_trade_metrics(daily: pd.DataFrame, entry_date: pd.Timestamp, entry_price: float) -> dict:
    metrics: dict[str, Optional[float]] = {}
    index = pd.DatetimeIndex(daily.index).normalize()
    positions = index.get_indexer([pd.Timestamp(entry_date).normalize()])
    pos = int(positions[0])
    if pos < 0 or entry_price <= 0:
        return empty_trade_metrics()

    for horizon in HORIZONS:
        target = pos + horizon
        sell_price = None if target >= len(daily) else _float_or_none(daily["Close"].iloc[target])
        metrics[f"sell_price_{horizon}d"] = sell_price
        metrics[f"profit_loss_{horizon}d"] = None if sell_price is None else sell_price - entry_price
        metrics[f"return_{horizon}d_pct"] = None if sell_price is None else (sell_price / entry_price - 1.0) * 100.0

    for window in EXCURSION_WINDOWS:
        if pos + window >= len(daily):
            metrics[f"minimum_price_{window}d"] = None
            metrics[f"maximum_price_{window}d"] = None
            metrics[f"max_drawdown_{window}d"] = None
            metrics[f"max_drawdown_{window}d_pct"] = None
            metrics[f"max_favorable_excursion_{window}d_pct"] = None
            metrics[f"first_touch_{window}d"] = None
            continue
        lows = pd.to_numeric(daily["Low"].iloc[pos + 1:pos + window + 1], errors="coerce").dropna()
        high_source = daily["High"] if "High" in daily.columns else daily["Close"]
        highs = pd.to_numeric(high_source.iloc[pos + 1:pos + window + 1], errors="coerce").dropna()
        minimum = None if lows.empty else float(lows.min())
        maximum = None if highs.empty else float(highs.max())
        metrics[f"minimum_price_{window}d"] = minimum
        metrics[f"maximum_price_{window}d"] = maximum
        metrics[f"max_drawdown_{window}d"] = None if minimum is None else min(0.0, minimum - entry_price)
        metrics[f"max_drawdown_{window}d_pct"] = (
            None if minimum is None else min(0.0, (minimum / entry_price - 1.0) * 100.0)
        )
        metrics[f"max_favorable_excursion_{window}d_pct"] = (
            None if maximum is None else max(0.0, (maximum / entry_price - 1.0) * 100.0)
        )
        metrics[f"first_touch_{window}d"] = first_threshold_touch(daily, pos, entry_price, window)
    return metrics


def empty_trade_metrics() -> dict:
    metrics = {}
    for horizon in HORIZONS:
        metrics[f"sell_price_{horizon}d"] = None
        metrics[f"profit_loss_{horizon}d"] = None
        metrics[f"return_{horizon}d_pct"] = None
    for window in EXCURSION_WINDOWS:
        metrics[f"minimum_price_{window}d"] = None
        metrics[f"maximum_price_{window}d"] = None
        metrics[f"max_drawdown_{window}d"] = None
        metrics[f"max_drawdown_{window}d_pct"] = None
        metrics[f"max_favorable_excursion_{window}d_pct"] = None
        metrics[f"first_touch_{window}d"] = None
    return metrics


def first_threshold_touch(
    daily: pd.DataFrame,
    entry_position: int,
    entry_price: float,
    window: int,
) -> Optional[str]:
    if entry_position < 0 or entry_price <= 0:
        return None
    if entry_position + window >= len(daily):
        return None
    plus_target = entry_price * 1.05
    minus_target = entry_price * 0.97
    high_source = daily["High"] if "High" in daily.columns else daily["Close"]
    for offset in range(1, window + 1):
        high = _float_or_none(high_source.iloc[entry_position + offset])
        low = _float_or_none(daily["Low"].iloc[entry_position + offset])
        reached_plus = high is not None and high >= plus_target
        reached_minus = low is not None and low <= minus_target
        if reached_plus and reached_minus:
            return None
        if reached_plus:
            return "plus_5pct"
        if reached_minus:
            return "minus_3pct"
    return None


def _float_or_none(value) -> Optional[float]:
    try:
        return None if pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return None
