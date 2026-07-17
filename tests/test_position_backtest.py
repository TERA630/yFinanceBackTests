from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from app.domain.position_backtest import (
    DUPLICATE_HOLDING,
    DUPLICATE_MIN_INTERVAL,
    DUPLICATE_NOT_RESET,
    EXIT_HORIZON,
    EXIT_STOP_LOSS,
    EXIT_TAKE_PROFIT,
    determine_position_exit,
    simulate_positions,
)
from app.output.markdown_writer import _position_markdown
from app.usecases.run_position_backtest import build_position_summary
from app.usecases.run_position_backtest import run_position_backtest
from app.domain.vwap_backtest import BACKTEST_METHOD_POSITION, VwapBacktestConfig


def _daily(*, periods: int = 12, early_stop: bool = False) -> pd.DataFrame:
    dates = pd.bdate_range("2026-06-01", periods=periods)
    daily = pd.DataFrame(
        {
            "Open": 100.0,
            "High": 102.0,
            "Low": 98.0,
            "Close": 100.0,
            "Volume": 1000.0,
        },
        index=dates,
    )
    if early_stop:
        daily.loc[dates[1], "Low"] = 96.0
    return daily


def _candidate(code: str, date: pd.Timestamp, band_min: float = -2.0) -> dict:
    return {
        "code": code,
        "name": f"銘柄{code}",
        "signal_date": date,
        "entry_date": date,
        "entry_price": 100.0,
        "dev25_band_min": band_min,
        "dev25_band_max": band_min + 2.0,
    }


class PositionExitTest(unittest.TestCase):
    def test_same_day_take_profit_and_stop_loss_uses_stop_loss(self):
        daily = _daily()
        daily.iloc[1, daily.columns.get_loc("High")] = 106.0
        daily.iloc[1, daily.columns.get_loc("Low")] = 96.0

        result = determine_position_exit(daily, daily.index[0], 100.0, 5)

        self.assertEqual(result.reason, EXIT_STOP_LOSS)
        self.assertEqual(result.date, daily.index[1])
        self.assertEqual(result.price, 97.0)

    def test_take_profit_uses_exact_five_percent_price(self):
        daily = _daily()
        daily.iloc[1, daily.columns.get_loc("High")] = 106.0

        result = determine_position_exit(daily, daily.index[0], 100.0, 5)

        self.assertEqual(result.reason, EXIT_TAKE_PROFIT)
        self.assertEqual(result.price, 105.0)

    def test_unreached_thresholds_exit_at_horizon_close(self):
        daily = _daily()
        daily.iloc[5, daily.columns.get_loc("Close")] = 103.0

        result = determine_position_exit(daily, daily.index[0], 100.0, 5)

        self.assertEqual(result.reason, EXIT_HORIZON)
        self.assertEqual(result.date, daily.index[5])
        self.assertEqual(result.price, 103.0)


class PositionStateTest(unittest.TestCase):
    def test_classifies_all_duplicate_reasons_and_allows_reset_reentry(self):
        daily_a = _daily()
        daily_b = _daily(early_stop=True)
        daily_c = _daily(early_stop=True)
        dates = daily_a.index
        candidates = pd.DataFrame(
            [
                _candidate("A", dates[0]),
                _candidate("B", dates[0]),
                _candidate("C", dates[0]),
                _candidate("A", dates[1]),
                _candidate("B", dates[2], band_min=0.0),
                _candidate("C", dates[3]),
                _candidate("C", dates[4]),
            ]
        )

        result = simulate_positions(
            candidates,
            {"A": daily_a, "B": daily_b, "C": daily_c},
            holding_period_days=5,
        )

        self.assertEqual(result.signal_count, 7)
        self.assertEqual(len(result.trades), 4)
        self.assertEqual(result.duplicate_counts[DUPLICATE_HOLDING], 1)
        self.assertEqual(result.duplicate_counts[DUPLICATE_NOT_RESET], 1)
        self.assertEqual(result.duplicate_counts[DUPLICATE_MIN_INTERVAL], 1)
        c_entries = result.trades.loc[result.trades["code"] == "C", "signal_date"].tolist()
        self.assertEqual(c_entries, [dates[0], dates[4]])


class PositionSummaryTest(unittest.TestCase):
    def test_summary_counts_match_signals_entries_and_duplicate_breakdown(self):
        daily = _daily()
        dates = daily.index
        candidates = pd.DataFrame([_candidate("A", dates[0]), _candidate("A", dates[1])])
        simulation = simulate_positions(candidates, {"A": daily}, 5)
        config = VwapBacktestConfig(
            "2026-06-01",
            "2026-06-12",
            -4.0,
            12.0,
            "prev_close",
            backtest_method=BACKTEST_METHOD_POSITION,
        )

        summary = build_position_summary(config, {5: simulation}, stock_count=3)
        period = summary["periods"][5]

        self.assertEqual(period["signal_count"], 2)
        self.assertEqual(period["independent_entry_count"], 1)
        self.assertEqual(period["duplicate_count"], 1)
        self.assertEqual(period["target_stock_count"], 1)

    def test_markdown_contains_requested_counts_without_wave_count(self):
        daily = _daily()
        dates = daily.index
        candidates = pd.DataFrame([_candidate("A", dates[0]), _candidate("A", dates[1])])
        simulation = simulate_positions(candidates, {"A": daily}, 5)
        config = VwapBacktestConfig(
            "2026-06-01",
            "2026-06-12",
            -4.0,
            12.0,
            "prev_close",
            backtest_method=BACKTEST_METHOD_POSITION,
        )
        summary = build_position_summary(config, {5: simulation}, stock_count=3)

        markdown = _position_markdown(simulation.trades, summary)

        self.assertIn("シグナル発生件数: 2件", markdown)
        self.assertIn("独立エントリー件数: 1件", markdown)
        self.assertIn("重複除外: 1件", markdown)
        self.assertIn("対象銘柄数: 1銘柄", markdown)
        self.assertNotIn("独立上昇波動", markdown)


class PositionUseCaseTest(unittest.TestCase):
    def test_runs_all_eight_bands_and_three_holding_periods(self):
        daily = _daily(periods=30)
        candidate = pd.DataFrame([_candidate("1234", daily.index[0])])
        config = VwapBacktestConfig(
            daily.index[0].strftime("%Y-%m-%d"),
            daily.index[10].strftime("%Y-%m-%d"),
            -1.0,
            1.0,
            "prev_close",
            backtest_method=BACKTEST_METHOD_POSITION,
        )

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- テスト銘柄 (1234)\n", encoding="utf-8")
            with patch(
                "app.usecases.run_position_backtest.fetch_daily_prices",
                return_value={"1234": daily},
            ), patch(
                "app.usecases.run_position_backtest.run_vwap_backtest",
                return_value=(candidate, {}),
            ) as candidate_runner:
                trades, summary = run_position_backtest(watchlist, config)

        self.assertEqual(candidate_runner.call_count, 8)
        self.assertEqual(set(summary["periods"]), {5, 10, 15})
        self.assertEqual(set(trades["holding_period_days"]), {5, 10, 15})
        self.assertTrue(all(period["signal_count"] == 1 for period in summary["periods"].values()))


if __name__ == "__main__":
    unittest.main()
