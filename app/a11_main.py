"""Official application entry point for the A11 backtest."""

from __future__ import annotations

from app.output.markdown_writer import save_a11_reports
from app.presentation.backtest_gui import request_backtest_inputs, show_batch_completion
from app.usecases.run_vwap_backtest import run_vwap_backtest


def main() -> None:
    inputs = request_backtest_inputs()
    if inputs is None:
        return

    outputs = []
    errors = []
    for gui_input in inputs:
        try:
            trades, summary = run_vwap_backtest(gui_input.stock_file, gui_input.config)
            summary_path, result_path = save_a11_reports(gui_input.output_dir, trades, summary)
            outputs.append((summary_path, result_path))
        except Exception as exc:
            errors.append((gui_input, exc))

    for summary_path, result_path in outputs:
        print(f"summary: {summary_path}")
        print(f"results: {result_path}")
    show_batch_completion(outputs, errors)
