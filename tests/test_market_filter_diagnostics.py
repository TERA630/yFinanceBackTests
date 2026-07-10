from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from app.data.vwap_price_repository import SymbolDownloadDiagnostics
from app.domain.vwap_backtest import VwapBacktestConfig
from app.output.markdown_writer import save_market_filter_diagnostics
from app.usecases.diagnose_market_filters import diagnose_market_filters


class MarketFilterDiagnosticsTest(unittest.TestCase):
    def _metadata(self, symbol: str, interval: str, rows: int) -> SymbolDownloadDiagnostics:
        return SymbolDownloadDiagnostics(
            symbol=symbol,
            interval=interval,
            start="2026-05-18",
            end="2026-06-05",
            cache_path=Path(".yfcache") / f"{symbol}_{interval}.pkl",
            cache_exists=True,
            cache_hit=False,
            error=None,
            row_count=rows,
            first_timestamp="2026-05-29 00:00:00",
            last_timestamp="2026-06-02 08:00:00",
            columns=("Close",),
        )

    def test_diagnoses_nikkei_0800_and_sox_daily_inputs(self):
        config = VwapBacktestConfig(
            "2026-06-01",
            "2026-06-01",
            -5.0,
            5.0,
            "11:00",
            use_nikkei_futures_filter=True,
            use_sox_semiconductor_filter=True,
        )
        nikkei_intraday = pd.DataFrame(
            {"Close": [100.0, 99.0, 101.0]},
            index=pd.to_datetime(["2026-06-01 15:25", "2026-06-02 07:55", "2026-06-02 08:00"]),
        )
        sox_daily = pd.DataFrame(
            {"Close": [100.0, 99.0]},
            index=pd.to_datetime(["2026-05-29", "2026-06-01"]),
        )

        def fake_fetch(symbol: str, start: str, end: str, interval: str, *, use_cache: bool):
            self.assertFalse(use_cache)
            if symbol == "NIY=F" and interval == "5m":
                return nikkei_intraday, self._metadata(symbol, interval, len(nikkei_intraday))
            if symbol == "^SOX" and interval == "1d":
                return sox_daily, self._metadata(symbol, interval, len(sox_daily))
            raise AssertionError(f"unexpected fetch: {symbol} {interval}")

        with TemporaryDirectory() as tmp:
            watchlist = Path(tmp) / "stocks.md"
            watchlist.write_text("- 半導体銘柄 (1234) 半導体\n- 通常銘柄 (5678)\n", encoding="utf-8")
            with patch("app.usecases.diagnose_market_filters.fetch_symbol_price_diagnostics", side_effect=fake_fetch):
                diagnostics = diagnose_market_filters(watchlist, config, ignore_cache=True)

        self.assertTrue(diagnostics["nikkei"]["enabled"])
        self.assertEqual(diagnostics["nikkei"]["dates"][0]["status"], "OK: 下落")
        self.assertEqual(diagnostics["nikkei"]["dates"][0]["close_before_1530"], 100.0)
        self.assertEqual(diagnostics["nikkei"]["dates"][0]["timestamp_before_0800"], "2026-06-02 07:55:00")
        self.assertTrue(diagnostics["sox"]["enabled"])
        self.assertEqual(diagnostics["sox"]["dates"][0]["status"], "OK: 下落")
        self.assertEqual(diagnostics["sox"]["dates"][0]["comparison_date"], "2026-05-29")
        self.assertEqual(diagnostics["sox"]["dates"][0]["latest_date"], "2026-06-01")
        self.assertEqual(diagnostics["semiconductor_related_count"], 1)
        self.assertEqual(diagnostics["nikkei"]["intraday"]["row_count"], 3)

    def test_saves_market_filter_diagnostics_markdown(self):
        diagnostics = {
            "generated_at": "2026-06-01 12:00:00",
            "start_date": "2026-06-01",
            "end_date": "2026-06-01",
            "entry_time": "11:00",
            "ignore_cache": True,
            "watchlist_count": 1,
            "semiconductor_related_count": 1,
            "signal_date_count": 1,
            "nikkei": {
                "enabled": True,
                "symbol": "NIY=F",
                "intraday": self._metadata("NIY=F", "5m", 2).__dict__,
                "dates": [
                    {
                        "date": "2026-06-02",
                        "reference_date": "2026-06-01",
                        "close_before_1530": 100.0,
                        "timestamp_before_1530": "2026-06-01 15:25:00",
                        "close_before_0800": 99.0,
                        "timestamp_before_0800": "2026-06-02 07:55:00",
                        "status": "OK: 下落",
                    }
                ],
            },
            "sox": {
                "enabled": True,
                "symbol": "^SOX",
                "daily": self._metadata("^SOX", "1d", 2).__dict__,
                "dates": [
                    {
                        "date": "2026-06-02",
                        "comparison_date": "2026-05-29",
                        "previous_close": 100.0,
                        "latest_date": "2026-06-01",
                        "latest_close": 99.0,
                        "status": "OK: 下落",
                    }
                ],
            },
        }

        with TemporaryDirectory() as tmp:
            path = save_market_filter_diagnostics(Path(tmp), diagnostics)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("# 市場フィルタ データ検証", markdown)
        self.assertIn("- キャッシュ: 無視して再取得", markdown)
        self.assertIn(
            "| 2026-06-02 | 2026-06-01 | 100.00 (2026-06-01 15:25:00) | "
            "99.00 (2026-06-02 07:55:00) | OK: 下落 |",
            markdown,
        )
        self.assertIn("| 2026-06-02 | 2026-05-29 | 100.00 | 2026-06-01 | 99.00 | OK: 下落 |", markdown)


if __name__ == "__main__":
    unittest.main()
