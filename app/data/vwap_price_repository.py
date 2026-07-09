"""Daily and intraday price downloads used by the VWAP backtest."""

from __future__ import annotations

import hashlib
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import yfinance as yf

CACHE_DIR = Path(".yfcache")


@dataclass(frozen=True)
class SymbolDownloadDiagnostics:
    symbol: str
    interval: str
    start: str
    end: str
    cache_path: Path
    cache_exists: bool
    cache_hit: bool
    error: str | None
    row_count: int
    first_timestamp: str | None
    last_timestamp: str | None
    columns: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return self.row_count <= 0


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


def fetch_symbol_daily_price(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    start, end = symbol_daily_download_window(start_date, end_date)
    return _download_symbol(symbol, start, end, "1d")


def fetch_symbol_intraday_price(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    start, end = symbol_intraday_download_window(start_date, end_date)
    return _download_symbol(symbol, start, end, "5m")


def symbol_daily_download_window(start_date: str, end_date: str) -> tuple[str, str]:
    start = (pd.Timestamp(start_date) - pd.Timedelta(days=14)).strftime("%Y-%m-%d")
    end = (pd.Timestamp(end_date) + pd.Timedelta(days=4)).strftime("%Y-%m-%d")
    return start, end


def symbol_intraday_download_window(start_date: str, end_date: str) -> tuple[str, str]:
    cutoff = pd.offsets.BDay().rollforward(pd.Timestamp.now().normalize() - pd.Timedelta(days=59))
    requested_start = pd.Timestamp(start_date) - pd.Timedelta(days=7)
    start = max(cutoff, requested_start).strftime("%Y-%m-%d")
    end = min(pd.Timestamp.now().normalize() + pd.Timedelta(days=1), pd.Timestamp(end_date) + pd.Timedelta(days=4)).strftime("%Y-%m-%d")
    return start, end


def fetch_symbol_price_diagnostics(
    symbol: str,
    start: str,
    end: str,
    interval: str,
    *,
    use_cache: bool = True,
) -> tuple[pd.DataFrame, SymbolDownloadDiagnostics]:
    return _download_symbol_with_diagnostics(symbol, start, end, interval, use_cache=use_cache)


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


def _download_symbol(symbol: str, start: str, end: str, interval: str, *, use_cache: bool = True) -> pd.DataFrame:
    result, _ = _download_symbol_with_diagnostics(symbol, start, end, interval, use_cache=use_cache)
    return result


def _download_symbol_with_diagnostics(
    symbol: str,
    start: str,
    end: str,
    interval: str,
    *,
    use_cache: bool = True,
) -> tuple[pd.DataFrame, SymbolDownloadDiagnostics]:
    cache_path = _symbol_cache_path(symbol, start, end, interval)
    cache_exists = cache_path.exists()
    if use_cache:
        cached = _read_single_cache(cache_path)
        if cached is not None:
            return cached, _symbol_diagnostics(
                symbol,
                start,
                end,
                interval,
                cache_path,
                cache_exists=cache_exists,
                cache_hit=True,
                error=None,
                data=cached,
            )

    try:
        data = yf.download(
            tickers=symbol,
            start=start,
            end=end,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        result = pd.DataFrame() if data is None or data.empty else _normalize(data.copy(), interval)
        if not result.empty:
            _write_single_cache(cache_path, result)
        return result, _symbol_diagnostics(
            symbol,
            start,
            end,
            interval,
            cache_path,
            cache_exists=cache_exists,
            cache_hit=False,
            error=None,
            data=result,
        )
    except Exception as exc:
        result = pd.DataFrame()
        return result, _symbol_diagnostics(
            symbol,
            start,
            end,
            interval,
            cache_path,
            cache_exists=cache_exists,
            cache_hit=False,
            error=str(exc),
            data=result,
        )


def _symbol_diagnostics(
    symbol: str,
    start: str,
    end: str,
    interval: str,
    cache_path: Path,
    *,
    cache_exists: bool,
    cache_hit: bool,
    error: str | None,
    data: pd.DataFrame,
) -> SymbolDownloadDiagnostics:
    if data is None or data.empty:
        row_count = 0
        first_timestamp = None
        last_timestamp = None
        columns: tuple[str, ...] = ()
    else:
        row_count = int(len(data))
        first_timestamp = str(data.index[0])
        last_timestamp = str(data.index[-1])
        columns = tuple(str(column) for column in data.columns)
    return SymbolDownloadDiagnostics(
        symbol=symbol,
        interval=interval,
        start=start,
        end=end,
        cache_path=cache_path,
        cache_exists=cache_exists,
        cache_hit=cache_hit,
        error=error,
        row_count=row_count,
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        columns=columns,
    )


def _normalize(df: pd.DataFrame, interval: str) -> pd.DataFrame:
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


def _symbol_cache_path(symbol: str, start: str, end: str, interval: str) -> Path:
    digest = hashlib.sha1(symbol.encode("utf-8")).hexdigest()[:8]
    start_label = pd.Timestamp(start).strftime("%Y%m%d")
    end_label = pd.Timestamp(end).strftime("%Y%m%d")
    return CACHE_DIR / f"symbol_{interval}_{start_label}_{end_label}_{digest}.pkl"


def _read_cache(path: Path) -> Dict[str, pd.DataFrame] | None:
    try:
        if not path.exists():
            return None
        with path.open("rb") as file:
            value = pickle.load(file)
    except (OSError, pickle.PickleError, EOFError):
        return None
    return value if isinstance(value, dict) else None


def _read_single_cache(path: Path) -> pd.DataFrame | None:
    try:
        if not path.exists():
            return None
        with path.open("rb") as file:
            value = pickle.load(file)
    except (OSError, pickle.PickleError, EOFError):
        return None
    return value if isinstance(value, pd.DataFrame) else None


def _write_cache(path: Path, value: Dict[str, pd.DataFrame]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as file:
            pickle.dump(value, file)
    except OSError:
        return


def _write_single_cache(path: Path, value: pd.DataFrame) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as file:
            pickle.dump(value, file)
    except OSError:
        return
