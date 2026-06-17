"""Orchestration for the configurable VWAP-maintenance backtest."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Dict, List

import pandas as pd

from app.data.vwap_price_repository import fetch_daily_prices, fetch_intraday_prices
from app.domain.vwap_backtest import (
    EXCURSION_WINDOWS,
    ENTRY_PREV_CLOSE,
    HORIZONS,
    A8BacktestConfig,
    build_trade_metrics,
    calculate_range_position_pct,
    intraday_entry,
    intraday_range_position_pct,
)
from app.usecases.watchlist import load_watchlist


def run_a8_backtest(stock_md_path: Path, config: A8BacktestConfig) -> tuple[pd.DataFrame, dict]:
    config.validate()
    _validate_intraday_range(config)
    watchlist = load_watchlist(stock_md_path)

    print("[1/3] 日足データ取得")
    daily_map = fetch_daily_prices(watchlist, config.start_date, config.end_date)
    print("[2/3] 5分足データ取得")
    intraday_map = fetch_intraday_prices(watchlist, config.start_date, config.end_date)
    print("[3/3] A8バックテスト")

    records: List[dict] = []
    skipped = Counter()
    evaluated = 0

    for name, code in watchlist:
        daily = _prepare_daily(daily_map.get(code, pd.DataFrame()))
        intraday = intraday_map.get(code, pd.DataFrame())
        if daily.empty:
            skipped["日足データなし"] += 1
            continue

        dates = daily.index[(daily.index >= pd.Timestamp(config.start_date)) & (daily.index <= pd.Timestamp(config.end_date))]
        for signal_date in dates:
            evaluated += 1
            daily_position = daily.index.get_loc(signal_date)
            row = daily.loc[signal_date]
            previous_close = _number(row.get("Close"))
            ma25 = _number(row.get("MA25"))
            if previous_close is None or ma25 in (None, 0):
                skipped["25日線を計算できない"] += 1
                continue

            dev25_pct = (previous_close / ma25 - 1.0) * 100.0
            if not (config.dev25_min < dev25_pct <= config.dev25_max):
                skipped["25日乖離率が範囲外"] += 1
                continue

            lower_low_count = _lower_low_count(daily, daily_position)
            if config.lower_low_exclude_count > 0 and lower_low_count >= config.lower_low_exclude_count:
                skipped["安値切り下げ回数が除外基準以上"] += 1
                continue

            if config.entry_time == ENTRY_PREV_CLOSE:
                entry_date = signal_date
                entry = intraday_entry(intraday, entry_date, "15:30")
                entry_price = previous_close
                if entry is None or (config.require_vwap_confirmation and entry[1] is None):
                    skipped["前日分足データなし"] += 1
                    continue
                _, vwap = entry
                entry_ma25 = ma25
                previous_ma25 = _number(daily["MA25"].iloc[daily_position - 1]) if daily_position > 0 else None
                range_position_pct = calculate_range_position_pct(
                    _number(row.get("Low")),
                    _number(row.get("High")),
                    entry_price,
                )
            else:
                next_position = daily_position + 1
                if next_position >= len(daily):
                    skipped["翌営業日データなし"] += 1
                    continue
                entry_date = pd.Timestamp(daily.index[next_position])
                entry = intraday_entry(intraday, entry_date, config.entry_time)
                if entry is None:
                    skipped["指定時刻の分足データなし"] += 1
                    continue
                entry_price, vwap = entry
                if config.require_vwap_confirmation and vwap is None:
                    skipped["VWAPを計算できない"] += 1
                    continue
                entry_ma25 = _provisional_ma25(daily, daily_position, entry_price)
                previous_ma25 = ma25
                range_position_pct = intraday_range_position_pct(
                    intraday,
                    entry_date,
                    config.entry_time,
                    entry_price,
                )

            if config.range_position_min_pct is not None:
                if range_position_pct is None:
                    skipped["終端位置を計算できない"] += 1
                    continue
                if range_position_pct < config.range_position_min_pct:
                    skipped["終端位置が条件未満"] += 1
                    continue

            if entry_ma25 in (None, 0):
                skipped["当日25日線を計算できない"] += 1
                continue

            entry_dev25_pct = (entry_price / entry_ma25 - 1.0) * 100.0
            if not (config.dev25_min < entry_dev25_pct <= config.dev25_max):
                skipped["当日25日乖離率が範囲外"] += 1
                continue

            if previous_ma25 in (None, 0):
                skipped["25日線傾きを計算できない"] += 1
                continue
            ma25_slope_pct = (entry_ma25 / previous_ma25 - 1.0) * 100.0
            if ma25_slope_pct < 0.0:
                skipped["25日線が下向き"] += 1
                continue

            if config.require_vwap_confirmation and entry_price < vwap:
                skipped["VWAP未維持"] += 1
                continue

            record = {
                "signal_date": pd.Timestamp(signal_date).strftime("%Y-%m-%d"),
                "entry_date": pd.Timestamp(entry_date).strftime("%Y-%m-%d"),
                "name": name,
                "code": code,
                "entry_time": config.entry_time,
                "vwap_confirmation_required": config.require_vwap_confirmation,
                "previous_close": previous_close,
                "previous_ma25": ma25,
                "previous_dev25_pct": dev25_pct,
                "lower_low_count_3d": lower_low_count,
                "entry_price": entry_price,
                "entry_range_position_pct": range_position_pct,
                "entry_ma25": entry_ma25,
                "entry_dev25_pct": entry_dev25_pct,
                "ma25_slope_pct": ma25_slope_pct,
                "vwap": vwap,
                "vwap_margin_pct": None if vwap in (None, 0) else (entry_price / vwap - 1.0) * 100.0,
            }
            record.update(build_trade_metrics(daily, entry_date, entry_price))
            records.append(record)

    trades = pd.DataFrame(records)
    summary = build_summary(trades, config, len(watchlist), evaluated, skipped)
    return trades, summary


def build_summary(
    trades: pd.DataFrame,
    config: A8BacktestConfig,
    stock_count: int,
    evaluated: int,
    skipped: Counter,
) -> dict:
    summary: Dict[str, object] = {
        "start_date": config.start_date,
        "end_date": config.end_date,
        "dev25_min": config.dev25_min,
        "dev25_max": config.dev25_max,
        "entry_time": config.entry_time,
        "require_vwap_confirmation": config.require_vwap_confirmation,
        "lower_low_exclude_count": config.lower_low_exclude_count,
        "range_position_min_pct": config.range_position_min_pct,
        "stock_count": stock_count,
        "evaluated_count": evaluated,
        "entry_count": int(len(trades)),
        "skipped": dict(skipped),
    }
    for horizon in HORIZONS:
        return_column = f"return_{horizon}d_pct"
        profit_column = f"profit_loss_{horizon}d"
        values = pd.to_numeric(trades.get(return_column, pd.Series(dtype=float)), errors="coerce").dropna()
        profits = pd.to_numeric(trades.get(profit_column, pd.Series(dtype=float)), errors="coerce").dropna()
        summary[f"completed_{horizon}d"] = int(len(values))
        summary[f"win_rate_{horizon}d_pct"] = None if values.empty else float((values > 0).mean() * 100.0)
        summary[f"average_return_{horizon}d_pct"] = None if values.empty else float(values.mean())
        summary[f"total_profit_loss_{horizon}d"] = None if profits.empty else float(profits.sum())

    for window in EXCURSION_WINDOWS:
        maes = pd.to_numeric(
            trades.get(f"max_drawdown_{window}d_pct", pd.Series(dtype=float)), errors="coerce"
        ).dropna()
        mfes = pd.to_numeric(
            trades.get(f"max_favorable_excursion_{window}d_pct", pd.Series(dtype=float)), errors="coerce"
        ).dropna()
        summary[f"completed_excursion_{window}d"] = int(min(len(maes), len(mfes)))
        summary[f"average_mae_{window}d_pct"] = None if maes.empty else float(maes.mean())
        summary[f"median_mae_{window}d_pct"] = None if maes.empty else float(maes.median())
        summary[f"median_mfe_{window}d_pct"] = None if mfes.empty else float(mfes.median())
        summary[f"adverse_3pct_rate_{window}d_pct"] = (
            None if maes.empty else float((maes <= -3.0).mean() * 100.0)
        )
        summary[f"reach_5pct_rate_{window}d_pct"] = (
            None if mfes.empty else float((mfes >= 5.0).mean() * 100.0)
        )

    # Compatibility keys retained for existing report consumers.
    summary["completed_drawdown_5d"] = summary["completed_excursion_5d"]
    summary["average_max_drawdown_5d_pct"] = summary["average_mae_5d_pct"]
    summary["median_max_drawdown_5d_pct"] = summary["median_mae_5d_pct"]
    return summary


def run_vwap_backtest(stock_md_path: Path, config: A8BacktestConfig) -> tuple[pd.DataFrame, dict]:
    """Compatibility alias for the former VWAP-only entry point."""
    return run_a8_backtest(stock_md_path, config)


def _prepare_daily(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.copy()
    result.index = pd.DatetimeIndex(result.index).normalize()
    result["MA25"] = pd.to_numeric(result["Close"], errors="coerce").rolling(25).mean()
    return result.sort_index()


def _provisional_ma25(daily: pd.DataFrame, signal_position: int, entry_price: float):
    start = signal_position - 23
    if start < 0:
        return None
    closes = pd.to_numeric(daily["Close"].iloc[start:signal_position + 1], errors="coerce").dropna()
    if len(closes) != 24:
        return None
    return float((closes.sum() + entry_price) / 25.0)


def _lower_low_count(daily: pd.DataFrame, signal_position: int) -> int:
    start = max(0, signal_position - 3)
    lows = pd.to_numeric(daily["Low"].iloc[start:signal_position + 1], errors="coerce")
    return int((lows.diff() < 0).iloc[-3:].fillna(False).sum())


def _validate_intraday_range(config: VwapBacktestConfig) -> None:
    oldest = pd.Timestamp.now().normalize() - pd.Timedelta(days=59)
    if pd.Timestamp(config.start_date) < oldest:
        raise ValueError(
            f"5分足を使うため、開始日は {oldest.strftime('%Y-%m-%d')} 以降にしてください。"
        )
    if pd.Timestamp(config.end_date) > pd.Timestamp.now().normalize():
        raise ValueError("終了日に未来の日付は指定できません。")


def _number(value):
    try:
        return None if pd.isna(value) else float(value)
    except (TypeError, ValueError):
        return None
