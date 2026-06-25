from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from app.data import vwap_price_repository
from app.domain.vwap_backtest import (
    BreakdownScoreInput,
    MA5_SLOWDOWN_ALLOW_ONE,
    MA5_SLOWDOWN_ALLOW_PREVIOUS_DAY,
    MA5_SLOWDOWN_ALLOW_THREE_DAYS_AGO,
    MA5_SLOWDOWN_REJECT_ANY,
    MA25_NEGATIVE_SLOPE_SCORE,
    build_trade_metrics,
    calculate_breakdown_score,
    calculate_ma5_breakdown_score,
    calculate_range_position_pct,
    calculate_vwap,
    first_threshold_touch,
    intraday_entry,
    intraday_range_position_pct,
    is_upper_stall,
    is_ma5_slope_slowdown_excluded,
    RESISTANCE_FAILURE_REJECT_ALL,
    RESISTANCE_FAILURE_REJECT_APPROACH,
)
from app.output.markdown_writer import _report_paths, _result_markdown, _summary_markdown
from app.usecases.run_vwap_backtest import _higher_high_count, _lower_low_count, build_summary, run_vwap_backtest
from app.domain.vwap_backtest import VwapBacktestConfig


class VwapCalculationTest(unittest.TestCase):
    def test_calculate_vwap_uses_typical_price_and_volume(self):
        rows = pd.DataFrame(
            {
                "High": [102.0, 112.0],
                "Low": [98.0, 108.0],
                "Close": [100.0, 110.0],
                "Volume": [100.0, 300.0],
            }
        )
        self.assertAlmostEqual(calculate_vwap(rows), 107.5)

    def test_intraday_entry_uses_last_completed_bar_before_cutoff(self):
        index = pd.to_datetime(["2026-06-10 10:55", "2026-06-10 11:00", "2026-06-10 11:05"])
        rows = pd.DataFrame(
            {
                "High": [100.0, 102.0, 104.0],
                "Low": [98.0, 100.0, 102.0],
                "Close": [99.0, 101.0, 103.0],
                "Volume": [100.0, 100.0, 100.0],
            },
            index=index,
        )
        price, vwap = intraday_entry(rows, pd.Timestamp("2026-06-10"), "11:00")
        self.assertEqual(price, 99.0)
        self.assertAlmostEqual(vwap, 99.0)

    def test_config_allows_previous_close_without_vwap_confirmation(self):
        config = VwapBacktestConfig(
            "2026-06-01",
            "2026-06-10",
            -5.0,
            5.0,
            "prev_close",
            require_vwap_confirmation=False,
        )

        config.validate()

    def test_config_rejects_unsupported_range_position_threshold(self):
        config = VwapBacktestConfig(
            "2026-06-01",
            "2026-06-10",
            -5.0,
            5.0,
            "11:00",
            range_position_min_pct=35.0,
        )
        with self.assertRaises(ValueError):
            config.validate()

    def test_config_rejects_unsupported_resistance_failure_policy(self):
        config = VwapBacktestConfig(
            "2026-06-01",
            "2026-06-10",
            -5.0,
            5.0,
            "11:00",
            resistance_failure_policy="unsupported",
        )
        with self.assertRaises(ValueError):
            config.validate()


class RangePositionTest(unittest.TestCase):
    def test_calculates_range_position_from_low_to_high(self):
        self.assertAlmostEqual(calculate_range_position_pct(90.0, 110.0, 100.0), 50.0)

    def test_zero_range_is_not_calculable(self):
        self.assertIsNone(calculate_range_position_pct(100.0, 100.0, 100.0))

    def test_intraday_range_position_uses_completed_bars_before_cutoff(self):
        index = pd.to_datetime(["2026-06-10 10:55", "2026-06-10 11:00"])
        rows = pd.DataFrame(
            {
                "High": [105.0, 120.0],
                "Low": [95.0, 80.0],
                "Close": [101.0, 119.0],
                "Volume": [100.0, 100.0],
            },
            index=index,
        )

        pct = intraday_range_position_pct(rows, pd.Timestamp("2026-06-10"), "11:00", 101.0)

        self.assertAlmostEqual(pct, 60.0)


class BreakdownScoreTest(unittest.TestCase):
    def test_upper_stall_requires_large_upper_wick_and_small_body(self):
        self.assertTrue(is_upper_stall(100.0, 112.0, 90.0, 102.0))
        self.assertFalse(is_upper_stall(100.0, 106.0, 90.0, 104.0))

    def test_ma5_breakdown_score_is_capped_at_three(self):
        score = calculate_ma5_breakdown_score(-1.0, 1.0, 2.0)

        self.assertEqual(score, 3)

    def test_calculates_breakdown_score_reasons(self):
        score = calculate_breakdown_score(
            BreakdownScoreInput(
                entry_price=99.0,
                vwap=100.0,
                higher_low_count_3d=0,
                higher_high_count_3d=0,
                range_position_pct=35.0,
                volume_ratio_20d=1.2,
                open_price=105.0,
                high_price=108.0,
                low_price=98.0,
                close_price=99.0,
                nearest_support_distance_atr=0.8,
                ma25_slope_pct=0.0,
                ma5_slope_pct=-1.0,
                previous_ma5_slope_pct=1.0,
                three_days_ago_ma5_slope_pct=2.0,
            )
        )

        self.assertEqual(score.total, 11)
        self.assertEqual(score.ma5_score, 3)
        self.assertIn("VWAP未満", score.reasons)
        self.assertIn("直下支持線が遠い", score.reasons)


class SupportResistanceFilterTest(unittest.TestCase):
    def _daily_and_intraday(self, *, close: float = 100.0, high: float = 102.0, low: float = 98.0):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=90)
        signal_date = dates[80]
        entry_date = dates[81]
        daily = pd.DataFrame(
            {
                "Open": [100.0] * len(dates),
                "High": [102.0] * len(dates),
                "Low": [98.0] * len(dates),
                "Close": [100.0] * len(dates),
                "Volume": [1000.0] * len(dates),
            },
            index=dates,
        )
        daily.loc[signal_date, ["Close", "High", "Low"]] = [close, high, low]
        intraday = pd.DataFrame(
            {"High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [100.0]},
            index=pd.to_datetime([f"{entry_date.date()} 10:55"]),
        )
        return dates, signal_date, daily, intraday

    def _run(self, daily, intraday, signal_date, **config_options):
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"),
            signal_date.strftime("%Y-%m-%d"),
            -5.0,
            5.0,
            "11:00",
            require_vwap_confirmation=False,
            **config_options,
        )
        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                return run_vwap_backtest(watchlist, config)

    def test_support_rebound_requires_a_test_and_reclaim_of_open_known_support(self):
        _, signal_date, daily, intraday = self._daily_and_intraday(close=101.0, high=103.0, low=99.0)

        trades, summary = self._run(daily, intraday, signal_date, require_support_rebound=True)

        self.assertEqual(len(trades), 1)
        self.assertTrue(trades.iloc[0]["support_rebound"])
        self.assertEqual(trades.iloc[0]["support_level_type"], "25日線")
        self.assertAlmostEqual(trades.iloc[0]["atr14_open"], 4.0)
        self.assertTrue(summary["require_support_rebound"])

    def test_approach_failure_policy_rejects_resistance_that_was_not_broken(self):
        _, signal_date, daily, intraday = self._daily_and_intraday(close=100.0, high=101.5, low=98.0)

        trades, summary = self._run(
            daily,
            intraday,
            signal_date,
            resistance_failure_policy=RESISTANCE_FAILURE_REJECT_APPROACH,
        )

        self.assertTrue(trades.empty)
        self.assertEqual(summary["skipped"]["抵抗線トライ失敗（接近失速）"], 1)

    def test_all_failure_policy_also_rejects_false_breakouts(self):
        _, signal_date, daily, intraday = self._daily_and_intraday(close=100.0, high=103.0, low=98.0)

        trades, summary = self._run(
            daily,
            intraday,
            signal_date,
            resistance_failure_policy=RESISTANCE_FAILURE_REJECT_ALL,
        )

        self.assertTrue(trades.empty)
        self.assertEqual(summary["skipped"]["抵抗線トライ失敗（だまし突破）"], 1)


class Ma5SlopeSlowdownTest(unittest.TestCase):
    def test_reject_any_excludes_previous_or_three_days_ago_slowdown(self):
        self.assertTrue(is_ma5_slope_slowdown_excluded(1.0, 2.0, 0.5, MA5_SLOWDOWN_REJECT_ANY))
        self.assertTrue(is_ma5_slope_slowdown_excluded(1.0, 0.5, 2.0, MA5_SLOWDOWN_REJECT_ANY))
        self.assertFalse(is_ma5_slope_slowdown_excluded(1.0, 0.5, 0.5, MA5_SLOWDOWN_REJECT_ANY))

    def test_allow_one_excludes_only_when_both_slowdowns_exist(self):
        self.assertFalse(is_ma5_slope_slowdown_excluded(1.0, 2.0, 0.5, MA5_SLOWDOWN_ALLOW_ONE))
        self.assertFalse(is_ma5_slope_slowdown_excluded(1.0, 0.5, 2.0, MA5_SLOWDOWN_ALLOW_ONE))
        self.assertTrue(is_ma5_slope_slowdown_excluded(1.0, 2.0, 2.0, MA5_SLOWDOWN_ALLOW_ONE))

    def test_direction_specific_allowance(self):
        self.assertFalse(is_ma5_slope_slowdown_excluded(1.0, 0.5, 2.0, MA5_SLOWDOWN_ALLOW_THREE_DAYS_AGO))
        self.assertTrue(is_ma5_slope_slowdown_excluded(1.0, 2.0, 0.5, MA5_SLOWDOWN_ALLOW_THREE_DAYS_AGO))
        self.assertFalse(is_ma5_slope_slowdown_excluded(1.0, 2.0, 0.5, MA5_SLOWDOWN_ALLOW_PREVIOUS_DAY))
        self.assertTrue(is_ma5_slope_slowdown_excluded(1.0, 0.5, 2.0, MA5_SLOWDOWN_ALLOW_PREVIOUS_DAY))

    def test_enabled_policy_excludes_when_slope_history_is_missing(self):
        self.assertTrue(is_ma5_slope_slowdown_excluded(None, 1.0, 1.0, MA5_SLOWDOWN_REJECT_ANY))


class TradeMetricsTest(unittest.TestCase):
    def test_future_closes_and_drawdown_are_based_on_entry_price(self):
        index = pd.bdate_range("2026-05-01", periods=17)
        daily = pd.DataFrame(
            {
                "Close": [100.0] + [101.0, 102.0, 103.0, 104.0, 105.0] + [110.0] * 9 + [115.0, 116.0],
                "High": [101.0] + [102.0, 103.0, 104.0, 105.0, 106.0] + [111.0] * 9 + [116.0, 117.0],
                "Low": [99.0] + [98.0, 97.0, 96.0, 95.0, 94.0] + [93.0] * 11,
            },
            index=index,
        )
        metrics = build_trade_metrics(daily, index[0], 100.0)
        self.assertEqual(metrics["sell_price_1d"], 101.0)
        self.assertEqual(metrics["sell_price_5d"], 105.0)
        self.assertEqual(metrics["sell_price_10d"], 110.0)
        self.assertEqual(metrics["sell_price_15d"], 115.0)
        self.assertEqual(metrics["minimum_price_5d"], 94.0)
        self.assertEqual(metrics["max_drawdown_5d"], -6.0)
        self.assertEqual(metrics["minimum_price_15d"], 93.0)
        self.assertEqual(metrics["max_drawdown_15d"], -7.0)
        self.assertAlmostEqual(metrics["max_favorable_excursion_5d_pct"], 6.0)
        self.assertAlmostEqual(metrics["max_favorable_excursion_15d_pct"], 16.0)
        self.assertEqual(metrics["first_touch_5d"], "minus_3pct")

    def test_drawdown_is_zero_when_all_future_lows_are_above_entry(self):
        index = pd.bdate_range("2026-05-01", periods=6)
        daily = pd.DataFrame({"Close": [100, 102, 103, 104, 105, 106], "Low": [99, 101, 102, 103, 104, 105]}, index=index)
        metrics = build_trade_metrics(daily, index[0], 100.0)
        self.assertEqual(metrics["max_drawdown_5d"], 0.0)
        self.assertEqual(metrics["max_drawdown_5d_pct"], 0.0)
        self.assertIsNone(metrics["max_drawdown_15d"])

    def test_first_threshold_touch_uses_the_first_reached_threshold(self):
        index = pd.bdate_range("2026-05-01", periods=6)
        daily = pd.DataFrame(
            {
                "Close": [100.0] * 6,
                "High": [100.0, 104.0, 106.0, 101.0, 101.0, 101.0],
                "Low": [100.0, 99.0, 99.0, 96.0, 99.0, 99.0],
            },
            index=index,
        )

        self.assertEqual(first_threshold_touch(daily, 0, 100.0, 5), "plus_5pct")

    def test_first_threshold_touch_ignores_same_day_double_touch(self):
        index = pd.bdate_range("2026-05-01", periods=6)
        daily = pd.DataFrame(
            {
                "Close": [100.0] * 6,
                "High": [100.0, 106.0, 101.0, 101.0, 101.0, 101.0],
                "Low": [100.0, 96.0, 99.0, 99.0, 99.0, 99.0],
            },
            index=index,
        )

        self.assertIsNone(first_threshold_touch(daily, 0, 100.0, 5))


class SummaryTest(unittest.TestCase):
    def test_win_rate_excludes_missing_future_results(self):
        trades = pd.DataFrame(
            {
                "return_1d_pct": [1.0, -1.0, None],
                "profit_loss_1d": [10.0, -10.0, None],
                "return_5d_pct": [2.0, None, None],
                "profit_loss_5d": [20.0, None, None],
                "return_10d_pct": [3.0, -2.0, None],
                "profit_loss_10d": [30.0, -20.0, None],
                "return_15d_pct": [4.0, None, None],
                "profit_loss_15d": [40.0, None, None],
                "max_drawdown_5d_pct": [-2.0, -3.0, -4.0],
                "max_favorable_excursion_5d_pct": [6.0, 1.0, 7.0],
                "first_touch_5d": ["plus_5pct", "minus_3pct", None],
            }
        )
        config = VwapBacktestConfig("2026-06-01", "2026-06-10", -5.0, 5.0, "11:00")
        summary = build_summary(trades, config, stock_count=2, evaluated=10, skipped={})
        self.assertEqual(summary["completed_1d"], 2)
        self.assertEqual(summary["win_rate_1d_pct"], 50.0)
        self.assertEqual(summary["completed_10d"], 2)
        self.assertEqual(summary["win_rate_10d_pct"], 50.0)
        self.assertEqual(summary["completed_15d"], 1)
        self.assertEqual(summary["win_rate_15d_pct"], 100.0)
        self.assertEqual(summary["average_max_drawdown_5d_pct"], -3.0)
        self.assertEqual(summary["median_max_drawdown_5d_pct"], -3.0)
        self.assertAlmostEqual(summary["adverse_3pct_rate_5d_pct"], 200.0 / 3.0)
        self.assertAlmostEqual(summary["reach_5pct_rate_5d_pct"], 200.0 / 3.0)
        self.assertEqual(summary["first_reach_5pct_rate_5d_pct"], 50.0)
        self.assertEqual(summary["first_adverse_3pct_rate_5d_pct"], 50.0)

    def test_summary_markdown_contains_five_day_key_metrics(self):
        trades = pd.DataFrame(
            {
                "return_1d_pct": [1.0],
                "profit_loss_1d": [1.0],
                "return_5d_pct": [4.5],
                "profit_loss_5d": [4.5],
                "return_10d_pct": [6.0],
                "profit_loss_10d": [6.0],
                "return_15d_pct": [7.0],
                "profit_loss_15d": [7.0],
                "max_drawdown_5d_pct": [-3.5],
                "max_favorable_excursion_5d_pct": [6.0],
                "first_touch_5d": ["plus_5pct"],
            }
        )
        config = VwapBacktestConfig("2026-06-01", "2026-06-10", -5.0, 5.0, "11:00")
        summary = build_summary(trades, config, stock_count=1, evaluated=1, skipped={})
        markdown = _summary_markdown(summary)
        self.assertIn("# A9r3バックテスト サマリー", markdown)
        self.assertIn("| 5営業日 | 100.00% | 100.00% | 6.00% | -3.50% | 100.00% | 0.00% |", markdown)
        self.assertIn("| 10営業日後 | 1 | 100.00% |", markdown)
        self.assertIn("- VWAP: 単独除外なし（崩れスコアで判定）", markdown)
        self.assertNotIn("合計損益", markdown)

    def test_report_paths_include_me25_condition_date_and_sequence(self):
        config = VwapBacktestConfig("2026-06-01", "2026-06-10", -1.0, 2.0, "11:00")
        summary = build_summary(pd.DataFrame(), config, stock_count=1, evaluated=0, skipped={})

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            first_summary, first_result = _report_paths(out_dir, summary, "06-17")
            first_summary.write_text("", encoding="utf-8")
            first_result.write_text("", encoding="utf-8")
            second_summary, second_result = _report_paths(out_dir, summary, "06-17")

        self.assertEqual(first_summary.name, "bt_v9r3_ME25(-1,2)-06-17_summary-1.md")
        self.assertEqual(first_result.name, "bt_v9r3_ME25(-1,2)-06-17_result-1.md")
        self.assertEqual(second_summary.name, "bt_v9r3_ME25(-1,2)-06-17_summary-2.md")
        self.assertEqual(second_result.name, "bt_v9r3_ME25(-1,2)-06-17_result-2.md")

    def test_result_markdown_shows_conditions_and_hides_entry_only_rows(self):
        trades = pd.DataFrame(
            [
                {
                    "entry_date": "2026-06-03",
                    "signal_date": "2026-06-02",
                    "name": "表示銘柄",
                    "code": "1111",
                    "entry_time": "11:00",
                    "vwap_confirmation_required": True,
                    "previous_close": 100.0,
                    "previous_ma25": 100.0,
                    "previous_dev25_pct": 0.0,
                    "lower_low_count_3d": 0,
                    "entry_price": 101.0,
                    "entry_range_position_pct": 50.0,
                    "entry_ma5": 100.0,
                    "ma5_slope_pct": 1.0,
                    "entry_ma25": 100.0,
                    "entry_dev25_pct": 1.0,
                    "ma25_slope_pct": 0.5,
                    "vwap": 100.0,
                    "vwap_margin_pct": 1.0,
                    "sell_price_1d": 102.0,
                    "profit_loss_1d": 1.0,
                    "return_1d_pct": 0.99,
                    "sell_price_5d": 106.0,
                    "profit_loss_5d": 5.0,
                    "return_5d_pct": 4.95,
                    "sell_price_10d": None,
                    "profit_loss_10d": None,
                    "return_10d_pct": None,
                    "sell_price_15d": None,
                    "profit_loss_15d": None,
                    "return_15d_pct": None,
                    "maximum_price_5d": 108.0,
                    "max_favorable_excursion_5d_pct": 6.93,
                    "minimum_price_5d": 98.0,
                    "max_drawdown_5d": -3.0,
                    "max_drawdown_5d_pct": -2.97,
                    "first_touch_5d": "plus_5pct",
                    "maximum_price_10d": None,
                    "max_favorable_excursion_10d_pct": None,
                    "minimum_price_10d": None,
                    "max_drawdown_10d": None,
                    "max_drawdown_10d_pct": None,
                    "first_touch_10d": None,
                    "maximum_price_15d": None,
                    "max_favorable_excursion_15d_pct": None,
                    "minimum_price_15d": None,
                    "max_drawdown_15d": None,
                    "max_drawdown_15d_pct": None,
                    "first_touch_15d": None,
                },
                {
                    "entry_date": "2026-06-04",
                    "signal_date": "2026-06-03",
                    "name": "非表示銘柄",
                    "code": "2222",
                    "return_5d_pct": None,
                },
            ]
        )
        config = VwapBacktestConfig("2026-06-01", "2026-06-10", -1.0, 2.0, "11:00")
        summary = build_summary(trades, config, stock_count=2, evaluated=2, skipped={})

        markdown = _result_markdown(trades, summary)

        self.assertIn("## 実行条件", markdown)
        self.assertIn("- 前日・当日25日乖離率: -1.0% < 乖離率 <= 2.0%", markdown)
        self.assertIn("- エントリーのみ: 1件", markdown)
        self.assertIn("- 3日間の高値更新条件: 考慮しない", markdown)
        self.assertIn("- 崩れスコア除外: 考慮しない", markdown)
        self.assertIn("表示銘柄", markdown)
        self.assertNotIn("非表示銘柄", markdown)


class LowerLowTest(unittest.TestCase):
    def test_counts_lower_lows_over_the_latest_three_comparisons(self):
        daily = pd.DataFrame({"Low": [100.0, 99.0, 101.0, 98.0]})
        self.assertEqual(_lower_low_count(daily, 3), 2)


class HigherHighTest(unittest.TestCase):
    def test_counts_higher_highs_over_the_latest_three_comparisons(self):
        daily = pd.DataFrame({"High": [100.0, 101.0, 99.0, 102.0]})
        self.assertEqual(_higher_high_count(daily, 3), 2)


class YfinanceCacheTest(unittest.TestCase):
    def test_reuses_cached_download_for_same_symbols_dates_and_interval(self):
        index = pd.to_datetime(["2026-06-01"])
        downloaded = pd.DataFrame(
            {"Open": [100.0], "High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [1000.0]},
            index=index,
        )

        with TemporaryDirectory() as tmp:
            with patch.object(vwap_price_repository, "CACHE_DIR", Path(tmp) / ".yfcache"), patch(
                "app.data.vwap_price_repository.yf.download", return_value=downloaded
            ) as download:
                first = vwap_price_repository._download_map([("テスト", "1234")], "2026-06-01", "2026-06-02", "1d")
                second = vwap_price_repository._download_map([("テスト", "1234")], "2026-06-01", "2026-06-02", "1d")

        self.assertEqual(download.call_count, 1)
        self.assertEqual(first["1234"].iloc[0]["Close"], 100.0)
        self.assertEqual(second["1234"].iloc[0]["Close"], 100.0)


class BacktestUsecaseTest(unittest.TestCase):
    def test_1100_mode_uses_signal_day_close_and_next_trade_day_intraday(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        entry_date = dates[29]
        daily = pd.DataFrame(
            {
                "Open": [100.0] * len(dates),
                "High": [102.0] * len(dates),
                "Low": [98.0] * len(dates),
                "Close": [100.0] * len(dates),
                "Volume": [1000.0] * len(dates),
            },
            index=dates,
        )
        intraday = pd.DataFrame(
            {
                "High": [101.0, 102.0],
                "Low": [99.0, 100.0],
                "Close": [101.0, 102.0],
                "Volume": [100.0, 100.0],
            },
            index=pd.to_datetime([f"{entry_date.date()} 10:55", f"{entry_date.date()} 11:00"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"),
            signal_date.strftime("%Y-%m-%d"),
            -1.0,
            1.0,
            "11:00",
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, summary = run_vwap_backtest(watchlist, config)

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0]["signal_date"], signal_date.strftime("%Y-%m-%d"))
        self.assertEqual(trades.iloc[0]["entry_date"], entry_date.strftime("%Y-%m-%d"))
        self.assertEqual(trades.iloc[0]["entry_price"], 101.0)
        self.assertGreaterEqual(trades.iloc[0]["ma25_slope_pct"], 0.0)
        self.assertGreater(trades.iloc[0]["entry_dev25_pct"], -1.0)
        self.assertLessEqual(trades.iloc[0]["entry_dev25_pct"], 1.0)
        self.assertEqual(summary["entry_count"], 1)

    def test_rejects_entry_when_current_deviation_is_outside_range(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        entry_date = dates[29]
        daily = pd.DataFrame(
            {"Open": 100.0, "High": 102.0, "Low": 98.0, "Close": 100.0, "Volume": 1000.0},
            index=dates,
        )
        intraday = pd.DataFrame(
            {"High": [111.0], "Low": [109.0], "Close": [110.0], "Volume": [100.0]},
            index=pd.to_datetime([f"{entry_date.date()} 10:55"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"), signal_date.strftime("%Y-%m-%d"), -1.0, 1.0, "11:00"
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, summary = run_vwap_backtest(watchlist, config)

        self.assertTrue(trades.empty)
        self.assertEqual(summary["skipped"]["当日25日乖離率が範囲外"], 1)

    def test_rejects_entry_when_provisional_ma25_is_falling(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        entry_date = dates[29]
        closes = [101.0] * len(dates)
        closes[28] = 100.0
        daily = pd.DataFrame(
            {"Open": closes, "High": [102.0] * len(dates), "Low": [98.0] * len(dates),
             "Close": closes, "Volume": [1000.0] * len(dates)},
            index=dates,
        )
        intraday = pd.DataFrame(
            {"High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [100.0]},
            index=pd.to_datetime([f"{entry_date.date()} 10:55"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"), signal_date.strftime("%Y-%m-%d"), -2.0, 2.0, "11:00"
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, summary = run_vwap_backtest(watchlist, config)

        self.assertTrue(trades.empty)
        self.assertEqual(summary["skipped"]["25日線が下向き"], 1)

    def test_negative_ma25_slope_can_be_counted_in_breakdown_score(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        entry_date = dates[29]
        closes = [101.0] * len(dates)
        closes[28] = 100.0
        daily = pd.DataFrame(
            {
                "Open": closes,
                "High": [102.0] * len(dates),
                "Low": [98.0] * len(dates),
                "Close": closes,
                "Volume": [1000.0] * len(dates),
            },
            index=dates,
        )
        intraday = pd.DataFrame(
            {"High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [100.0]},
            index=pd.to_datetime([f"{entry_date.date()} 10:55"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"),
            signal_date.strftime("%Y-%m-%d"),
            -2.0,
            2.0,
            "11:00",
            ma25_negative_slope_policy=MA25_NEGATIVE_SLOPE_SCORE,
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, summary = run_vwap_backtest(watchlist, config)

        self.assertEqual(len(trades), 1)
        self.assertGreaterEqual(trades.iloc[0]["breakdown_score"], 2)
        self.assertIn("25日線横ばい以下", trades.iloc[0]["breakdown_reasons"])
        self.assertEqual(summary["ma25_negative_slope_policy"], MA25_NEGATIVE_SLOPE_SCORE)

    def test_rejects_entry_when_required_ma5_slope_is_not_positive(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        entry_date = dates[29]
        closes = [100.0] * len(dates)
        closes[4] = 90.0
        closes[28] = 110.0
        daily = pd.DataFrame(
            {
                "Open": closes,
                "High": [112.0] * len(dates),
                "Low": [98.0] * len(dates),
                "Close": closes,
                "Volume": [1000.0] * len(dates),
            },
            index=dates,
        )
        intraday = pd.DataFrame(
            {"High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [100.0]},
            index=pd.to_datetime([f"{entry_date.date()} 10:55"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"),
            signal_date.strftime("%Y-%m-%d"),
            -20.0,
            20.0,
            "11:00",
            require_ma5_slope_positive=True,
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, summary = run_vwap_backtest(watchlist, config)

        self.assertTrue(trades.empty)
        self.assertEqual(summary["skipped"]["5日線が上向きでない"], 1)

    def test_rejects_entry_when_ma5_slope_slowdown_policy_excludes_both(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        entry_date = dates[29]
        closes = [100.0] * len(dates)
        closes[21:29] = [100.0, 101.0, 102.0, 104.0, 107.0, 111.0, 116.0, 122.0]
        daily = pd.DataFrame(
            {
                "Open": closes,
                "High": [130.0] * len(dates),
                "Low": [95.0] * len(dates),
                "Close": closes,
                "Volume": [1000.0] * len(dates),
            },
            index=dates,
        )
        intraday = pd.DataFrame(
            {"High": [110.0], "Low": [110.0], "Close": [110.0], "Volume": [100.0]},
            index=pd.to_datetime([f"{entry_date.date()} 10:55"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"),
            signal_date.strftime("%Y-%m-%d"),
            -20.0,
            20.0,
            "11:00",
            ma5_slope_slowdown_policy=MA5_SLOWDOWN_ALLOW_ONE,
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, summary = run_vwap_backtest(watchlist, config)

        self.assertTrue(trades.empty)
        self.assertEqual(summary["skipped"]["5日線傾き鈍化"], 1)
        self.assertEqual(summary["ma5_slope_slowdown_policy"], MA5_SLOWDOWN_ALLOW_ONE)

    def test_below_vwap_adds_breakdown_score_without_rejecting_by_itself(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        entry_date = dates[29]
        daily = pd.DataFrame(
            {"Open": 100.0, "High": 102.0, "Low": 98.0, "Close": 100.0, "Volume": 1000.0},
            index=dates,
        )
        intraday = pd.DataFrame(
            {"High": [102.0], "Low": [100.0], "Close": [100.0], "Volume": [100.0]},
            index=pd.to_datetime([f"{entry_date.date()} 10:55"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"), signal_date.strftime("%Y-%m-%d"), -1.0, 1.0, "11:00"
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, summary = run_vwap_backtest(watchlist, config)

        self.assertEqual(len(trades), 1)
        self.assertGreaterEqual(trades.iloc[0]["breakdown_score"], 1)
        self.assertIn("VWAP未満", trades.iloc[0]["breakdown_reasons"])
        self.assertNotIn("VWAP未維持", summary["skipped"])

    def test_rejects_entry_when_breakdown_score_reaches_threshold(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        entry_date = dates[29]
        daily = pd.DataFrame(
            {"Open": 100.0, "High": 102.0, "Low": 98.0, "Close": 100.0, "Volume": 1000.0},
            index=dates,
        )
        intraday = pd.DataFrame(
            {"High": [102.0], "Low": [100.0], "Close": [100.0], "Volume": [100.0]},
            index=pd.to_datetime([f"{entry_date.date()} 10:55"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"),
            signal_date.strftime("%Y-%m-%d"),
            -1.0,
            1.0,
            "11:00",
            breakdown_score_threshold=1,
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, summary = run_vwap_backtest(watchlist, config)

        self.assertTrue(trades.empty)
        self.assertEqual(summary["skipped"]["崩れスコア1点以上"], 1)

    def test_rejects_entry_when_higher_high_count_is_below_required_count(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        entry_date = dates[29]
        highs = [102.0] * len(dates)
        highs[25:29] = [100.0, 101.0, 100.0, 100.0]
        daily = pd.DataFrame(
            {"Open": 100.0, "High": highs, "Low": 98.0, "Close": 100.0, "Volume": 1000.0},
            index=dates,
        )
        intraday = pd.DataFrame(
            {"High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [100.0]},
            index=pd.to_datetime([f"{entry_date.date()} 10:55"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"),
            signal_date.strftime("%Y-%m-%d"),
            -1.0,
            1.0,
            "11:00",
            higher_high_exclude_count=2,
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, summary = run_vwap_backtest(watchlist, config)

        self.assertTrue(trades.empty)
        self.assertEqual(summary["skipped"]["高値更新回数が必要回数未満"], 1)

    def test_accepts_entry_when_higher_high_count_meets_required_count(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        entry_date = dates[29]
        highs = [102.0] * len(dates)
        highs[25:29] = [100.0, 101.0, 100.0, 101.0]
        daily = pd.DataFrame(
            {"Open": 100.0, "High": highs, "Low": 98.0, "Close": 100.0, "Volume": 1000.0},
            index=dates,
        )
        intraday = pd.DataFrame(
            {"High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [100.0]},
            index=pd.to_datetime([f"{entry_date.date()} 10:55"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"),
            signal_date.strftime("%Y-%m-%d"),
            -1.0,
            1.0,
            "11:00",
            higher_high_exclude_count=2,
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, summary = run_vwap_backtest(watchlist, config)

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0]["higher_high_count_3d"], 2)
        self.assertEqual(summary["higher_high_exclude_count"], 2)

    def test_enters_at_selected_time_without_vwap_confirmation(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        entry_date = dates[29]
        daily = pd.DataFrame(
            {"Open": 100.0, "High": 102.0, "Low": 98.0, "Close": 100.0, "Volume": 1000.0},
            index=dates,
        )
        intraday = pd.DataFrame(
            {"High": [102.0], "Low": [100.0], "Close": [100.0], "Volume": [100.0]},
            index=pd.to_datetime([f"{entry_date.date()} 10:55"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"),
            signal_date.strftime("%Y-%m-%d"),
            -1.0,
            1.0,
            "11:00",
            require_vwap_confirmation=False,
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, summary = run_vwap_backtest(watchlist, config)

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0]["entry_price"], 100.0)
        self.assertFalse(trades.iloc[0]["vwap_confirmation_required"])
        self.assertEqual(summary["entry_count"], 1)
        self.assertFalse(summary["require_vwap_confirmation"])

    def test_enters_without_calculable_vwap_when_confirmation_is_off(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        entry_date = dates[29]
        daily = pd.DataFrame(
            {"Open": 100.0, "High": 102.0, "Low": 98.0, "Close": 100.0, "Volume": 1000.0},
            index=dates,
        )
        intraday = pd.DataFrame(
            {"High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [0.0]},
            index=pd.to_datetime([f"{entry_date.date()} 10:55"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"),
            signal_date.strftime("%Y-%m-%d"),
            -1.0,
            1.0,
            "11:00",
            require_vwap_confirmation=False,
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, _ = run_vwap_backtest(watchlist, config)

        self.assertEqual(len(trades), 1)
        self.assertTrue(pd.isna(trades.iloc[0]["vwap"]))

    def test_rejects_entry_at_selected_lower_low_threshold(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        entry_date = dates[29]
        lows = [99.0] * len(dates)
        lows[25:29] = [102.0, 101.0, 100.0, 99.0]
        daily = pd.DataFrame(
            {"Open": 100.0, "High": 102.0, "Low": lows, "Close": 100.0, "Volume": 1000.0},
            index=dates,
        )
        intraday = pd.DataFrame(
            {"High": [101.0], "Low": [99.0], "Close": [100.0], "Volume": [100.0]},
            index=pd.to_datetime([f"{entry_date.date()} 10:55"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"),
            signal_date.strftime("%Y-%m-%d"),
            -1.0,
            1.0,
            "11:00",
            lower_low_exclude_count=3,
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, summary = run_vwap_backtest(watchlist, config)

        self.assertTrue(trades.empty)
        self.assertEqual(summary["skipped"]["安値切り下げ回数が除外基準以上"], 1)

    def test_rejects_entry_below_selected_range_position_threshold(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        entry_date = dates[29]
        daily = pd.DataFrame(
            {"Open": 100.0, "High": 102.0, "Low": 98.0, "Close": 100.0, "Volume": 1000.0},
            index=dates,
        )
        intraday = pd.DataFrame(
            {"High": [110.0], "Low": [90.0], "Close": [100.0], "Volume": [100.0]},
            index=pd.to_datetime([f"{entry_date.date()} 10:55"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"),
            signal_date.strftime("%Y-%m-%d"),
            -1.0,
            1.0,
            "11:00",
            range_position_min_pct=60.0,
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, summary = run_vwap_backtest(watchlist, config)

        self.assertTrue(trades.empty)
        self.assertEqual(summary["skipped"]["終端位置が条件未満"], 1)

    def test_prev_close_range_position_uses_signal_day_daily_range(self):
        dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=50)
        signal_date = dates[28]
        daily = pd.DataFrame(
            {"Open": 100.0, "High": 110.0, "Low": 90.0, "Close": 102.0, "Volume": 1000.0},
            index=dates,
        )
        intraday = pd.DataFrame(
            {"High": [105.0], "Low": [95.0], "Close": [102.0], "Volume": [100.0]},
            index=pd.to_datetime([f"{signal_date.date()} 15:25"]),
        )
        config = VwapBacktestConfig(
            signal_date.strftime("%Y-%m-%d"),
            signal_date.strftime("%Y-%m-%d"),
            -1.0,
            3.0,
            "prev_close",
            range_position_min_pct=60.0,
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch("app.usecases.run_vwap_backtest.fetch_daily_prices", return_value={"1234": daily}), patch(
                "app.usecases.run_vwap_backtest.fetch_intraday_prices", return_value={"1234": intraday}
            ):
                trades, summary = run_vwap_backtest(watchlist, config)

        self.assertEqual(len(trades), 1)
        self.assertAlmostEqual(trades.iloc[0]["entry_range_position_pct"], 60.0)
        self.assertEqual(summary["range_position_min_pct"], 60.0)


if __name__ == "__main__":
    unittest.main()
