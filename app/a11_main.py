"""Official application entry point for the A11 backtest."""

from __future__ import annotations

from dataclasses import replace

from app.domain.vwap_backtest import BACKTEST_METHOD_POSITION
from app.output.markdown_writer import save_a11_reports, save_position_report
from app.presentation.backtest_gui import request_backtest_inputs, show_batch_completion
from app.usecases.run_position_backtest import run_position_backtest
from app.usecases.run_vwap_backtest import run_vwap_backtest


def main() -> None:
    inputs = request_backtest_inputs()
    if inputs is None:
        return

    outputs = []
    errors = []
    processed_position_settings = set()
    for gui_input in inputs:
        try:
            if gui_input.config.backtest_method == BACKTEST_METHOD_POSITION:
                normalized_config = replace(gui_input.config, dev25_min=-4.0, dev25_max=12.0)
                position_key = (gui_input.stock_file, gui_input.output_dir, normalized_config)
                if position_key in processed_position_settings:
                    continue
                processed_position_settings.add(position_key)
                trades, summary = run_position_backtest(gui_input.stock_file, normalized_config)
                result_path = save_position_report(gui_input.output_dir, trades, summary)
                outputs.append((result_path,))
            else:
                trades, summary = run_vwap_backtest(gui_input.stock_file, gui_input.config)
                summary_path, result_path = save_a11_reports(gui_input.output_dir, trades, summary)
                outputs.append((summary_path, result_path))
        except Exception as exc:
            errors.append((gui_input, exc))

    for output_paths in outputs:
        for output_path in output_paths:
            print(f"output: {output_path}")
    show_batch_completion(outputs, errors)
