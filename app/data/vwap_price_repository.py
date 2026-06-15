"""Daily and intraday price downloads used by the VWAP backtest."""

from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd
import yfinance as yf


def fetch_daily_prices(watchlist: List[Tuple[str, str]], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    start = (pd.Timestamp(start_date) - pd.Timedelta(days=70)).strftime("%Y-%m-%d")
    end = (pd.Timestamp(end_date) + pd.Timedelta(days=45)).strftime("%Y-%m-%d")
    return _download_map(watchlist, start, end, "1d")


def fetch_intraday_prices(watchlist: List[Tuple[str, str]], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=59)
    requested_start = pd.Timestamp(start_date) - pd.Timedelta(days=7)
    start = max(cutoff, requested_start).strftime("%Y-%m-%d")
    end = min(pd.Timestamp.now().normalize() + pd.Timedelta(days=1), pd.Timestamp(end_date) + pd.Timedelta(days=8)).strftime("%Y-%m-%d")
    return _download_map(watchlist, start, end, "5m")


def _download_map(
    watchlist: List[Tuple[str, str]], start: str, end: str, interval: str
) -> Dict[str, pd.DataFrame]:
    symbols = [f"{code}.T" for _, code in watchlist]
    data = yf.download(
        tickers=symbols,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    result = {code: pd.DataFrame() for _, code in watchlist}
    if data is None or data.empty:
        return result

    if isinstance(data.columns, pd.MultiIndex):
        available = set(data.columns.get_level_values(0))
        for _, code in watchlist:
            symbol = f"{code}.T"
            if symbol in available:
                result[code] = _normalize(data[symbol].copy(), interval)
    elif len(watchlist) == 1:
        result[watchlist[0][1]] = _normalize(data.copy(), interval)
    return result


def _normalize(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    df.columns = [str(column).title() for column in df.columns]
    index = pd.DatetimeIndex(pd.to_datetime(df.index))
    if index.tz is not None:
        index = index.tz_convert("Asia/Tokyo").tz_localize(None)
    df.index = index.normalize() if interval == "1d" else index
    return df.sort_index().dropna(how="all")
