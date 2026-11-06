import tempfile
import unittest
from pathlib import Path

from experiments.d_entry_quality.cache import load_candles, save_candles
from experiments.d_entry_quality.data_loader import HOUR_MS, HistoryLoadError


class CandleCacheTests(unittest.TestCase):
    def candles(self):
        return [{
            "time": i * HOUR_MS,
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 10.0,
        } for i in range(4)]

    def test_csv_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "BTCUSDT.csv"
            save_candles(path, self.candles())
            loaded = load_candles(path)
            self.assertEqual(loaded, self.candles())

    def test_cache_refuses_missing_hour(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.csv"
            with self.assertRaises(HistoryLoadError):
                save_candles(path, self.candles()[:2] + self.candles()[3:])

    def test_cache_refuses_wrong_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.csv"
            path.write_text("timestamp,close\n1,100\n", encoding="utf-8")
            with self.assertRaises(HistoryLoadError):
                load_candles(path)


if __name__ == "__main__":
    unittest.main()
