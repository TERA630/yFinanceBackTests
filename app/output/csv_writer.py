"""CSV output writer."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def save_outputs(out_dir: Path, start_date: str, end_date: str, signals_df: pd.DataFrame, summary_df: pd.DataFrame):
    out_dir.mkdir(parents=True, exist_ok=True)
    signals_path = out_dir / f"backtest_A_signals_a7r2_{start_date}_to_{end_date}.csv"
    summary_path = out_dir / f"backtest_A_summary_a7r2_{start_date}_to_{end_date}.csv"
    signals_df.to_csv(signals_path, index=False, encoding="utf-8-sig")
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    return signals_path, summary_path
