import unittest

import pandas as pd

from app.presentation.a8_gui import default_date_range


class A8GuiDateDefaultsTests(unittest.TestCase):
    def test_weekday_uses_today_and_forty_business_days_before(self):
        start, end = default_date_range(pd.Timestamp("2026-06-15"))

        self.assertEqual(end, pd.Timestamp("2026-06-15"))
        self.assertEqual(len(pd.bdate_range(start, end)), 41)

    def test_weekend_uses_previous_friday(self):
        start, end = default_date_range(pd.Timestamp("2026-06-14"))

        self.assertEqual(end, pd.Timestamp("2026-06-12"))
        self.assertEqual(len(pd.bdate_range(start, end)), 41)


if __name__ == "__main__":
    unittest.main()
