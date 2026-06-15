from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from app.domain.vwap_backtest import build_trade_metrics, calculate_vwap, intraday_entry
from app.output.markdown_writer import _summary_markdown
from app.usecases.run_vwap_backtest import build_summary, run_vwap_backtest
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


class TradeMetricsTest(unittest.TestCase):
    def test_future_closes_and_drawdown_are_based_on_entry_price(self):
        index = pd.bdate_range("2026-05-01", periods=22)
        daily = pd.DataFrame(
            {
                "Close": [100.0] + [101.0, 102.0, 103.0, 104.0, 105.0] + [110.0] * 14 + [120.0, 121.0],
                "Low": [99.0] + [98.0, 97.0, 96.0, 95.0, 94.0] + [93.0] * 16,
            },
            index=index,
        )
        metrics = build_trade_metrics(daily, index[0], 100.0)
        self.assertEqual(metrics["sell_price_1d"], 101.0)
        self.assertEqual(metrics["sell_price_5d"], 105.0)
        self.assertEqual(metrics["sell_price_20d"], 120.0)
        self.assertEqual(metrics["minimum_price_5d"], 94.0)
        self.assertEqual(metrics["max_drawdown_5d"], -6.0)
        self.assertEqual(metrics["minimum_price_20d"], 93.0)
        self.assertEqual(metrics["max_drawdown_20d"], -7.0)

    def test_drawdown_is_zero_when_all_future_lows_are_above_entry(self):
        index = pd.bdate_range("2026-05-01", periods=6)
        daily = pd.DataFrame({"Close": [100, 102, 103, 104, 105, 106], "Low": [99, 101, 102, 103, 104, 105]}, index=index)
        metrics = build_trade_metrics(daily, index[0], 100.0)
        self.assertEqual(metrics["max_drawdown_5d"], 0.0)
        self.assertEqual(metrics["max_drawdown_5d_pct"], 0.0)
        self.assertIsNone(metrics["max_drawdown_20d"])


class SummaryTest(unittest.TestCase):
    def test_win_rate_excludes_missing_future_results(self):
        trades = pd.DataFrame(
            {
                "return_1d_pct": [1.0, -1.0, None],
                "profit_loss_1d": [10.0, -10.0, None],
                "return_5d_pct": [2.0, None, None],
                "profit_loss_5d": [20.0, None, None],
                "max_drawdown_5d_pct": [-2.0, -3.0, -4.0],
                "return_20d_pct": [None, None, None],
                "profit_loss_20d": [None, None, None],
            }
        )
        config = VwapBacktestConfig("2026-06-01", "2026-06-10", -5.0, 5.0, "11:00")
        summary = build_summary(trades, config, stock_count=2, evaluated=10, skipped={})
        self.assertEqual(summary["completed_1d"], 2)
        self.assertEqual(summary["win_rate_1d_pct"], 50.0)
        self.assertEqual(summary["completed_20d"], 0)
        self.assertIsNone(summary["win_rate_20d_pct"])
        self.assertEqual(summary["average_max_drawdown_5d_pct"], -3.0)
        self.assertEqual(summary["median_max_drawdown_5d_pct"], -3.0)
        self.assertAlmostEqual(summary["adverse_3pct_rate_5d_pct"], 200.0 / 3.0)

    def test_summary_markdown_contains_five_day_key_metrics(self):
        trades = pd.DataFrame(
            {
                "return_1d_pct": [1.0],
                "profit_loss_1d": [1.0],
                "return_5d_pct": [4.5],
                "profit_loss_5d": [4.5],
                "max_drawdown_5d_pct": [-3.5],
                "return_20d_pct": [5.0],
                "profit_loss_20d": [5.0],
            }
        )
        config = VwapBacktestConfig("2026-06-01", "2026-06-10", -5.0, 5.0, "11:00")
        summary = build_summary(trades, config, stock_count=1, evaluated=1, skipped={})
        markdown = _summary_markdown(summary)
        self.assertIn("5営業日後リターン: 4.50%", markdown)
        self.assertIn("最大含み損 平均: -3.50%", markdown)
        self.assertIn("最大含み損 中央値: -3.50%", markdown)
        self.assertIn("-3%逆行率: 100.00%", markdown)


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

    def test_rejects_entry_when_price_is_below_vwap(self):
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

        self.assertTrue(trades.empty)
        self.assertEqual(summary["skipped"]["VWAP未維持"], 1)


if __name__ == "__main__":
    unittest.main()
