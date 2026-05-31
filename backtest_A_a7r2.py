#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
backtest_A_a7r2.py

A7R2 の狙い
- V7 の厳選ロジックをベースにする
- V9 の改善点を必要最小限だけ取り込む
  1) adjusted OHLC ベース
  2) ファンダ欠損は soft fail
  3) 売上成長率は四半期 YoY 優先
  4) ROA は 3 段階判定
- stock_screen_yf_picker_v4 依存を完全に除去
- GUI は入力取得だけに限定し、スレッド違反を避ける

出力
- backtest_A_signals_a7r2_<start>_to_<end>.csv
- backtest_A_summary_a7r2_<start>_to_<end>.csv
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.data.fundamental_extractors import (
    extract_per_pbr,
    extract_quarterly_sales_growth_pct,
    extract_roa_pct,
)
from app.data.yfinance_repository import fetch_fundamentals_once, fetch_raw_price_map
from app.domain.config import (
    CATEGORY_PRIORITY,
    DEV25_HARD_MAX,
    DEV25_SOFT_1,
    DEV25_SOFT_2,
    DEV5_HARD_LOW,
    DEV5_HARD_MAX,
    DEV5_SOFT_MAX,
    DEV5_SOFT_MIN,
    ENTRY_LIMIT_DEV_FROM_25,
    GENERAL_SALES_GROWTH_FLOOR,
    HORIZONS,
    LEADER_CODES,
    LEADER_SALES_GROWTH_FLOOR,
    MA25_SLOPE_MIN,
    MA75_SLOPE_MIN,
    MAX_DAY_GAIN,
    MAX_RSI,
    MIN_RSI,
    MIN_TURNOVER_20D,
    NEAR_HIGH_MIN,
    PERCENT_B_HARD_MAX,
    PERCENT_B_SOFT_MAX,
    PER_HARD_EXCLUDE,
    PER_HARD_EXCLUDE_DEV25,
    PER_HARD_EXCLUDE_RSI,
    REBOUND_DEV25_MAX,
    ROA_HARD_MIN,
    ROA_PASS_MIN,
    ROA_STRONG_MIN,
    SOFT_FAIL_NEAR_PASS_MAX,
    TWO_DAY_GAIN_HARD_MAX,
    WINDOWS,
)
from app.domain.indicators import compute_indicators, safe_float
from app.domain.models import ReasonItem, ScreenResult

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
    from tkcalendar import DateEntry
except Exception:
    tk = None
    filedialog = None
    messagebox = None
    DateEntry = None

def parse_stock_md(md_text: str) -> List[Tuple[str, str]]:
    results: List[Tuple[str, str]] = []
    pattern = re.compile(r"[-*]?\s*([^\n()]+?)\s*[\(（]\s*(\d{4})\s*[\)）]")
    for line in md_text.splitlines():
        m = pattern.search(line)
        if m:
            results.append((m.group(1).strip(), m.group(2).strip()))

    seen = set()
    deduped: List[Tuple[str, str]] = []
    for name, code in results:
        if code not in seen:
            seen.add(code)
            deduped.append((name, code))
    return deduped

def add_reason(items: List[ReasonItem], category: str, message: str, *, is_hard: bool, priority: int) -> None:
    items.append(ReasonItem(category=category, message=message, is_hard=is_hard, priority=priority))


def summarize_reasons(reason_items: List[ReasonItem]) -> Tuple[Optional[str], Optional[str], List[str]]:
    if not reason_items:
        return None, None, []

    ordered = sorted(
        reason_items,
        key=lambda x: (CATEGORY_PRIORITY.get(x.category, 99), x.priority, 0 if x.is_hard else 1, x.message),
    )
    primary = ordered[0]
    secondary: List[str] = []
    seen = {primary.message}
    for item in ordered[1:]:
        if item.message not in seen:
            secondary.append(item.message)
            seen.add(item.message)
    return primary.category, primary.message, secondary



def is_recoverable_soft_reason(item: ReasonItem) -> bool:
    if item.is_hard:
        return False
    msg = item.message or ""
    if item.category == "過熱":
        if "25日線からやや過熱" in msg or "25日線から強い過熱" in msg:
            return True
        if "%B=" in msg or "+2σ超え" in msg:
            return True
    if item.category == "押し目未完成":
        if "直近3日で安値切り下げが続く" in msg:
            return True
    return False


def can_promote_soft_fails(reason_items: List[ReasonItem]) -> bool:
    softs = [x for x in reason_items if not x.is_hard]
    if not softs:
        return True
    return all(is_recoverable_soft_reason(x) for x in softs)

def estimate_entry_limits(ma25: Optional[float], close: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
    if ma25 is None:
        return None, None
    low = ma25
    high = ma25 * (1 + ENTRY_LIMIT_DEV_FROM_25 / 100)
    if close is not None and close < high:
        high = max(close, low)
    return low, high


def business_days(start_date: str, end_date: str) -> List[pd.Timestamp]:
    return list(pd.bdate_range(start=start_date, end=end_date))


def load_watchlist(stock_md_path: Path) -> List[Tuple[str, str]]:
    text = stock_md_path.read_text(encoding="utf-8")
    parsed = parse_stock_md(text)
    if not parsed:
        raise ValueError("stock.md から 4桁コード付き銘柄を抽出できませんでした。")
    return parsed


# =========================
# data loading
# =========================
def bulk_download_prices(watchlist: List[Tuple[str, str]], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    raw_price_map = fetch_raw_price_map(watchlist, start_date, end_date)
    return {code: compute_indicators(df) for code, df in raw_price_map.items()}


# =========================
# optimized backtest helpers
# =========================
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


# =========================
# scoring / evaluation
# =========================
def score_result_a7r2(
    *,
    close: Optional[float],
    ma25: Optional[float],
    ma75: Optional[float],
    dev5: Optional[float],
    dev25: Optional[float],
    rsi: Optional[float],
    momentum_pct: Optional[float],
    avg_turnover_20d: Optional[float],
    near_high_ratio: Optional[float],
    ma25_slope_pct: Optional[float],
    ma75_slope_pct: Optional[float],
    roa_pct: Optional[float],
    sales_growth_pct: Optional[float],
    bb_percent_b: Optional[float],
    code: str,
) -> int:
    score = 0

    if ma25 is not None and ma75 is not None and ma25 > ma75:
        score += 15
    if close is not None and ma25 is not None and close > ma25:
        score += 15
    if ma25_slope_pct is not None and ma25_slope_pct > MA25_SLOPE_MIN:
        score += 8
    if ma75_slope_pct is not None and ma75_slope_pct >= MA75_SLOPE_MIN:
        score += 5

    if dev25 is not None:
        if 0.5 <= dev25 <= 4.0:
            score += 14
        elif 0 <= dev25 <= DEV25_SOFT_1:
            score += 10
        elif -1.0 <= dev25 < 0:
            score += 3

    if dev5 is not None:
        if 0.5 <= dev5 <= 2.5:
            score += 10
        elif DEV5_SOFT_MIN <= dev5 <= DEV5_SOFT_MAX:
            score += 5

    if rsi is not None:
        if 47.0 <= rsi <= 60.0:
            score += 10
        elif MIN_RSI <= rsi <= MAX_RSI:
            score += 5

    if near_high_ratio is not None:
        if near_high_ratio >= 0.90:
            score += 8
        elif near_high_ratio >= NEAR_HIGH_MIN:
            score += 4

    if avg_turnover_20d is not None:
        if avg_turnover_20d >= 5_000_000_000:
            score += 5
        elif avg_turnover_20d >= MIN_TURNOVER_20D:
            score += 3

    if momentum_pct is not None and momentum_pct > 0:
        score += 5

    if roa_pct is not None:
        if roa_pct >= ROA_STRONG_MIN:
            score += 6
        elif roa_pct >= ROA_PASS_MIN:
            score += 3
        elif roa_pct >= ROA_HARD_MIN:
            score += 1

    leader_floor = 5.0 if code not in LEADER_CODES else 0.0
    if sales_growth_pct is not None and sales_growth_pct >= leader_floor:
        score += 6
    elif sales_growth_pct is not None and sales_growth_pct > LEADER_SALES_GROWTH_FLOOR:
        score += 2

    if bb_percent_b is not None:
        if 0.25 <= bb_percent_b <= 0.90:
            score += 4
        elif bb_percent_b > 0.98:
            score -= 2

    return max(0, min(score, 100))


def evaluate_row_a7r2(
    name: str,
    code: str,
    trade_date: pd.Timestamp,
    row: pd.Series,
    prev3: pd.DataFrame,
    fundamentals: dict,
) -> ScreenResult:
    close = safe_float(row["Close"])
    ma5 = safe_float(row["MA5"])
    ma25 = safe_float(row["MA25"])
    ma75 = safe_float(row["MA75"])
    dev5 = safe_float(row["Dev5"])
    dev25 = safe_float(row["Dev25"])
    rsi = safe_float(row["RSI14"])
    momentum_raw = safe_float(row["Momentum20"])
    momentum_pct = momentum_raw * 100 if momentum_raw is not None else None
    avg_turnover_20d = safe_float(row["AvgTurnover20"])
    near_high_ratio = safe_float(row["NearHighRatio"])
    ma25_slope_pct = safe_float(row["MA25_SlopePct"])
    ma75_slope_pct = safe_float(row["MA75_SlopePct"])
    day_change_pct = safe_float(row["DayChangePct"])
    volume_ratio_20d = safe_float(row["VolumeRatio20"])
    close_position_pct = safe_float(row["ClosePositionPct"])
    prev_close = safe_float(row["PrevClose"])
    bb_upper = safe_float(row.get("BB_Upper20"))
    bb_lower = safe_float(row.get("BB_Lower20"))
    bb_percent_b = safe_float(row.get("BB_PercentB"))
    prev2_base = safe_float(row.get("Close2Ago"))
    two_day_gain_pct = None if prev2_base in (None, 0) or close is None else (close / prev2_base - 1.0) * 100.0

    per = fundamentals.get("per")
    pbr = fundamentals.get("pbr")
    sales_growth_pct = fundamentals.get("sales_growth_pct")
    roa_pct = fundamentals.get("roa_pct")

    reason_items: List[ReasonItem] = []
    hard_fail = False
    soft_fail_count = 0
    is_leader = code in LEADER_CODES

    # ===== trend =====
    if ma25 is None or ma75 is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "移動平均線データ不足", is_hard=True, priority=1)
    elif ma25 <= ma75:
        hard_fail = True
        add_reason(reason_items, "下降トレンド", "25日線が75日線の上にない", is_hard=True, priority=1)

    if close is None or ma25 is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "終値または25日線データ不足", is_hard=True, priority=2)
    elif close <= ma25:
        hard_fail = True
        add_reason(reason_items, "下降トレンド", "終値が25日線の上にない", is_hard=True, priority=2)

    if ma25_slope_pct is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "25日線傾きデータ不足", is_hard=True, priority=3)
    elif ma25_slope_pct <= MA25_SLOPE_MIN:
        hard_fail = True
        add_reason(reason_items, "下降トレンド", f"25日線の傾きが弱い({ma25_slope_pct:.2f}%)", is_hard=True, priority=3)

    if ma75_slope_pct is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "75日線傾きデータ不足", is_hard=True, priority=4)
    elif ma75_slope_pct < MA75_SLOPE_MIN:
        hard_fail = True
        add_reason(reason_items, "下降トレンド", f"75日線が上向きでない({ma75_slope_pct:.2f}%)", is_hard=True, priority=4)

    if near_high_ratio is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "60日高値圏データ不足", is_hard=True, priority=5)
    elif near_high_ratio < NEAR_HIGH_MIN:
        hard_fail = True
        add_reason(reason_items, "下降トレンド", "60日高値圏から離れすぎ", is_hard=True, priority=5)

    # ===== pullback / overheat =====
    if dev25 is None or dev5 is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "乖離率データ不足", is_hard=True, priority=10)
    else:
        if dev25 < REBOUND_DEV25_MAX:
            hard_fail = True
            add_reason(reason_items, "リバ候補", f"25日線から離れすぎ({dev25:.2f}%)", is_hard=True, priority=1)
        elif dev25 < 0:
            soft_fail_count += 1
            add_reason(reason_items, "押し目未完成", f"25日線を少し割り込み({dev25:.2f}%)", is_hard=False, priority=1)
        elif dev25 > DEV25_HARD_MAX:
            hard_fail = True
            add_reason(reason_items, "過熱", f"25日線乖離が大きすぎる({dev25:.2f}%)", is_hard=True, priority=1)
        elif dev25 > DEV25_SOFT_2:
            soft_fail_count += 1
            add_reason(reason_items, "過熱", f"25日線から強い過熱({dev25:.2f}%)", is_hard=False, priority=2)
        elif dev25 > DEV25_SOFT_1:
            soft_fail_count += 1
            add_reason(reason_items, "過熱", f"25日線からやや過熱({dev25:.2f}%)", is_hard=False, priority=3)

        if dev5 < DEV5_HARD_LOW:
            hard_fail = True
            add_reason(reason_items, "押し目未完成", f"5日線を大きく割り込み({dev5:.2f}%)", is_hard=True, priority=2)
        elif dev5 < DEV5_SOFT_MIN:
            soft_fail_count += 1
            add_reason(reason_items, "押し目未完成", f"5日線を少し割り込み({dev5:.2f}%)", is_hard=False, priority=2)
        elif dev5 > DEV5_HARD_MAX:
            hard_fail = True
            add_reason(reason_items, "過熱", f"5日線から離れすぎ({dev5:.2f}%)", is_hard=True, priority=4)
        elif dev5 > DEV5_SOFT_MAX:
            soft_fail_count += 1
            add_reason(reason_items, "過熱", f"5日線からやや離れすぎ({dev5:.2f}%)", is_hard=False, priority=4)

    # ===== bollinger =====
    if bb_percent_b is not None and bb_percent_b > PERCENT_B_HARD_MAX:
        hard_fail = True
        add_reason(reason_items, "過熱", f"%Bが過熱水準({bb_percent_b:.2f})", is_hard=True, priority=5)
    elif bb_percent_b is not None and bb_percent_b > PERCENT_B_SOFT_MAX:
        soft_fail_count += 1
        add_reason(reason_items, "過熱", f"%Bがやや高い({bb_percent_b:.2f})", is_hard=False, priority=6)
    elif bb_upper is not None and close is not None and close > bb_upper:
        soft_fail_count += 1
        add_reason(reason_items, "過熱", f"+2σ超えで過熱警戒(%B={bb_percent_b:.2f})" if bb_percent_b is not None else "+2σ超えで過熱警戒", is_hard=False, priority=7)

    # ===== RSI / extension =====
    if rsi is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "RSIデータ不足", is_hard=True, priority=11)
    else:
        if rsi < MIN_RSI:
            hard_fail = True
            add_reason(reason_items, "押し目未完成", f"RSIが弱い({rsi:.2f})", is_hard=True, priority=3)
        elif rsi > MAX_RSI:
            hard_fail = True
            add_reason(reason_items, "過熱", f"RSIが高すぎる({rsi:.2f})", is_hard=True, priority=7)

    if day_change_pct is not None and day_change_pct > MAX_DAY_GAIN:
        hard_fail = True
        add_reason(reason_items, "過熱", f"当日上昇率が大きすぎる({day_change_pct:.2f}%)", is_hard=True, priority=8)

    if two_day_gain_pct is not None and two_day_gain_pct > TWO_DAY_GAIN_HARD_MAX:
        hard_fail = True
        add_reason(reason_items, "過熱", f"直近2日で上がりすぎ({two_day_gain_pct:.2f}%)", is_hard=True, priority=9)

    # ===== pullback completion =====
    if len(prev3) >= 3:
        lower_low_count = int(prev3["LowerLow"].fillna(False).sum())
        bear_count = int(prev3["IsBear"].fillna(False).sum())
        if lower_low_count >= 3:
            hard_fail = True
            add_reason(reason_items, "押し目未完成", "直近3日で安値切り下げが続きすぎ", is_hard=True, priority=4)
        elif lower_low_count == 2:
            soft_fail_count += 1
            add_reason(reason_items, "押し目未完成", "直近3日で安値切り下げが続く", is_hard=False, priority=4)
        if bear_count >= 3:
            hard_fail = True
            add_reason(reason_items, "押し目未完成", "陰線が連続しすぎ", is_hard=True, priority=5)

    if bool(row.get("DownVolExpand2", False)):
        hard_fail = True
        add_reason(reason_items, "押し目未完成", "出来高増で2日連続下落", is_hard=True, priority=6)

    # ===== liquidity =====
    if avg_turnover_20d is None:
        hard_fail = True
        add_reason(reason_items, "判定保留", "20日平均売買代金データ不足", is_hard=True, priority=20)
    elif avg_turnover_20d < MIN_TURNOVER_20D:
        hard_fail = True
        add_reason(reason_items, "流動性不足", "20日平均売買代金が15億円未満", is_hard=True, priority=1)

    # ===== fundamentals =====
    if roa_pct is None:
        soft_fail_count += 1
        add_reason(reason_items, "判定保留", "ROAデータ不足", is_hard=False, priority=30)
    elif roa_pct < ROA_HARD_MIN:
        hard_fail = True
        add_reason(reason_items, "ファンダ注意", f"ROAが低すぎる({roa_pct:.2f}%)", is_hard=True, priority=1)
    elif roa_pct < ROA_PASS_MIN:
        soft_fail_count += 1
        add_reason(reason_items, "ファンダ注意", f"ROAがやや低い({roa_pct:.2f}%)", is_hard=False, priority=2)

    if sales_growth_pct is None:
        soft_fail_count += 1
        add_reason(reason_items, "判定保留", "売上成長率データ不足", is_hard=False, priority=31)
    else:
        floor = LEADER_SALES_GROWTH_FLOOR if is_leader else GENERAL_SALES_GROWTH_FLOOR
        if sales_growth_pct < floor:
            hard_fail = True
            if is_leader:
                add_reason(reason_items, "ファンダ注意", f"売上成長が許容下限以下({sales_growth_pct:.2f}%)", is_hard=True, priority=3)
            else:
                add_reason(reason_items, "ファンダ注意", f"売上成長率が0%未満({sales_growth_pct:.2f}%)", is_hard=True, priority=3)
        elif sales_growth_pct < (0.0 if is_leader else 3.0):
            soft_fail_count += 1
            add_reason(reason_items, "ファンダ注意", f"売上成長が弱い({sales_growth_pct:.2f}%)", is_hard=False, priority=4)

    if per is not None and (dev25 is not None and dev25 >= PER_HARD_EXCLUDE_DEV25) and (rsi is not None and rsi >= PER_HARD_EXCLUDE_RSI) and per > PER_HARD_EXCLUDE:
        hard_fail = True
        add_reason(reason_items, "過熱", f"高PERかつ過熱({per:.2f}倍)", is_hard=True, priority=10)

    promotable_soft_only = can_promote_soft_fails(reason_items)
    passed = (not hard_fail) and (
        soft_fail_count == 0
        or (promotable_soft_only and soft_fail_count <= 2)
    )
    near_pass = (not hard_fail) and (not passed) and (0 < soft_fail_count <= SOFT_FAIL_NEAR_PASS_MAX)

    score = score_result_a7r2(
        close=close,
        ma25=ma25,
        ma75=ma75,
        dev5=dev5,
        dev25=dev25,
        rsi=rsi,
        momentum_pct=momentum_pct,
        avg_turnover_20d=avg_turnover_20d,
        near_high_ratio=near_high_ratio,
        ma25_slope_pct=ma25_slope_pct,
        ma75_slope_pct=ma75_slope_pct,
        roa_pct=roa_pct,
        sales_growth_pct=sales_growth_pct,
        bb_percent_b=bb_percent_b,
        code=code,
    )

    primary_category, primary_reason, secondary_reasons = summarize_reasons(reason_items)

    if passed:
        watch_status = "本命候補"
    elif near_pass:
        watch_status = "監視候補"
    else:
        mapping = {
            "下降トレンド": "見送り:トレンド",
            "押し目未完成": "見送り:押し未完成",
            "過熱": "見送り:過熱",
            "ファンダ注意": "見送り:ファンダ",
            "流動性不足": "見送り:流動性",
            "リバ候補": "別戦略:リバ候補",
            "判定保留": "判定保留",
        }
        watch_status = mapping.get(primary_category or "", "見送り")

    entry_limit_low, entry_limit_high = estimate_entry_limits(ma25, close)

    return ScreenResult(
        code=code,
        name=name,
        symbol=f"{code}.T",
        trade_date=trade_date.strftime("%Y-%m-%d"),
        day_open=safe_float(row["Open"]),
        day_high=safe_float(row["High"]),
        day_low=safe_float(row["Low"]),
        day_close=close,
        ma5=ma5,
        ma25=ma25,
        ma75=ma75,
        dev5=dev5,
        dev25=dev25,
        roa_pct=roa_pct,
        rsi=rsi,
        momentum_pct=momentum_pct,
        per=per,
        pbr=pbr,
        sales_growth_pct=sales_growth_pct,
        avg_turnover_20d=avg_turnover_20d,
        near_high_ratio=near_high_ratio,
        ma25_slope_pct=ma25_slope_pct,
        ma75_slope_pct=ma75_slope_pct,
        day_change_pct=day_change_pct,
        volume_ratio_20d=volume_ratio_20d,
        close_position_pct=close_position_pct,
        prev_close=prev_close,
        passed=passed,
        near_pass=near_pass,
        score=score,
        reason_items=reason_items,
        primary_category=primary_category,
        primary_reason=primary_reason,
        secondary_reasons=secondary_reasons,
        watch_status=watch_status,
        entry_limit_low=entry_limit_low,
        entry_limit_high=entry_limit_high,
        bb_upper=bb_upper,
        bb_lower=bb_lower,
        bb_percent_b=bb_percent_b,
        two_day_gain_pct=two_day_gain_pct,
    )


# =========================
# output helpers
# =========================
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


def summarize_signals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    summaries = []
    for category, g in df.groupby("category", dropna=False):
        record = {"category": category, "count": int(len(g))}
        for h in HORIZONS:
            col = f"ret_{h}d_pct"
            s = pd.to_numeric(g[col], errors="coerce")
            record[f"avg_{h}d_pct"] = float(s.mean()) if not s.dropna().empty else np.nan
            record[f"median_{h}d_pct"] = float(s.median()) if not s.dropna().empty else np.nan
            record[f"winrate_{h}d_pct"] = float((s > 0).mean() * 100.0) if not s.dropna().empty else np.nan

        for w in WINDOWS:
            up = pd.to_numeric(g[f"max_up_{w}d_pct"], errors="coerce")
            dd = pd.to_numeric(g[f"max_dd_{w}d_pct"], errors="coerce")
            record[f"avg_max_up_{w}d_pct"] = float(up.mean()) if not up.dropna().empty else np.nan
            record[f"avg_max_dd_{w}d_pct"] = float(dd.mean()) if not dd.dropna().empty else np.nan

        summaries.append(record)

    out = pd.DataFrame(summaries)
    preferred_order = {
        "本命候補": 0,
        "監視候補": 1,
        "別戦略:リバ候補": 2,
        "見送り:押し未完成": 3,
        "見送り:過熱": 4,
        "見送り:トレンド": 5,
        "見送り:ファンダ": 6,
        "見送り:流動性": 7,
        "判定保留": 8,
    }
    out["_order"] = out["category"].map(lambda x: preferred_order.get(x, 99))
    out = out.sort_values(["_order", "avg_5d_pct", "count"], ascending=[True, False, False]).drop(columns=["_order"]).reset_index(drop=True)
    return out


def save_outputs(out_dir: Path, start_date: str, end_date: str, signals_df: pd.DataFrame, summary_df: pd.DataFrame):
    out_dir.mkdir(parents=True, exist_ok=True)
    signals_path = out_dir / f"backtest_A_signals_a7r2_{start_date}_to_{end_date}.csv"
    summary_path = out_dir / f"backtest_A_summary_a7r2_{start_date}_to_{end_date}.csv"
    signals_df.to_csv(signals_path, index=False, encoding="utf-8-sig")
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    return signals_path, summary_path


# =========================
# backtest core
# =========================
def run_backtest_A7R2(stock_md_path: Path, start_date: str, end_date: str):
    watchlist = load_watchlist(stock_md_path)
    dates = business_days(start_date, end_date)
    date_index = pd.DatetimeIndex(dates)

    print("[1/3] 価格データ一括取得")
    raw_price_map = fetch_raw_price_map(watchlist, start_date, end_date)
    price_map = {code: compute_indicators(df) for code, df in raw_price_map.items()}

    print("[2/3] ファンダメンタル取得（銘柄ごと1回）")
    fundamentals_map = fetch_fundamentals_once(watchlist)

    print("[3/3] 日次判定ループ")
    signal_rows: List[dict] = []

    trade_date_maps: Dict[str, Dict[pd.Timestamp, Optional[pd.Timestamp]]] = {}
    forward_metric_maps: Dict[str, Dict[pd.Timestamp, Dict[str, Optional[float]]]] = {}
    prev3_caches: Dict[str, Dict[pd.Timestamp, pd.DataFrame]] = {}

    for _, code in watchlist:
        df = price_map.get(code, pd.DataFrame())
        trade_date_maps[code] = build_trade_date_index(df, date_index)
        forward_metric_maps[code] = build_forward_metrics_map(df)
        prev3_caches[code] = build_prev3_cache(df)

    total = len(dates) * len(watchlist)
    done = 0

    for dt in dates:
        for name, code in watchlist:
            done += 1
            print(f"[{done}/{total}] {dt.strftime('%Y-%m-%d')} {name} ({code})")
            price_df = price_map.get(code, pd.DataFrame())
            fundamentals = fundamentals_map.get(code, {"per": None, "pbr": None, "sales_growth_pct": None, "roa_pct": None})
            trade_dt = trade_date_maps[code].get(pd.Timestamp(dt))

            if trade_dt is None or price_df.empty or trade_dt not in price_df.index:
                reason_items = [ReasonItem(category="判定保留", message="指定日以前の価格データなし", is_hard=True, priority=1)]
                primary_category, primary_reason, secondary_reasons = summarize_reasons(reason_items)
                result = ScreenResult(
                    code=code,
                    name=name,
                    symbol=f"{code}.T",
                    trade_date="N/A",
                    day_open=None,
                    day_high=None,
                    day_low=None,
                    day_close=None,
                    ma5=None,
                    ma25=None,
                    ma75=None,
                    dev5=None,
                    dev25=None,
                    roa_pct=fundamentals.get("roa_pct"),
                    rsi=None,
                    momentum_pct=None,
                    per=fundamentals.get("per"),
                    pbr=fundamentals.get("pbr"),
                    sales_growth_pct=fundamentals.get("sales_growth_pct"),
                    avg_turnover_20d=None,
                    near_high_ratio=None,
                    ma25_slope_pct=None,
                    ma75_slope_pct=None,
                    day_change_pct=None,
                    volume_ratio_20d=None,
                    close_position_pct=None,
                    prev_close=None,
                    passed=False,
                    near_pass=False,
                    score=0,
                    reason_items=reason_items,
                    primary_category=primary_category,
                    primary_reason=primary_reason,
                    secondary_reasons=secondary_reasons,
                    watch_status="判定保留",
                    entry_limit_low=None,
                    entry_limit_high=None,
                    bb_upper=None,
                    bb_lower=None,
                    bb_percent_b=None,
                    two_day_gain_pct=None,
                )
                future_metrics = {f"ret_{h}d_pct": np.nan for h in HORIZONS}
                for w in WINDOWS:
                    future_metrics[f"max_up_{w}d_pct"] = np.nan
                    future_metrics[f"max_dd_{w}d_pct"] = np.nan
            else:
                row = price_df.loc[trade_dt]
                prev3 = prev3_caches[code].get(pd.Timestamp(trade_dt), pd.DataFrame())
                result = evaluate_row_a7r2(name, code, pd.Timestamp(trade_dt), row, prev3, fundamentals)
                future_metrics = forward_metric_maps[code].get(pd.Timestamp(trade_dt), {})

            signal_rows.append(make_signal_record(result, dt, future_metrics))

    signals_df = pd.DataFrame(signal_rows)
    summary_df = summarize_signals(signals_df)
    return signals_df, summary_df


# =========================
# GUI / CLI input
# =========================
def select_stock_file() -> Optional[Path]:
    if tk is None or filedialog is None:
        raise RuntimeError("tkinter が使えません。CLI引数で実行してください。")
    root = tk.Tk()
    root.withdraw()
    root.update()
    file_path = filedialog.askopenfilename(
        title="監視銘柄の stock.md を選択",
        filetypes=[("Markdown files", "*.md"), ("All files", "*.*")],
    )
    root.destroy()
    return Path(file_path) if file_path else None


def select_output_dir(initial_dir: Optional[Path] = None) -> Optional[Path]:
    if tk is None or filedialog is None:
        raise RuntimeError("tkinter が使えません。CLI引数で実行してください。")
    root = tk.Tk()
    root.withdraw()
    root.update()
    folder = filedialog.askdirectory(
        title="出力先フォルダを選択",
        initialdir=str(initial_dir) if initial_dir else None,
    )
    root.destroy()
    return Path(folder) if folder else None


def select_date_range() -> Optional[Tuple[str, str]]:
    if tk is None or DateEntry is None:
        raise RuntimeError("tkcalendar が使えません。pip install tkcalendar を実行するか、CLI引数で実行してください。")

    result = {"start": None, "end": None}
    win = tk.Tk()
    win.title("A7R バックテスト期間を選択")
    win.geometry("360x200")
    win.resizable(False, False)

    tk.Label(win, text="開始日").pack(pady=(15, 5))
    start_entry = DateEntry(win, width=14, background="darkblue", foreground="white", borderwidth=2, date_pattern="yyyy-mm-dd", locale="ja_JP")
    start_entry.pack()

    tk.Label(win, text="終了日").pack(pady=(15, 5))
    end_entry = DateEntry(win, width=14, background="darkblue", foreground="white", borderwidth=2, date_pattern="yyyy-mm-dd", locale="ja_JP")
    end_entry.pack()

    def on_ok():
        start = start_entry.get_date().strftime("%Y-%m-%d")
        end = end_entry.get_date().strftime("%Y-%m-%d")
        if start > end:
            if messagebox is not None:
                messagebox.showerror("エラー", "開始日は終了日以前にしてください。")
            return
        result["start"] = start
        result["end"] = end
        win.destroy()

    def on_cancel():
        win.destroy()

    btn_frame = tk.Frame(win)
    btn_frame.pack(pady=20)
    tk.Button(btn_frame, text="実行", width=10, command=on_ok).pack(side=tk.LEFT, padx=8)
    tk.Button(btn_frame, text="キャンセル", width=10, command=on_cancel).pack(side=tk.LEFT, padx=8)
    win.mainloop()

    if result["start"] is None or result["end"] is None:
        return None
    return result["start"], result["end"]


def build_parser():
    p = argparse.ArgumentParser(description="A7R 条件 Aバックテスト: V7厳選 + 最小限の現代化")
    p.add_argument("--stock-md", help="監視銘柄の markdown ファイルパス")
    p.add_argument("--start", help="開始日 YYYY-MM-DD")
    p.add_argument("--end", help="終了日 YYYY-MM-DD")
    p.add_argument("--out-dir", help="出力先フォルダ")
    p.add_argument("--gui", action="store_true", help="GUIでファイル・日付を選ぶ")
    return p


def resolve_inputs(args) -> Optional[Tuple[Path, str, str, Path]]:
    use_gui = args.gui or not (args.stock_md and args.start and args.end)

    if use_gui:
        stock_md_path = select_stock_file()
        if stock_md_path is None:
            return None
        date_range = select_date_range()
        if date_range is None:
            return None
        start_date, end_date = date_range
        out_dir = select_output_dir(stock_md_path.parent)
        if out_dir is None:
            return None
        return stock_md_path, start_date, end_date, out_dir

    stock_md_path = Path(args.stock_md)
    start_date = args.start
    end_date = args.end
    out_dir = Path(args.out_dir) if args.out_dir else stock_md_path.parent
    return stock_md_path, start_date, end_date, out_dir


def main():
    parser = build_parser()
    args = parser.parse_args()

    resolved = resolve_inputs(args)
    if resolved is None:
        return

    stock_md_path, start_date, end_date, out_dir = resolved
    signals_df, summary_df = run_backtest_A7R2(stock_md_path, start_date, end_date)
    signals_path, summary_path = save_outputs(out_dir, start_date, end_date, signals_df, summary_df)

    print("")
    print("完了")
    print(f"signals: {signals_path}")
    print(f"summary: {summary_path}")

    if not summary_df.empty:
        print("")
        print(summary_df.to_string(index=False))

    if messagebox is not None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("完了", f"出力が完了しました。\n\n{signals_path}\n{summary_path}")
        root.destroy()


if __name__ == "__main__":
    main()
