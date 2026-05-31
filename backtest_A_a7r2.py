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
from app.domain.entry_rules.a7r2 import (
    A7R2EntryRule,
    add_reason,
    can_promote_soft_fails,
    estimate_entry_limits,
    evaluate_row_a7r2,
    is_recoverable_soft_reason,
    score_result_a7r2,
    summarize_reasons,
)
from app.domain.models import ReasonItem, ScreenResult
from app.domain.post_entry_metrics import (
    build_forward_metrics_map,
    build_prev3_cache,
    build_trade_date_index,
    business_days,
)
from app.domain.summary import summarize_signals

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
