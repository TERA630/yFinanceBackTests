"""Official application entry point for the A9r4 backtest."""

from __future__ import annotations

from app.output.markdown_writer import save_a9r4_reports, save_market_filter_diagnostics
from app.presentation.a8_gui import request_a8_backtest_input, show_a8_batch_completion
from app.usecases.diagnose_market_filters import diagnose_market_filters
from app.usecases.run_vwap_backtest import run_a8_backtest


def main() -> None:
    inputs = request_a8_backtest_input()
    if inputs is None:
        return

    outputs = []
    diagnostics_outputs = []
    errors = []
    for gui_input in inputs:
        try:
            if gui_input.action == "market_diagnostics":
                diagnostics = diagnose_market_filters(
                    gui_input.stock_file,
                    gui_input.config,
                    ignore_cache=gui_input.ignore_market_cache,
                )
                diagnostics_outputs.append(save_market_filter_diagnostics(gui_input.output_dir, diagnostics))
            else:
                trades, summary = run_a8_backtest(gui_input.stock_file, gui_input.config)
                summary_path, result_path = save_a9r4_reports(gui_input.output_dir, trades, summary)
                outputs.append((summary_path, result_path))
        except Exception as exc:
            errors.append((gui_input, exc))

    for summary_path, result_path in outputs:
        print(f"summary: {summary_path}")
        print(f"results: {result_path}")
    for diagnostics_path in diagnostics_outputs:
        print(f"market diagnostics: {diagnostics_path}")
    show_a8_batch_completion(outputs, errors, diagnostics_outputs)
