import unittest

from experiments.d_tp4_backtest import (
    DEFAULT_TARGET_ATRS, build_tp4_position, process_tp4_bar,
    close_tp4_position,
)


class TP4ExecutionTests(unittest.TestCase):
    def candle(self, open_price=100, high=100, low=100, close=100):
        return {"open": open_price, "high": high, "low": low, "close": close}

    def test_defaults_keep_original_d_target_as_tp1(self):
        self.assertEqual(DEFAULT_TARGET_ATRS, (2.5, 3.5, 4.5, 5.5))
        position = build_tp4_position("LONG", 100, 2, entry_cost_rate=0)
        self.assertEqual(position["stop"], 97)
        self.assertEqual(position["targets"], [105, 107, 109, 111])

    def test_short_geometry(self):
        position = build_tp4_position("SHORT", 100, 2, entry_cost_rate=0)
        self.assertEqual(position["stop"], 103)
        self.assertEqual(position["targets"], [95, 93, 91, 89])

    def test_entry_cost_is_included(self):
        long = build_tp4_position("LONG", 100, 2, entry_cost_rate=0.0015)
        short = build_tp4_position("SHORT", 100, 2, entry_cost_rate=0.0015)
        self.assertAlmostEqual(long["entry_fill"], 100.15)
        self.assertAlmostEqual(short["entry_fill"], 99.85)

    def test_only_nearest_target_fills_per_ohlc_bar(self):
        position = build_tp4_position("LONG", 100, 2, entry_cost_rate=0)
        events = process_tp4_bar(position, self.candle(high=112, low=99), 0)
        self.assertEqual([e["reason"] for e in events], ["TP1"])
        self.assertAlmostEqual(position["remaining_fraction"], 0.6)

    def test_stop_wins_when_stop_and_target_both_touched(self):
        position = build_tp4_position("LONG", 100, 2, entry_cost_rate=0)
        events = process_tp4_bar(position, self.candle(high=112, low=96), 0)
        self.assertEqual(events[0]["reason"], "STOP_LOSS")
        self.assertAlmostEqual(events[0]["fraction"], 1.0)
        self.assertTrue(position["closed"])

    def test_long_stop_gap_fills_at_open_or_worse(self):
        position = build_tp4_position("LONG", 100, 2, entry_cost_rate=0)
        events = process_tp4_bar(position, self.candle(open_price=94, high=96, low=93), 0)
        self.assertEqual(events[0]["fill"], 94)

    def test_short_stop_gap_fills_at_open_or_worse(self):
        position = build_tp4_position("SHORT", 100, 2, entry_cost_rate=0)
        events = process_tp4_bar(position, self.candle(open_price=106, high=107, low=104), 0)
        self.assertEqual(events[0]["fill"], 106)

    def test_partial_then_stop_closes_remaining_only(self):
        position = build_tp4_position("LONG", 100, 2, entry_cost_rate=0)
        first = process_tp4_bar(position, self.candle(high=106, low=99), 0)
        self.assertEqual(first[0]["reason"], "TP1")
        self.assertAlmostEqual(position["remaining_fraction"], 0.6)
        stop = process_tp4_bar(position, self.candle(high=101, low=96), 0)
        self.assertEqual(stop[0]["reason"], "STOP_LOSS")
        self.assertAlmostEqual(stop[0]["fraction"], 0.6)
        self.assertEqual(position["remaining_fraction"], 0)

    def test_exit_cost_is_applied(self):
        position = build_tp4_position("LONG", 100, 2, entry_cost_rate=0)
        event = process_tp4_bar(position, self.candle(high=106, low=99), 0.001)
        self.assertLess(event[0]["fill"], 105)

    def test_reverse_cross_closes_remaining_fraction(self):
        position = build_tp4_position("SHORT", 100, 2, entry_cost_rate=0)
        process_tp4_bar(position, self.candle(high=100, low=94), 0)
        event = close_tp4_position(position, 97, "REVERSE_CROSS", 0)
        self.assertAlmostEqual(event[0]["fraction"], 0.6)
        self.assertTrue(position["closed"])

    def test_forced_end_closes_remaining_fraction(self):
        position = build_tp4_position("LONG", 100, 2, entry_cost_rate=0)
        event = close_tp4_position(position, 101, "FORCED_END", 0)
        self.assertEqual(event[0]["reason"], "FORCED_END")
        self.assertEqual(event[0]["fraction"], 1.0)

    def test_closed_position_cannot_exit_twice(self):
        position = build_tp4_position("LONG", 100, 2, entry_cost_rate=0)
        close_tp4_position(position, 96, "FORCED_END", 0)
        self.assertEqual(process_tp4_bar(position, self.candle(high=120, low=80), 0), [])
        self.assertEqual(close_tp4_position(position, 110, "REVERSE_CROSS", 0), [])

    def test_four_targets_close_exactly_full_position(self):
        position = build_tp4_position("LONG", 100, 2, entry_cost_rate=0)
        events = []
        for target in (105, 107, 109, 111):
            events.extend(process_tp4_bar(position, self.candle(high=target, low=100), 0))
        self.assertEqual([e["reason"] for e in events], ["TP1", "TP2", "TP3", "TP4"])
        self.assertEqual(position["remaining_fraction"], 0)
        self.assertAlmostEqual(sum(e["fraction"] for e in events), 1)

    def test_invalid_allocations_and_targets_rejected(self):
        with self.assertRaises(ValueError):
            build_tp4_position("LONG", 100, 2, allocations=(.4, .3, .2, .2))
        with self.assertRaises(ValueError):
            build_tp4_position("LONG", 100, 2, target_atrs=(2.5, 2, 4, 5))

    def test_invalid_ohlc_rejected(self):
        position = build_tp4_position("LONG", 100, 2)
        with self.assertRaises(ValueError):
            process_tp4_bar(position, self.candle(high=90, low=95))


if __name__ == "__main__":
    unittest.main()
