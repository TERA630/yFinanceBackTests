import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.data.settings_store import load_watchlist_path, save_watchlist_path


class SettingsStoreTests(unittest.TestCase):
    def test_round_trips_existing_watchlist_path(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            watchlist = root / "watchlist.md"
            settings = root / "settings.json"
            watchlist.write_text("- test (1234)\n", encoding="utf-8")

            save_watchlist_path(watchlist, settings)

            self.assertEqual(load_watchlist_path(settings), watchlist.resolve())

    def test_returns_none_for_missing_or_invalid_saved_path(self):
        with TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text(json.dumps({"watchlist_path": "missing.md"}), encoding="utf-8")
            self.assertIsNone(load_watchlist_path(settings))

            settings.write_text("not json", encoding="utf-8")
            self.assertIsNone(load_watchlist_path(settings))


if __name__ == "__main__":
    unittest.main()
