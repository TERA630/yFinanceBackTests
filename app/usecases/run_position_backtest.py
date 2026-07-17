"""Generate all MA25 candidates and run independent position simulations."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Dict

import pandas as pd

from app.data.vwap_price_repository import fetch_daily_prices, fetch_intraday_prices
from app.domain.position_backtest import (
    DUPLICATE_HOLDING,
    DUPLICATE_MIN_INTERVAL,
    DUPLICATE_NOT_RESET,
    EXIT_HORIZON,
    EXIT_INCOMPLETE,
    EXIT_STOP_LOSS,
    EXIT_TAKE_PROFIT,
    PositionSimulation,
    simulate_positions,
)
from app.domain.price_series import prepare_daily_prices
from app.domain.vwap_backtest import (
    BACKTEST_METHOD_POSITION,
    MA25_DEVIATION_RANGES,
    POSITION_HORIZONS,
    VwapBacktestConfig,
    requires_intraday_prices,
)
from app.usecases.run_vwap_backtest import run_vwap_backtest
from app.usecases.watchlist import load_watchlist_items


def run_position_backtest(
    stock_md_path: Path,
    base_config: VwapBacktestConfig,
) -> tuple[pd.DataFrame, dict]:
    config = replace(base_config, backtest_method=BACKTEST_METHOD_POSITION)
    config.validate()
    watchlist_items = load_watchlist_items(stock_md_path)
    watchlist = [(item.name, item.code) for item in watchlist_items]

    print("[1/4] 日足データ取得")
    daily_map = fetch_daily_prices(watchlist, config.start_date, config.end_date)
    if requires_intraday_prices(config):
        print("[2/4] 5分足データ取得")
        intraday_map = fetch_intraday_prices(watchlist, config.start_date, config.end_date)
    else:
        print("[2/4] 5分足データ取得なし（日足条件のみ）")
        intraday_map = {}

    print("[3/4] 全MA25乖離率帯のシグナル生成")
    candidate_frames: list[pd.DataFrame] = []
    for dev25_min, dev25_max in MA25_DEVIATION_RANGES:
        band_config = replace(config, dev25_min=dev25_min, dev25_max=dev25_max)
        trades, _ = run_vwap_backtest(
            stock_md_path,
            band_config,
            daily_map=daily_map,
            intraday_map=intraday_map,
            announce=False,
        )
        if trades.empty:
            continue
        band_candidates = trades.copy()
        band_candidates["dev25_band_min"] = dev25_min
        band_candidates["dev25_band_max"] = dev25_max
        candidate_frames.append(band_candidates)

    candidates = _combine_candidates(candidate_frames)
    prepared_daily = {
        str(code): prepare_daily_prices(daily)
        for code, daily in daily_map.items()
    }

    print("[4/4] 5・10・15営業日ポジション法")
    simulations = {
        horizon: simulate_positions(candidates, prepared_daily, horizon)
        for horizon in POSITION_HORIZONS
    }
    position_trades = _combine_position_trades(simulations)
    summary = build_position_summary(
        config,
        simulations,
        stock_count=len(watchlist_items),
    )
    return position_trades, summary


def build_position_summary(
    config: VwapBacktestConfig,
    simulations: dict[int, PositionSimulation],
    stock_count: int,
) -> dict:
    periods: Dict[int, dict] = {}
    for horizon, simulation in simulations.items():
        trades = simulation.trades
        duplicate_counts = simulation.duplicate_counts
        duplicate_total = int(sum(duplicate_counts.values()))
        independent_entries = int(len(trades))
        if simulation.signal_count != independent_entries + duplicate_total:
            raise ValueError("ポジション法のシグナル集計が整合しません。")

        returns = pd.to_numeric(
            trades.get("position_return_pct", pd.Series(dtype=float)),
            errors="coerce",
        ).dropna()
        exit_reasons = trades.get("exit_reason", pd.Series(dtype=object)).value_counts()
        periods[horizon] = {
            "signal_count": simulation.signal_count,
            "independent_entry_count": independent_entries,
            "duplicate_count": duplicate_total,
            "target_stock_count": int(trades.get("code", pd.Series(dtype=object)).nunique()),
            "duplicate_holding_count": int(duplicate_counts[DUPLICATE_HOLDING]),
            "duplicate_not_reset_count": int(duplicate_counts[DUPLICATE_NOT_RESET]),
            "duplicate_min_interval_count": int(duplicate_counts[DUPLICATE_MIN_INTERVAL]),
            "completed_count": int(len(returns)),
            "win_rate_pct": None if returns.empty else float((returns > 0).mean() * 100.0),
            "average_return_pct": None if returns.empty else float(returns.mean()),
            "median_return_pct": None if returns.empty else float(returns.median()),
            "take_profit_count": int(exit_reasons.get(EXIT_TAKE_PROFIT, 0)),
            "stop_loss_count": int(exit_reasons.get(EXIT_STOP_LOSS, 0)),
            "holding_period_exit_count": int(exit_reasons.get(EXIT_HORIZON, 0)),
            "incomplete_count": int(exit_reasons.get(EXIT_INCOMPLETE, 0)),
        }

    return {
        "backtest_method": BACKTEST_METHOD_POSITION,
        "start_date": config.start_date,
        "end_date": config.end_date,
        "dev25_ranges": MA25_DEVIATION_RANGES,
        "entry_time": config.entry_time,
        "lower_low_exclude_count": config.lower_low_exclude_count,
        "range_position_min_pct": config.range_position_min_pct,
        "support_distance_max_atr": config.support_distance_max_atr,
        "require_ma5_slope_positive": config.require_ma5_slope_positive,
        "ma5_slope_slowdown_policy": config.ma5_slope_slowdown_policy,
        "ma25_negative_slope_policy": config.ma25_negative_slope_policy,
        "breakdown_score_threshold": config.breakdown_score_threshold,
        "uses_intraday_prices": requires_intraday_prices(config),
        "stock_count": stock_count,
        "periods": periods,
    }


def _combine_candidates(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=["code", "signal_date", "entry_date", "entry_price"])
    candidates = pd.concat(frames, ignore_index=True)
    candidates["signal_date"] = pd.to_datetime(candidates["signal_date"]).dt.normalize()
    candidates["entry_date"] = pd.to_datetime(candidates["entry_date"]).dt.normalize()
    return (
        candidates.sort_values(
            ["signal_date", "code", "dev25_band_min"],
            kind="stable",
        )
        .drop_duplicates(["code", "signal_date"], keep="first")
        .reset_index(drop=True)
    )


def _combine_position_trades(simulations: dict[int, PositionSimulation]) -> pd.DataFrame:
    frames = [simulation.trades for simulation in simulations.values() if not simulation.trades.empty]
    if not frames:
        return pd.DataFrame()
    trades = pd.concat(frames, ignore_index=True)
    return trades.sort_values(["holding_period_days", "signal_date", "code"], kind="stable").reset_index(drop=True)
