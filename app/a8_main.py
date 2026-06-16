"""Official application entry point for the integrated A8 backtest."""

from __future__ import annotations

from app.output.markdown_writer import save_a8_reports
from app.presentation.a8_gui import request_a8_backtest_input, show_a8_batch_completion
from app.usecases.run_vwap_backtest import run_a8_backtest


def main() -> None:
    inputs = request_a8_backtest_input()
    if inputs is None:
        return

    outputs = []
    errors = []
    for gui_input in inputs:
        try:
            trades, summary = run_a8_backtest(gui_input.stock_file, gui_input.config)
            summary_path, result_path = save_a8_reports(gui_input.output_dir, trades, summary)
            outputs.append((summary_path, result_path))
        except Exception as exc:
            errors.append((gui_input, exc))

    for summary_path, result_path in outputs:
        print(f"summary: {summary_path}")
        print(f"results: {result_path}")
    show_a8_batch_completion(outputs, errors)
