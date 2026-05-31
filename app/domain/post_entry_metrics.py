"""Post-entry date alignment and future performance metrics."""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from app.domain.config import HORIZONS, WINDOWS
from app.domain.indicators import safe_float


def business_days(start_date: str, end_date: str) -> List[pd.Timestamp]:
    return list(pd.bdate_range(start=start_date, end=end_date))


def build_trade_date_index(df: pd.DataFrame, dt_range: pd.DatetimeIndex) -> Dict[pd.Timestamp, Optional[pd.Timestamp]]:
    if df is None or df.empty:
        return {pd.Timestamp(dt): None for dt in dt_range}

    trade_index = pd.DatetimeIndex(df.index)
    positions = trade_index.searchsorted(dt_range, side="right") - 1
    mapping: Dict[pd.Timestamp, Optional[pd.Timestamp]] = {}
    for dt, pos in zip(dt_range, positions):
        mapping[pd.Timestamp(dt)] = None if pos < 0 else pd.Timestamp(trade_index[pos])
    return mapping


def build_forward_metrics_map(df: pd.DataFrame) -> Dict[pd.Timestamp, Dict[str, Optional[float]]]:
    metrics_map: Dict[pd.Timestamp, Dict[str, Optional[float]]] = {}
    if df is None or df.empty:
        return metrics_map

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)

    for idx, row_idx in enumerate(df.index):
        base_close = safe_float(close.iat[idx])
        rec: Dict[str, Optional[float]] = {}
        if base_close in (None, 0):
            for k in HORIZONS:
                rec[f"ret_{k}d_pct"] = None
            for k in WINDOWS:
                rec[f"max_up_{k}d_pct"] = None
                rec[f"max_dd_{k}d_pct"] = None
            metrics_map[pd.Timestamp(row_idx)] = rec
            continue

        for k in HORIZONS:
            j = idx + k
            if j < len(df):
                close_k = safe_float(close.iat[j])
                rec[f"ret_{k}d_pct"] = None if close_k in (None, 0) else (close_k / base_close - 1.0) * 100.0
            else:
                rec[f"ret_{k}d_pct"] = None

        for k in WINDOWS:
            future = slice(idx + 1, min(idx + k + 1, len(df)))
            if future.start >= future.stop:
                rec[f"max_up_{k}d_pct"] = None
                rec[f"max_dd_{k}d_pct"] = None
            else:
                max_high = safe_float(high.iloc[future].max())
                min_low = safe_float(low.iloc[future].min())
                rec[f"max_up_{k}d_pct"] = None if max_high in (None, 0) else (max_high / base_close - 1.0) * 100.0
                rec[f"max_dd_{k}d_pct"] = None if min_low in (None, 0) else (min_low / base_close - 1.0) * 100.0

        metrics_map[pd.Timestamp(row_idx)] = rec
    return metrics_map


def build_prev3_cache(df: pd.DataFrame) -> Dict[pd.Timestamp, pd.DataFrame]:
    if df is None or df.empty:
        return {}
    return {pd.Timestamp(idx): df.iloc[max(0, i - 2): i + 1] for i, idx in enumerate(df.index)}
