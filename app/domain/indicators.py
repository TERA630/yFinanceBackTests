"""Technical indicator calculation for Backtest A."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from app.domain.config import BB_PERIOD, BB_STD, MOMENTUM_LOOKBACK, RSI_PERIOD


def safe_float(x) -> Optional[float]:
    try:
        if x is None or pd.isna(x):
            return None
        return float(x)
    except Exception:
        return None


def ema_rsi(series: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    out = df.copy()
    close = out["Close"]

    out["MA5"] = close.rolling(5).mean()
    out["MA25"] = close.rolling(25).mean()
    out["MA75"] = close.rolling(75).mean()
    out["RSI14"] = ema_rsi(close, RSI_PERIOD)
    out["Momentum20"] = close / close.shift(MOMENTUM_LOOKBACK) - 1.0

    out["Dev5"] = (close / out["MA5"] - 1.0) * 100
    out["Dev25"] = (close / out["MA25"] - 1.0) * 100

    out["Turnover"] = out["Close"] * out["Volume"]
    out["AvgTurnover20"] = out["Turnover"].rolling(20).mean()
    out["High60"] = out["High"].rolling(60).max()
    out["NearHighRatio"] = out["Close"] / out["High60"]

    out["MA25_SlopePct"] = (out["MA25"] / out["MA25"].shift(5) - 1.0) * 100
    out["MA75_SlopePct"] = (out["MA75"] / out["MA75"].shift(5) - 1.0) * 100

    out["VolumeAvg20"] = out["Volume"].rolling(20).mean()
    out["VolumeRatio20"] = out["Volume"] / out["VolumeAvg20"]
    out["PrevClose"] = out["Close"].shift(1)
    out["PrevOpen"] = out["Open"].shift(1)
    out["PrevVolume"] = out["Volume"].shift(1)

    out["DayChangePct"] = (out["Close"] / out["PrevClose"] - 1.0) * 100
    day_range = (out["High"] - out["Low"]).replace(0, np.nan)
    out["ClosePositionPct"] = (out["Close"] - out["Low"]) / day_range

    out["IsBear"] = out["Close"] < out["Open"]
    out["LowerLow"] = out["Low"] < out["Low"].shift(1)
    out["DownVolExpand"] = (out["Close"] < out["PrevClose"]) & (out["Volume"] > out["PrevVolume"])
    out["DownVolExpand2"] = out["DownVolExpand"] & out["DownVolExpand"].shift(1).fillna(False)

    bb_mid = close.rolling(BB_PERIOD).mean()
    bb_std = close.rolling(BB_PERIOD).std(ddof=0)
    out["BB_Mid20"] = bb_mid
    out["BB_Upper20"] = bb_mid + BB_STD * bb_std
    out["BB_Lower20"] = bb_mid - BB_STD * bb_std
    width = (out["BB_Upper20"] - out["BB_Lower20"]).replace(0, np.nan)
    out["BB_PercentB"] = (close - out["BB_Lower20"]) / width
    out["Close2Ago"] = close.shift(2)

    return out
