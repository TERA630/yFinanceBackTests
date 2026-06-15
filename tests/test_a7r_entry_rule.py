import unittest

from app.domain.entry_rules.a7r2 import is_lower_low_excluded


class LowerLowExclusionTests(unittest.TestCase):
    def test_zero_disables_exclusion(self):
        self.assertFalse(is_lower_low_excluded(3, 0))

    def test_excludes_at_selected_count_or_more(self):
        self.assertFalse(is_lower_low_excluded(1, 2))
        self.assertTrue(is_lower_low_excluded(2, 2))
        self.assertTrue(is_lower_low_excluded(3, 2))

    def test_rejects_out_of_range_setting(self):
        with self.assertRaises(ValueError):
            is_lower_low_excluded(2, 4)


if __name__ == "__main__":
    unittest.main()
