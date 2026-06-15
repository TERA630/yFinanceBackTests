"""Application entry point."""

from __future__ import annotations

from app.output.csv_writer import save_outputs
from app.presentation.cli import build_parser, resolve_inputs
from app.presentation.gui import show_completion_message
from app.usecases.run_backtest import run_backtest_A7R2


def main():
    parser = build_parser()
    args = parser.parse_args()

    resolved = resolve_inputs(args)
    if resolved is None:
        return

    stock_md_path, start_date, end_date, out_dir, lower_low_exclude_count = resolved
    signals_df, summary_df = run_backtest_A7R2(
        stock_md_path,
        start_date,
        end_date,
        lower_low_exclude_count=lower_low_exclude_count,
    )
    signals_path, summary_path = save_outputs(out_dir, start_date, end_date, signals_df, summary_df)

    print("")
    print("完了")
    print(f"signals: {signals_path}")
    print(f"summary: {summary_path}")

    if not summary_df.empty:
        print("")
        print(summary_df.to_string(index=False))

    show_completion_message(signals_path, summary_path)
