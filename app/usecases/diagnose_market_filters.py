"""Diagnostics for market filter source data."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.data.vwap_price_repository import (
    fetch_symbol_price_diagnostics,
    symbol_daily_download_window,
    symbol_intraday_download_window,
)
from app.domain.vwap_backtest import A8BacktestConfig, ENTRY_PREV_CLOSE
from app.usecases.run_vwap_backtest import _daily_rows_before, _intraday_snapshot_before
from app.usecases.watchlist import load_watchlist_items


def diagnose_market_filters(
    stock_md_path: Path,
    config: A8BacktestConfig,
    *,
    ignore_cache: bool = True,
) -> dict:
    config.validate()
    watchlist_items = load_watchlist_items(stock_md_path)
    signal_dates = list(pd.bdate_range(config.start_date, config.end_date))
    entry_dates = _market_entry_dates(signal_dates, config.entry_time)
    daily_start, daily_end = symbol_daily_download_window(config.start_date, config.end_date)
    intraday_start, intraday_end = symbol_intraday_download_window(config.start_date, config.end_date)
    use_cache = not ignore_cache

    nikkei_intraday, nikkei_intraday_meta = fetch_symbol_price_diagnostics(
        config.nikkei_futures_symbol,
        intraday_start,
        intraday_end,
        "5m",
        use_cache=use_cache,
    )
    sox_daily, sox_daily_meta = fetch_symbol_price_diagnostics(
        config.sox_symbol,
        daily_start,
        daily_end,
        "1d",
        use_cache=use_cache,
    )

    semiconductor_count = sum(1 for item in watchlist_items if item.is_semiconductor_related)
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "start_date": config.start_date,
        "end_date": config.end_date,
        "entry_time": config.entry_time,
        "ignore_cache": ignore_cache,
        "watchlist_count": len(watchlist_items),
        "semiconductor_related_count": semiconductor_count,
        "signal_date_count": len(signal_dates),
        "nikkei": {
            "enabled": bool(config.use_nikkei_futures_filter and config.entry_time != ENTRY_PREV_CLOSE),
            "symbol": config.nikkei_futures_symbol,
            "intraday": asdict(nikkei_intraday_meta),
            "dates": _nikkei_date_diagnostics(nikkei_intraday, signal_dates, entry_dates),
        },
        "sox": {
            "enabled": bool(config.use_sox_semiconductor_filter),
            "symbol": config.sox_symbol,
            "daily": asdict(sox_daily_meta),
            "dates": _sox_date_diagnostics(sox_daily, entry_dates),
        },
    }


def _market_entry_dates(signal_dates: list[pd.Timestamp], entry_time: str) -> list[pd.Timestamp]:
    if entry_time == ENTRY_PREV_CLOSE:
        return [pd.Timestamp(date).normalize() for date in signal_dates]
    return [pd.Timestamp(date + pd.offsets.BDay(1)).normalize() for date in signal_dates]


def _nikkei_date_diagnostics(
    intraday: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    entry_dates: list[pd.Timestamp],
) -> list[dict]:
    records = []
    for signal_date, entry_date in zip(signal_dates, entry_dates):
        at_1530 = _intraday_snapshot_before(intraday, signal_date, "15:30")
        at_0800 = _intraday_snapshot_before(intraday, entry_date, "08:00")
        if at_1530 is None and at_0800 is None:
            status = "NG: 15時30分・8時足なし"
        elif at_1530 is None:
            status = "NG: 15時30分足なし"
        elif at_0800 is None:
            status = "NG: 8時足なし"
        elif at_0800[0] < at_1530[0]:
            status = "OK: 下落"
        else:
            status = "OK: 下落なし"
        records.append(
            {
                "date": entry_date.strftime("%Y-%m-%d"),
                "reference_date": signal_date.strftime("%Y-%m-%d"),
                "close_before_1530": None if at_1530 is None else at_1530[0],
                "timestamp_before_1530": None if at_1530 is None else str(at_1530[1]),
                "close_before_0800": None if at_0800 is None else at_0800[0],
                "timestamp_before_0800": None if at_0800 is None else str(at_0800[1]),
                "status": status,
            }
        )
    return records


def _sox_date_diagnostics(daily: pd.DataFrame, entry_dates: list[pd.Timestamp]) -> list[dict]:
    records = []
    for entry_date in entry_dates:
        rows = _daily_rows_before(daily, entry_date, 2)
        closes = pd.to_numeric(rows["Close"], errors="coerce").dropna() if "Close" in rows.columns else pd.Series(dtype=float)
        if len(closes) < 2:
            previous_close = None if closes.empty else float(closes.iloc[-1])
            status = "NG: 前日終値2本未満"
            latest_close = None
        else:
            previous_close = float(closes.iloc[-2])
            latest_close = float(closes.iloc[-1])
            status = "OK: 下落" if latest_close < previous_close else "OK: 下落なし"
        records.append(
            {
                "date": entry_date.strftime("%Y-%m-%d"),
                "comparison_date": None if len(closes) < 2 else closes.index[-2].strftime("%Y-%m-%d"),
                "previous_close": previous_close,
                "latest_date": None if len(closes) < 2 else closes.index[-1].strftime("%Y-%m-%d"),
                "latest_close": latest_close,
                "status": status,
            }
        )
    return records
