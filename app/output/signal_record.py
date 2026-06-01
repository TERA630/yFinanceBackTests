"""Convert screening results into output rows."""

from __future__ import annotations

import pandas as pd

from app.domain.models import ScreenResult


def normalize_category(result: ScreenResult) -> str:
    if result.passed:
        return "本命候補"
    if result.near_pass:
        return "監視候補"
    return result.watch_status or "判定保留"


def make_signal_record(result: ScreenResult, signal_date: pd.Timestamp, future_metrics: dict) -> dict:
    row = {
        "signal_date": signal_date.strftime("%Y-%m-%d"),
        "trade_date_used": result.trade_date,
        "name": result.name,
        "code": result.code,
        "category": normalize_category(result),
        "watch_status": result.watch_status,
        "score": result.score,
        "close": result.day_close,
        "ma5": result.ma5,
        "ma25": result.ma25,
        "ma75": result.ma75,
        "dev5_pct": result.dev5,
        "dev25_pct": result.dev25,
        "rsi": result.rsi,
        "two_day_gain_pct": result.two_day_gain_pct,
        "roa_pct": result.roa_pct,
        "per": result.per,
        "pbr": result.pbr,
        "sales_growth_pct": result.sales_growth_pct,
        "day_change_pct": result.day_change_pct,
        "volume_ratio_20d": result.volume_ratio_20d,
        "near_high_ratio": result.near_high_ratio,
        "ma25_slope_pct": result.ma25_slope_pct,
        "ma75_slope_pct": result.ma75_slope_pct,
        "bb_upper": result.bb_upper,
        "bb_lower": result.bb_lower,
        "bb_percent_b": result.bb_percent_b,
        "primary_category": result.primary_category,
        "primary_reason": result.primary_reason,
        "secondary_reasons": " / ".join(result.secondary_reasons) if result.secondary_reasons else "",
        "entry_limit_low": result.entry_limit_low,
        "entry_limit_high": result.entry_limit_high,
    }
    row.update(future_metrics)
    return row
