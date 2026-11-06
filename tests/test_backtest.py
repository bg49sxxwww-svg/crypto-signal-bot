import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main


class BacktestRegressionTests(unittest.TestCase):
    def test_ema_series_returns_aligned_values(self):
        values = [1, 2, 3, 4, 5]
        result = main.ema_series(values, 3)
        self.assertEqual(len(result), len(values))
        self.assertGreater(result[-1], result[0])

    def test_rsi_is_100_for_monotonic_rise(self):
        self.assertEqual(main.calculate_rsi(list(range(1, 16)), 14), 100.0)

    def test_four_hour_aggregation_drops_incomplete_bucket(self):
        hour = 60 * 60 * 1000
        candles = [
            {"time": i * hour, "open": 10 + i, "high": 12 + i,
             "low": 9 + i, "close": 11 + i, "volume": 1}
            for i in range(5)
        ]
        result = main.build_4h_candles(candles)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["time"], 0)
        self.assertEqual(result[0]["open"], 10)
        self.assertEqual(result[0]["close"], 14)
        self.assertEqual(result[0]["volume"], 4)

    def test_d_rsi_filter_boundaries_and_extremes(self):
        self.assertTrue(main.d_rsi_filter("LONG", 55))
        self.assertTrue(main.d_rsi_filter("LONG", 68))
        self.assertFalse(main.d_rsi_filter("LONG", 54.99))
        self.assertFalse(main.d_rsi_filter("LONG", 68.01))
        self.assertTrue(main.d_rsi_filter("SHORT", 32))
        self.assertTrue(main.d_rsi_filter("SHORT", 45))
        self.assertFalse(main.d_rsi_filter("SHORT", 31.99))
        self.assertFalse(main.d_rsi_filter("SHORT", 45.01))
        self.assertFalse(main.d_rsi_filter("LONG", None))
        self.assertFalse(main.d_rsi_filter("FLAT", 60))

    def test_backtests_fail_closed_on_short_history(self):
        candles = [
            {"time": i * 60 * 60 * 1000, "open": 100, "high": 101,
             "low": 99, "close": 100, "volume": 1}
            for i in range(100)
        ]
        for fn in (
            main.backtest_ema_cross,
            main.backtest_ema_triple,
            main.backtest_ema_filtered,
        ):
            result = fn("BTCUSDT", candles=candles)
            self.assertTrue(result["insufficient_data"])
            self.assertEqual(result["trades"], 0)

    def test_all_four_backtests_execute_on_synthetic_90_day_history(self):
        import math

        candles = []
        hour = 60 * 60 * 1000
        previous_close = 100.0
        for index in range(2160):
            close = 100 + 0.025 * index + 4 * math.sin(index / 18)
            open_price = previous_close
            candles.append({
                "time": index * hour,
                "open": open_price,
                "high": max(open_price, close) + 0.8,
                "low": min(open_price, close) - 0.8,
                "close": close,
                "volume": 1000 + index % 17,
            })
            previous_close = close

        strategies = (
            main.backtest_ema_cross_baseline,
            main.backtest_ema_cross,
            main.backtest_ema_triple,
            main.backtest_ema_filtered,
        )
        for strategy in strategies:
            result = strategy("BTCUSDT", candles=candles)
            self.assertFalse(result["insufficient_data"], strategy.__name__)
            self.assertEqual(result["bars"], 2160)
            self.assertGreaterEqual(result["trades"], 0)
            self.assertTrue(math.isfinite(result["total_return"]))
            self.assertTrue(math.isfinite(result["max_drawdown"]))
            self.assertFalse(result["open_position"])

    def test_report_describes_baseline_costs_and_all_four_groups(self):
        report = main.build_report([], [], {}, [], trade_log=[])
        self.assertIn("A 組基準", report)
        self.assertIn("D 組", report)
        self.assertIn("A 組僅以反向 EMA 交叉出場", report)
        self.assertIn("B／C／D 組使用 ATR(14)", report)


if __name__ == "__main__":
    unittest.main()
