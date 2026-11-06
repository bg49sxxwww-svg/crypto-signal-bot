import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


class EntryQualityBaselineTests(unittest.TestCase):
    @staticmethod
    def synthetic_candles(count=900):
        hour = 60 * 60 * 1000
        rows = []
        previous = 100.0
        for i in range(count):
            close = 100 + 0.018 * i + 3.0 * math.sin(i / 19.0)
            open_price = previous
            rows.append({
                "time": i * hour,
                "open": open_price,
                "high": max(open_price, close) + 0.7,
                "low": min(open_price, close) - 0.7,
                "close": close,
                "volume": 1000 + (i % 23) * 10,
            })
            previous = close
        return rows

    def test_four_hour_aggregation_rejects_missing_and_duplicate_rows(self):
        hour = 60 * 60 * 1000
        base = self.synthetic_candles(8)
        valid = main.build_4h_candles(base)
        self.assertEqual(len(valid), 2)
        missing = [row for row in base if row["time"] != 2 * hour]
        self.assertEqual(main.build_4h_candles(missing), [])
        duplicate = base[:4] + [dict(base[2])] + base[4:]
        self.assertEqual(main.build_4h_candles(duplicate), [valid[1]])

    def test_four_hour_aggregation_sorts_out_of_order_input(self):
        rows = self.synthetic_candles(8)
        expected = main.build_4h_candles(rows)
        actual = main.build_4h_candles(list(reversed(rows)))
        self.assertEqual(actual, expected)

    def test_d_baseline_is_deterministic_on_identical_candles(self):
        candles = self.synthetic_candles()
        first_log, second_log = [], []
        first = main.backtest_ema_filtered("BTCUSDT", candles=candles, trade_log=first_log)
        second = main.backtest_ema_filtered("BTCUSDT", candles=candles, trade_log=second_log)
        self.assertEqual(first, second)
        self.assertEqual(first_log, second_log)
        self.assertFalse(first["insufficient_data"])
        self.assertEqual(first["bars"], len(candles))


if __name__ == "__main__":
    unittest.main()
