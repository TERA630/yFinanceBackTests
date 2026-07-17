"""Pure calculations over normalized daily and intraday price series."""

from __future__ import annotations

from typing import Optional

import pandas as pd


def prepare_daily_prices(prices: pd.DataFrame) -> pd.DataFrame:
    if prices is None or prices.empty:
        return pd.DataFrame()

    daily = prices.copy()
    daily.index = pd.DatetimeIndex(daily.index).normalize()
    close = pd.to_numeric(daily["Close"], errors="coerce")
    high = pd.to_numeric(daily["High"], errors="coerce")
    low = pd.to_numeric(daily["Low"], errors="coerce")

    daily["MA5"] = close.rolling(5).mean()
    daily["MA25"] = close.rolling(25).mean()
    daily["MA25Open"] = close.rolling(25).mean().shift(1)
    daily["MA75Open"] = close.rolling(75).mean().shift(1)
    daily["Low20Open"] = low.rolling(20).min().shift(1)
    daily["Low60Open"] = low.rolling(60).min().shift(1)
    daily["High20Open"] = high.rolling(20).max().shift(1)
    daily["High60Open"] = high.rolling(60).max().shift(1)
    daily["VolumeAvg20Open"] = (
        pd.to_numeric(daily["Volume"], errors="coerce").rolling(20).mean().shift(1)
    )
    previous_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    daily["ATR14Open"] = true_range.rolling(14).mean().shift(1)
    return daily.sort_index()


def provisional_moving_average(
    daily: pd.DataFrame,
    signal_position: int,
    entry_price: float,
    window: int,
) -> Optional[float]:
    start = signal_position - (window - 2)
    if start < 0:
        return None
    closes = pd.to_numeric(
        daily["Close"].iloc[start : signal_position + 1], errors="coerce"
    ).dropna()
    if len(closes) != window - 1:
        return None
    return float((closes.sum() + entry_price) / window)


def lower_low_count(daily: pd.DataFrame, signal_position: int) -> int:
    return _direction_count(daily["Low"], signal_position, decreasing=True)


def higher_low_count(daily: pd.DataFrame, signal_position: int) -> int:
    return _direction_count(daily["Low"], signal_position, decreasing=False)


def higher_high_count(daily: pd.DataFrame, signal_position: int) -> int:
    return _direction_count(daily["High"], signal_position, decreasing=False)


def moving_average_slope_pct(
    daily: pd.DataFrame,
    position: int,
    window: int,
) -> Optional[float]:
    if position <= 0 or position >= len(daily):
        return None
    column = f"MA{window}"
    if column not in daily.columns:
        return None
    current = _number(daily[column].iloc[position])
    previous = _number(daily[column].iloc[position - 1])
    if current in (None, 0) or previous in (None, 0):
        return None
    return (current / previous - 1.0) * 100.0


def intraday_candle(
    intraday: pd.DataFrame,
    trade_date: pd.Timestamp,
    cutoff: str,
    entry_price: float,
) -> dict[str, float | None]:
    eligible = eligible_intraday_prices(intraday, trade_date, cutoff)
    if eligible.empty:
        return {"open": None, "high": None, "low": None, "close": entry_price}
    open_source = eligible["Open"] if "Open" in eligible.columns else eligible["Close"]
    return {
        "open": _number(open_source.iloc[0]),
        "high": _number(pd.to_numeric(eligible["High"], errors="coerce").max()),
        "low": _number(pd.to_numeric(eligible["Low"], errors="coerce").min()),
        "close": entry_price,
    }


def intraday_volume_ratio(
    intraday: pd.DataFrame,
    trade_date: pd.Timestamp,
    cutoff: str,
    average_volume_20d: object,
) -> Optional[float]:
    average = _number(average_volume_20d)
    if average in (None, 0):
        return None
    eligible = eligible_intraday_prices(intraday, trade_date, cutoff)
    if eligible.empty or "Volume" not in eligible.columns:
        return None
    volume = _number(pd.to_numeric(eligible["Volume"], errors="coerce").fillna(0.0).sum())
    return None if volume is None else volume / average


def eligible_intraday_prices(
    intraday: pd.DataFrame,
    trade_date: pd.Timestamp,
    cutoff: str,
) -> pd.DataFrame:
    if intraday is None or intraday.empty:
        return pd.DataFrame()
    day = intraday.loc[intraday.index.normalize() == pd.Timestamp(trade_date).normalize()]
    if day.empty:
        return pd.DataFrame()
    cutoff_time = pd.Timestamp(f"{pd.Timestamp(trade_date).date()} {cutoff}")
    return day.loc[day.index < cutoff_time]


def nearest_support_distance_atr(row: pd.Series, price: float) -> Optional[float]:
    atr = _number(row.get("ATR14Open"))
    if atr is None or atr <= 0 or price is None:
        return None
    levels = [
        level
        for column in ("MA25Open", "Low20Open", "Low60Open", "MA75Open")
        if (level := _number(row.get(column))) is not None and level < price
    ]
    if not levels:
        return None
    return (price - max(levels)) / atr


def _direction_count(series: pd.Series, position: int, *, decreasing: bool) -> int:
    start = max(0, position - 3)
    differences = pd.to_numeric(series.iloc[start : position + 1], errors="coerce").diff()
    matches = differences < 0 if decreasing else differences > 0
    return int(matches.iloc[-3:].fillna(False).sum())


def _number(value: object) -> Optional[float]:
    try:
        return None if pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return None
