"""Application entry point for the VWAP backtest."""

from __future__ import annotations

from app.output.markdown_writer import save_vwap_reports
from app.presentation.vwap_gui import request_vwap_backtest_input, show_vwap_completion
from app.usecases.run_vwap_backtest import run_vwap_backtest


def main() -> None:
    inputs = request_vwap_backtest_input()
    if inputs is None:
        return
    try:
        trades, summary = run_vwap_backtest(inputs.stock_file, inputs.config)
        summary_path, result_path = save_vwap_reports(inputs.output_dir, trades, summary)
    except Exception as exc:
        from tkinter import messagebox

        messagebox.showerror("実行エラー", str(exc))
        return

    print(f"summary: {summary_path}")
    print(f"results: {result_path}")
    show_vwap_completion(summary_path, result_path)
