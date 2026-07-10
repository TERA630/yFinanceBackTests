"""Daily and intraday price downloads used by the VWAP backtest."""

from __future__ import annotations

import hashlib
import pickle
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import yfinance as yf

CACHE_DIR = Path(".yfcache")


def fetch_daily_prices(watchlist: List[Tuple[str, str]], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    # 75日線・60日高安値を始値時点の値として計算できるよう、十分な営業日前データを取得する。
    start = (pd.Timestamp(start_date) - pd.Timedelta(days=130)).strftime("%Y-%m-%d")
    end = (pd.Timestamp(end_date) + pd.Timedelta(days=45)).strftime("%Y-%m-%d")
    return _download_map(watchlist, start, end, "1d")


def fetch_intraday_prices(watchlist: List[Tuple[str, str]], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    cutoff = pd.offsets.BDay().rollforward(pd.Timestamp.now().normalize() - pd.Timedelta(days=59))
    requested_start = pd.Timestamp(start_date) - pd.Timedelta(days=7)
    start = max(cutoff, requested_start).strftime("%Y-%m-%d")
    end = min(pd.Timestamp.now().normalize() + pd.Timedelta(days=1), pd.Timestamp(end_date) + pd.Timedelta(days=8)).strftime("%Y-%m-%d")
    return _download_map(watchlist, start, end, "5m")


def _download_map(
    watchlist: List[Tuple[str, str]], start: str, end: str, interval: str
) -> Dict[str, pd.DataFrame]:
    cache_path = _cache_path(watchlist, start, end, interval)
    cached = _read_cache(cache_path)
    if cached is not None:
        return cached

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
    _write_cache(cache_path, result)
    return result


def _normalize(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        # yfinance returns (price field, ticker) columns even for a single
        # symbol. Keep the level containing OHLCV field names so downstream
        # code can consistently address columns such as "Close".
        price_fields = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
        for level in range(df.columns.nlevels):
            values = [str(value).title() for value in df.columns.get_level_values(level)]
            if price_fields.intersection(values):
                df.columns = values
                break
    df.columns = [str(column).title() for column in df.columns]
    index = pd.DatetimeIndex(pd.to_datetime(df.index))
    if index.tz is not None:
        index = index.tz_convert("Asia/Tokyo").tz_localize(None)
    df.index = index.normalize() if interval == "1d" else index
    return df.sort_index().dropna(how="all")


def _cache_path(watchlist: List[Tuple[str, str]], start: str, end: str, interval: str) -> Path:
    codes = ",".join(sorted(code for _, code in watchlist))
    digest = hashlib.sha1(codes.encode("utf-8")).hexdigest()[:8]
    start_label = pd.Timestamp(start).strftime("%Y%m%d")
    end_label = pd.Timestamp(end).strftime("%Y%m%d")
    return CACHE_DIR / f"{interval}_{start_label}_{end_label}_{digest}.pkl"


def _read_cache(path: Path) -> Dict[str, pd.DataFrame] | None:
    try:
        if not path.exists():
            return None
        with path.open("rb") as file:
            value = pickle.load(file)
    except (OSError, pickle.PickleError, EOFError):
        return None
    return value if isinstance(value, dict) else None


def _write_cache(path: Path, value: Dict[str, pd.DataFrame]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as file:
            pickle.dump(value, file)
    except OSError:
        return
