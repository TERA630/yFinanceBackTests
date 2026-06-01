"""Backtest orchestration usecase."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.data.yfinance_repository import fetch_fundamentals_once, fetch_raw_price_map
from app.domain.config import HORIZONS, WINDOWS
from app.domain.entry_rules.a7r2 import evaluate_row_a7r2, summarize_reasons
from app.domain.indicators import compute_indicators
from app.domain.models import ReasonItem, ScreenResult
from app.domain.post_entry_metrics import (
    build_forward_metrics_map,
    build_prev3_cache,
    build_trade_date_index,
    business_days,
)
from app.domain.summary import summarize_signals
from app.output.signal_record import make_signal_record
from app.usecases.watchlist import load_watchlist


def bulk_download_prices(watchlist: List[Tuple[str, str]], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    raw_price_map = fetch_raw_price_map(watchlist, start_date, end_date)
    return {code: compute_indicators(df) for code, df in raw_price_map.items()}


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
