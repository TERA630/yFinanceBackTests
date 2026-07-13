"""Orchestration for the configurable VWAP-maintenance backtest."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Dict, List

import pandas as pd

from app.data.vwap_price_repository import (
    fetch_daily_prices,
    fetch_intraday_prices,
)
from app.domain.vwap_backtest import (
    EXCURSION_WINDOWS,
    ENTRY_OPEN,
    ENTRY_PREV_CLOSE,
    HORIZONS,
    VwapBacktestConfig,
    BreakdownScoreInput,
    build_trade_metrics,
    calculate_breakdown_score,
    calculate_range_position_pct,
    intraday_entry,
    intraday_range_position_pct,
    is_ma5_slope_slowdown_excluded,
    is_ma25_slope_excluded,
    MA25_NEGATIVE_SLOPE_REJECT,
    MA25_NEGATIVE_SLOPE_REJECT_NEGATIVE_OR_SLOWDOWN_5D,
    MA25_NEGATIVE_SLOPE_REJECT_SLOWDOWN_5D,
    requires_intraday_prices,
)
from app.domain.price_series import (
    higher_high_count,
    higher_low_count,
    intraday_candle,
    intraday_volume_ratio,
    lower_low_count,
    moving_average_slope_pct,
    nearest_support_distance_atr,
    prepare_daily_prices,
    provisional_moving_average,
)
from app.usecases.watchlist import load_watchlist_items


def run_vwap_backtest(
    stock_md_path: Path,
    config: VwapBacktestConfig,
) -> tuple[pd.DataFrame, dict]:
    config.validate()
    needs_intraday = requires_intraday_prices(config)
    _validate_price_data_range(config, needs_intraday)
    watchlist_items = load_watchlist_items(stock_md_path)
    watchlist = [(item.name, item.code) for item in watchlist_items]

    print("[1/3] 日足データ取得")
    daily_map = fetch_daily_prices(watchlist, config.start_date, config.end_date)
    if needs_intraday:
        print("[2/3] 5分足データ取得")
        intraday_map = fetch_intraday_prices(watchlist, config.start_date, config.end_date)
    else:
        print("[2/3] 5分足データ取得なし（日足条件のみ）")
        intraday_map = {}
    print("[3/3] A11バックテスト")

    records: List[dict] = []
    skipped = Counter()
    evaluated = 0

    for item in watchlist_items:
        name = item.name
        code = item.code
        daily = prepare_daily_prices(daily_map.get(code, pd.DataFrame()))
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
            ma5 = _number(row.get("MA5"))
            if previous_close is None or ma25 in (None, 0):
                skipped["25日線を計算できない"] += 1
                continue

            dev25_pct = (previous_close / ma25 - 1.0) * 100.0
            if not (config.dev25_min < dev25_pct <= config.dev25_max):
                skipped["25日乖離率が範囲外"] += 1
                continue

            lower_lows = lower_low_count(daily, daily_position)
            higher_lows = higher_low_count(daily, daily_position)
            if config.lower_low_exclude_count > 0 and lower_lows >= config.lower_low_exclude_count:
                skipped["安値切り下げ回数が除外基準以上"] += 1
                continue
            higher_highs = higher_high_count(daily, daily_position)
            if config.higher_high_exclude_count > 0 and higher_highs < config.higher_high_exclude_count:
                skipped["高値更新回数が必要回数未満"] += 1
                continue

            if config.entry_time == ENTRY_PREV_CLOSE:
                entry_date = signal_date
                entry_price = previous_close
                entry = intraday_entry(intraday, entry_date, "15:30") if needs_intraday else None
                if needs_intraday and entry is None:
                    skipped["崩れスコア用の分足データなし"] += 1
                    continue
                vwap = None if entry is None else entry[1]
                entry_ma25 = ma25
                previous_ma25 = _number(daily["MA25"].iloc[daily_position - 1]) if daily_position > 0 else None
                entry_ma5 = ma5
                previous_ma5 = _number(daily["MA5"].iloc[daily_position - 1]) if daily_position > 0 else None
                entry_position = daily_position
                support_row = row
                breakdown_candle = (
                    intraday_candle(intraday, entry_date, "15:30", entry_price)
                    if needs_intraday
                    else {"open": None, "high": None, "low": None, "close": None}
                )
                breakdown_volume_ratio_20d = (
                    intraday_volume_ratio(intraday, entry_date, "15:30", _number(row.get("VolumeAvg20Open")))
                    if needs_intraday
                    else None
                )
                range_position_pct = calculate_range_position_pct(
                    _number(row.get("Low")),
                    _number(row.get("High")),
                    entry_price,
                )
            elif config.entry_time == ENTRY_OPEN:
                next_position = daily_position + 1
                if next_position >= len(daily):
                    skipped["翌営業日データなし"] += 1
                    continue
                entry_date = pd.Timestamp(daily.index[next_position])
                entry_row = daily.iloc[next_position]
                entry_price = _number(entry_row.get("Open"))
                if entry_price is None:
                    skipped["翌営業日始値データなし"] += 1
                    continue
                vwap = None
                entry_ma25 = provisional_moving_average(daily, daily_position, entry_price, 25)
                previous_ma25 = ma25
                entry_ma5 = provisional_moving_average(daily, daily_position, entry_price, 5)
                previous_ma5 = ma5
                entry_position = next_position
                support_row = entry_row
                breakdown_candle = {"open": None, "high": None, "low": None, "close": None}
                breakdown_volume_ratio_20d = None
                range_position_pct = calculate_range_position_pct(
                    _number(row.get("Low")),
                    _number(row.get("High")),
                    previous_close,
                )
            else:
                next_position = daily_position + 1
                if next_position >= len(daily):
                    skipped["翌営業日データなし"] += 1
                    continue
                entry_date = pd.Timestamp(daily.index[next_position])
                entry_row = daily.iloc[next_position]
                entry = intraday_entry(intraday, entry_date, config.entry_time)
                if entry is None:
                    skipped["指定時刻の分足データなし"] += 1
                    continue
                entry_price, vwap = entry
                entry_ma25 = provisional_moving_average(daily, daily_position, entry_price, 25)
                previous_ma25 = ma25
                entry_ma5 = provisional_moving_average(daily, daily_position, entry_price, 5)
                previous_ma5 = ma5
                entry_position = next_position
                support_row = entry_row
                breakdown_candle = intraday_candle(intraday, entry_date, config.entry_time, entry_price)
                breakdown_volume_ratio_20d = intraday_volume_ratio(
                    intraday,
                    entry_date,
                    config.entry_time,
                    _number(entry_row.get("VolumeAvg20Open")),
                )
                range_position_pct = intraday_range_position_pct(
                    intraday,
                    entry_date,
                    config.entry_time,
                    entry_price,
                )

            if config.range_position_min_pct is not None:
                range_position_label = _range_position_label(config.entry_time)
                if range_position_pct is None:
                    skipped[f"{range_position_label}を計算できない"] += 1
                    continue
                if range_position_pct < config.range_position_min_pct:
                    skipped[f"{range_position_label}が条件未満"] += 1
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
            five_days_ago_ma25_slope_pct = moving_average_slope_pct(daily, entry_position - 5, 25)
            requires_ma25_slowdown = config.ma25_negative_slope_policy in (
                MA25_NEGATIVE_SLOPE_REJECT_SLOWDOWN_5D,
                MA25_NEGATIVE_SLOPE_REJECT_NEGATIVE_OR_SLOWDOWN_5D,
            )
            if requires_ma25_slowdown and five_days_ago_ma25_slope_pct is None:
                skipped["25日線5日前傾きを計算できない"] += 1
                continue
            if is_ma25_slope_excluded(
                ma25_slope_pct,
                five_days_ago_ma25_slope_pct,
                config.ma25_negative_slope_policy,
            ):
                if config.ma25_negative_slope_policy == MA25_NEGATIVE_SLOPE_REJECT or ma25_slope_pct < 0.0:
                    skipped["25日線が下向き"] += 1
                else:
                    skipped["25日線傾きが5日前より鈍化"] += 1
                continue

            ma5_slope_pct = None
            if entry_ma5 not in (None, 0) and previous_ma5 not in (None, 0):
                ma5_slope_pct = (entry_ma5 / previous_ma5 - 1.0) * 100.0
            if config.require_ma5_slope_positive:
                if ma5_slope_pct is None:
                    skipped["5日線傾きを計算できない"] += 1
                    continue
                if ma5_slope_pct <= 0.0:
                    skipped["5日線が上向きでない"] += 1
                    continue
            previous_ma5_slope_pct = moving_average_slope_pct(daily, entry_position - 1, 5)
            three_days_ago_ma5_slope_pct = moving_average_slope_pct(daily, entry_position - 3, 5)
            if is_ma5_slope_slowdown_excluded(
                ma5_slope_pct,
                previous_ma5_slope_pct,
                three_days_ago_ma5_slope_pct,
                config.ma5_slope_slowdown_policy,
            ):
                skipped["5日線傾き鈍化"] += 1
                continue

            support_distance_atr = nearest_support_distance_atr(support_row, entry_price)
            if config.support_distance_max_atr is not None:
                if support_distance_atr is None:
                    skipped["直下支持線距離を計算できない"] += 1
                    continue
                if support_distance_atr > config.support_distance_max_atr:
                    skipped[f"直下支持線距離{config.support_distance_max_atr:g}ATR超"] += 1
                    continue

            breakdown_score = None
            if needs_intraday:
                breakdown_score = calculate_breakdown_score(
                    BreakdownScoreInput(
                        entry_price=entry_price,
                        vwap=vwap,
                        higher_low_count_3d=higher_lows,
                        higher_high_count_3d=higher_highs,
                        range_position_pct=range_position_pct,
                        volume_ratio_20d=breakdown_volume_ratio_20d,
                        open_price=breakdown_candle.get("open"),
                        high_price=breakdown_candle.get("high"),
                        low_price=breakdown_candle.get("low"),
                        close_price=breakdown_candle.get("close"),
                    )
                )
            if (
                config.breakdown_score_threshold is not None
                and breakdown_score is not None
                and breakdown_score.total >= config.breakdown_score_threshold
            ):
                skipped[f"崩れスコア{config.breakdown_score_threshold}点以上"] += 1
                continue

            record = {
                "signal_date": pd.Timestamp(signal_date).strftime("%Y-%m-%d"),
                "entry_date": pd.Timestamp(entry_date).strftime("%Y-%m-%d"),
                "name": name,
                "code": code,
                "entry_time": config.entry_time,
                "semiconductor_related": item.is_semiconductor_related,
                "previous_close": previous_close,
                "previous_ma25": ma25,
                "previous_dev25_pct": dev25_pct,
                "lower_low_count_3d": lower_lows,
                "higher_low_count_3d": higher_lows,
                "higher_high_count_3d": higher_highs,
                "atr14_open": _number(row.get("ATR14Open")),
                "nearest_support_distance_atr": support_distance_atr,
                "entry_price": entry_price,
                "entry_range_position_pct": range_position_pct,
                "breakdown_volume_ratio_20d": breakdown_volume_ratio_20d,
                "breakdown_score": None if breakdown_score is None else breakdown_score.total,
                "breakdown_reasons": "" if breakdown_score is None else " / ".join(breakdown_score.reasons),
                "entry_ma5": entry_ma5,
                "ma5_slope_pct": ma5_slope_pct,
                "previous_ma5_slope_pct": previous_ma5_slope_pct,
                "three_days_ago_ma5_slope_pct": three_days_ago_ma5_slope_pct,
                "entry_ma25": entry_ma25,
                "entry_dev25_pct": entry_dev25_pct,
                "ma25_slope_pct": ma25_slope_pct,
                "five_days_ago_ma25_slope_pct": five_days_ago_ma25_slope_pct,
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
    config: VwapBacktestConfig,
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
        "lower_low_exclude_count": config.lower_low_exclude_count,
        "higher_high_exclude_count": config.higher_high_exclude_count,
        "range_position_min_pct": config.range_position_min_pct,
        "support_distance_max_atr": config.support_distance_max_atr,
        "require_ma5_slope_positive": config.require_ma5_slope_positive,
        "ma5_slope_slowdown_policy": config.ma5_slope_slowdown_policy,
        "ma25_negative_slope_policy": config.ma25_negative_slope_policy,
        "breakdown_score_threshold": config.breakdown_score_threshold,
        "uses_intraday_prices": requires_intraday_prices(config),
        "stock_count": stock_count,
        "evaluated_count": evaluated,
        "entry_count": int(len(trades)),
        "skipped": dict(skipped),
    }
    for horizon in HORIZONS:
        return_column = f"return_{horizon}d_pct"
        values = pd.to_numeric(trades.get(return_column, pd.Series(dtype=float)), errors="coerce").dropna()
        summary[f"completed_{horizon}d"] = int(len(values))
        summary[f"win_rate_{horizon}d_pct"] = None if values.empty else float((values > 0).mean() * 100.0)
        summary[f"average_return_{horizon}d_pct"] = None if values.empty else float(values.mean())

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
        first_touches = trades.get(f"first_touch_{window}d", pd.Series(dtype=object)).dropna()
        decided = first_touches[first_touches.isin(["plus_5pct", "minus_3pct"])]
        summary[f"first_reach_5pct_rate_{window}d_pct"] = (
            None if decided.empty else float((decided == "plus_5pct").mean() * 100.0)
        )
        summary[f"first_adverse_3pct_rate_{window}d_pct"] = (
            None if decided.empty else float((decided == "minus_3pct").mean() * 100.0)
        )

    return summary


def _range_position_label(entry_time: str) -> str:
    return "終端位置" if entry_time not in (ENTRY_PREV_CLOSE, ENTRY_OPEN) else "終値位置"


def _oldest_intraday_start(now: pd.Timestamp | None = None) -> pd.Timestamp:
    today = pd.Timestamp.now().normalize() if now is None else pd.Timestamp(now).normalize()
    return pd.Timestamp(pd.offsets.BDay().rollforward(today - pd.Timedelta(days=59)))


def _validate_price_data_range(config: VwapBacktestConfig, needs_intraday: bool) -> None:
    if needs_intraday:
        oldest = _oldest_intraday_start()
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
