import unittest
from pathlib import Path

import pandas as pd

from app.domain.vwap_backtest import (
    A8BacktestConfig,
    ENTRY_1100,
    ENTRY_1400,
    ENTRY_OPEN,
    ENTRY_PREV_CLOSE,
    MA5_SLOWDOWN_ALLOW_ONE,
)
from app.presentation.a8_gui import A8GuiInput, append_saved_condition, default_date_range, summarize_condition


class A8GuiDateDefaultsTests(unittest.TestCase):
    def test_weekday_uses_earliest_business_day_within_sixty_calendar_days(self):
        start, end = default_date_range(pd.Timestamp("2026-06-15"))

        self.assertEqual(end, pd.Timestamp("2026-06-15"))
        self.assertEqual(start, pd.Timestamp("2026-04-17"))

    def test_weekend_uses_previous_friday(self):
        start, end = default_date_range(pd.Timestamp("2026-06-14"))

        self.assertEqual(end, pd.Timestamp("2026-06-12"))
        self.assertEqual(start, pd.Timestamp("2026-04-16"))

    def test_rolls_start_forward_when_sixty_day_limit_is_weekend(self):
        start, end = default_date_range(pd.Timestamp("2026-06-17"))

        self.assertEqual(end, pd.Timestamp("2026-06-17"))
        self.assertEqual(start, pd.Timestamp("2026-04-20"))


class A8GuiSavedConditionTests(unittest.TestCase):
    def test_saved_condition_queue_keeps_latest_eight(self):
        queue = []
        for index in range(9):
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

        self.assertEqual(len(queue), 8)
        self.assertEqual(queue[0].stock_file, Path("stock_1.md"))
        self.assertEqual(queue[-1].stock_file, Path("stock_8.md"))

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
                    require_ma5_slope_positive=True,
                ),
            )
        )

        self.assertIn("25日乖離 -3.5%超-4%以下", summary)
        self.assertIn("日中足:14:00", summary)
        self.assertIn("安値切下げ:3日のうち2回安値切下げ", summary)
        self.assertIn("高値更新考慮なし", summary)
        self.assertIn("支持線距離考慮なし", summary)
        self.assertIn("5日線上向き", summary)
        self.assertIn("25日線傾き:傾き負を即除外", summary)
        self.assertIn("崩れスコア考慮なし", summary)
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

        self.assertIn("日足:前日終値", summary)

    def test_open_condition_summary_uses_daily_label(self):
        summary = summarize_condition(
            A8GuiInput(
                Path("watchlist.md"),
                Path("out"),
                A8BacktestConfig(
                    "2026-06-01",
                    "2026-06-10",
                    -5.0,
                    5.0,
                    ENTRY_OPEN,
                ),
            )
        )

        self.assertIn("日足:翌営業日始値", summary)

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

    def test_condition_summary_uses_close_position_for_daily_range_position(self):
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
                    range_position_min_pct=40.0,
                ),
            )
        )

        self.assertIn("終値位置40%以上", summary)

    def test_condition_summary_includes_support_distance_filter(self):
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
                    support_distance_max_atr=0.7,
                ),
            )
        )

        self.assertIn("支持線距離0.7ATR以内", summary)

    def test_condition_summary_includes_higher_high_exclusion(self):
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
                    higher_high_exclude_count=2,
                ),
            )
        )

        self.assertIn("高値更新2回以上", summary)

    def test_condition_summary_includes_ma5_slope_slowdown_policy(self):
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
                    ma5_slope_slowdown_policy=MA5_SLOWDOWN_ALLOW_ONE,
                ),
            )
        )

        self.assertIn("5日線鈍化:前日・3日前のいずれかのみ許容", summary)

if __name__ == "__main__":
    unittest.main()
