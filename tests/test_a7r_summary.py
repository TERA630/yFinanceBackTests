import math
import unittest

import pandas as pd

from app.domain.summary import summarize_signals


class A7RSummaryTests(unittest.TestCase):
    def test_adds_mfe_mae_and_threshold_rates_for_each_window(self):
        rows = []
        for max_up, max_dd in ((6.0, -4.0), (4.0, -2.0), (None, None)):
            row = {"category": "本命候補"}
            for horizon in (1, 3, 5, 10, 20):
                row[f"ret_{horizon}d_pct"] = 1.0
            for window in (5, 10, 20):
                row[f"max_up_{window}d_pct"] = max_up
                row[f"max_dd_{window}d_pct"] = max_dd
            rows.append(row)

        summary = summarize_signals(pd.DataFrame(rows)).iloc[0]

        for window in (5, 10, 20):
            self.assertEqual(summary[f"median_mfe_{window}d_pct"], 5.0)
            self.assertEqual(summary[f"median_mae_{window}d_pct"], -3.0)
            self.assertEqual(summary[f"adverse_3pct_rate_{window}d_pct"], 50.0)
            self.assertEqual(summary[f"reach_5pct_rate_{window}d_pct"], 50.0)

    def test_new_metrics_are_nan_without_future_data(self):
        row = {"category": "本命候補"}
        for horizon in (1, 3, 5, 10, 20):
            row[f"ret_{horizon}d_pct"] = None
        for window in (5, 10, 20):
            row[f"max_up_{window}d_pct"] = None
            row[f"max_dd_{window}d_pct"] = None

        summary = summarize_signals(pd.DataFrame([row])).iloc[0]

        self.assertTrue(math.isnan(summary["median_mfe_5d_pct"]))
        self.assertTrue(math.isnan(summary["median_mae_5d_pct"]))
        self.assertTrue(math.isnan(summary["adverse_3pct_rate_5d_pct"]))
        self.assertTrue(math.isnan(summary["reach_5pct_rate_5d_pct"]))


if __name__ == "__main__":
    unittest.main()
