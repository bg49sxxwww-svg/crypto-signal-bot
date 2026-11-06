import unittest

from experiments.tp4_engine import build_tp4_position, process_tp4_bar


class TP4EngineTests(unittest.TestCase):
    def test_long_position_has_four_ascending_targets(self):
        position = build_tp4_position("LONG", 100, 2)
        self.assertEqual(position["stop"], 97)
        self.assertEqual(position["targets"], [102, 104, 106, 108])
        self.assertEqual(position["allocations"], (0.4, 0.3, 0.2, 0.1))

    def test_short_position_has_four_descending_targets(self):
        position = build_tp4_position("SHORT", 100, 2)
        self.assertEqual(position["stop"], 103)
        self.assertEqual(position["targets"], [98, 96, 94, 92])

    def test_partial_targets_reduce_remaining_fraction(self):
        position = build_tp4_position("LONG", 100, 2)
        events = process_tp4_bar(
            position, {"open": 100, "high": 105, "low": 99, "close": 104}
        )
        self.assertEqual([event["reason"] for event in events], ["TP1", "TP2"])
        self.assertAlmostEqual(position["remaining_fraction"], 0.3)
        self.assertEqual(position["targets_hit"], [0, 1])

    def test_stop_has_priority_over_targets_on_same_bar(self):
        position = build_tp4_position("LONG", 100, 2)
        events = process_tp4_bar(
            position, {"open": 100, "high": 109, "low": 96, "close": 105}
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["reason"], "STOP_LOSS")
        self.assertAlmostEqual(events[0]["fraction"], 1.0)
        self.assertEqual(position["remaining_fraction"], 0.0)

    def test_short_partial_targets_and_stop(self):
        position = build_tp4_position("SHORT", 100, 2)
        events = process_tp4_bar(
            position, {"open": 100, "high": 101, "low": 95, "close": 96}
        )
        self.assertEqual([event["reason"] for event in events], ["TP1", "TP2"])
        self.assertAlmostEqual(position["remaining_fraction"], 0.3)

    def test_all_targets_close_exactly_full_position(self):
        position = build_tp4_position("LONG", 100, 2)
        events = process_tp4_bar(
            position, {"open": 100, "high": 109, "low": 99, "close": 108}
        )
        self.assertEqual(len(events), 4)
        self.assertEqual(position["remaining_fraction"], 0.0)
        self.assertAlmostEqual(sum(e["fraction"] for e in events), 1.0)

    def test_validation_rejects_invalid_allocations(self):
        with self.assertRaises(ValueError):
            build_tp4_position("LONG", 100, 2, allocations=(0.4, 0.3, 0.2, 0.2))


if __name__ == "__main__":
    unittest.main()
