"""Official application entry point for the integrated A8 backtest."""

from __future__ import annotations

from app.output.markdown_writer import save_a8_reports
from app.presentation.a8_gui import request_a8_backtest_input, show_a8_completion
from app.usecases.run_vwap_backtest import run_a8_backtest


def main() -> None:
    inputs = request_a8_backtest_input()
    if inputs is None:
        return
    try:
        trades, summary = run_a8_backtest(inputs.stock_file, inputs.config)
        summary_path, result_path = save_a8_reports(inputs.output_dir, trades, summary)
    except Exception as exc:
        from tkinter import messagebox

        messagebox.showerror("実行エラー", str(exc))
        return

    print(f"summary: {summary_path}")
    print(f"results: {result_path}")
    show_a8_completion(summary_path, result_path)
