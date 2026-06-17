"""Pure calculations for the VWAP-maintenance backtest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


ENTRY_PREV_CLOSE = "prev_close"
ENTRY_1100 = "11:00"
ENTRY_1400 = "14:00"
ENTRY_TIMES = (ENTRY_PREV_CLOSE, ENTRY_1100, ENTRY_1400)
HORIZONS = (1, 5, 20)
EXCURSION_WINDOWS = (5, 10, 20)


@dataclass(frozen=True)
class A8BacktestConfig:
    start_date: str
    end_date: str
    dev25_min: float
    dev25_max: float
    entry_time: str
    lower_low_exclude_count: int = 0
    require_vwap_confirmation: bool = True
    range_position_min_pct: Optional[float] = None

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
        if self.range_position_min_pct is not None and self.range_position_min_pct not in (30, 40, 50, 60):
            raise ValueError("終端位置は30%、40%、50%、60%、または考慮なしで指定してください。")


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
    return metrics


def _float_or_none(value) -> Optional[float]:
    try:
        return None if pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return None
