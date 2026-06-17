import unittest
from pathlib import Path

import pandas as pd

from app.domain.vwap_backtest import A8BacktestConfig, ENTRY_1100, ENTRY_1400, ENTRY_PREV_CLOSE
from app.presentation.a8_gui import A8GuiInput, append_saved_condition, default_date_range, summarize_condition


class A8GuiDateDefaultsTests(unittest.TestCase):
    def test_weekday_uses_today_and_forty_business_days_before(self):
        start, end = default_date_range(pd.Timestamp("2026-06-15"))

        self.assertEqual(end, pd.Timestamp("2026-06-15"))
        self.assertEqual(len(pd.bdate_range(start, end)), 41)

    def test_weekend_uses_previous_friday(self):
        start, end = default_date_range(pd.Timestamp("2026-06-14"))

        self.assertEqual(end, pd.Timestamp("2026-06-12"))
        self.assertEqual(len(pd.bdate_range(start, end)), 41)


class A8GuiSavedConditionTests(unittest.TestCase):
    def test_saved_condition_queue_keeps_latest_five(self):
        queue = []
        for index in range(6):
            append_saved_condition(
                queue,
                A8GuiInput(
                    Path(f"stock_{index}.md"),
                    Path("."),
                    A8BacktestConfig(
                        "2026-06-01",
                        "2026-06-10",
                        -5.0 + index,
                        5.0,
                        ENTRY_1100,
                    ),
                ),
            )

        self.assertEqual(len(queue), 5)
        self.assertEqual(queue[0].stock_file, Path("stock_1.md"))
        self.assertEqual(queue[-1].stock_file, Path("stock_5.md"))

    def test_condition_summary_excludes_paths_and_dates(self):
        summary = summarize_condition(
            A8GuiInput(
                Path("watchlist.md"),
                Path("out"),
                A8BacktestConfig(
                    "2026-06-01",
                    "2026-06-10",
                    -3.5,
                    4.0,
                    ENTRY_1400,
                    lower_low_exclude_count=2,
                    require_vwap_confirmation=False,
                ),
            )
        )

        self.assertIn("25日乖離 -3.5%超-4%以下", summary)
        self.assertIn("VWAPなし", summary)
        self.assertIn("14:00", summary)
        self.assertIn("安値2回以上除外", summary)
        self.assertNotIn("watchlist", summary)
        self.assertNotIn("2026-06", summary)

    def test_prev_close_condition_summary_uses_japanese_label(self):
        summary = summarize_condition(
            A8GuiInput(
                Path("watchlist.md"),
                Path("out"),
                A8BacktestConfig(
                    "2026-06-01",
                    "2026-06-10",
                    -5.0,
                    5.0,
                    ENTRY_PREV_CLOSE,
                ),
            )
        )

        self.assertIn("前日終値", summary)

    def test_condition_summary_includes_range_position_threshold(self):
        summary = summarize_condition(
            A8GuiInput(
                Path("watchlist.md"),
                Path("out"),
                A8BacktestConfig(
                    "2026-06-01",
                    "2026-06-10",
                    -5.0,
                    5.0,
                    ENTRY_1100,
                    range_position_min_pct=40.0,
                ),
            )
        )

        self.assertIn("終端位置40%以上", summary)


if __name__ == "__main__":
    unittest.main()
