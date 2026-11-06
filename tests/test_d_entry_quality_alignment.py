import unittest

from experiments.d_entry_quality.time_alignment import (
    FOUR_HOURS_MS,
    HOUR_MS,
    latest_completed_4h_bucket,
)


class TimeAlignmentTests(unittest.TestCase):
    def test_before_first_four_hour_boundary_uses_previous_bucket(self):
        self.assertEqual(latest_completed_4h_bucket(0), -FOUR_HOURS_MS)
        self.assertEqual(latest_completed_4h_bucket(HOUR_MS), -FOUR_HOURS_MS)
        self.assertEqual(latest_completed_4h_bucket(2 * HOUR_MS), -FOUR_HOURS_MS)

    def test_exact_four_hour_close_can_use_just_completed_bucket(self):
        self.assertEqual(latest_completed_4h_bucket(3 * HOUR_MS), 0)

    def test_after_boundary_keeps_latest_completed_bucket(self):
        self.assertEqual(latest_completed_4h_bucket(4 * HOUR_MS), 0)
        self.assertEqual(latest_completed_4h_bucket(7 * HOUR_MS), FOUR_HOURS_MS)

    def test_result_is_utc_bucket_aligned(self):
        for index in range(100):
            bucket = latest_completed_4h_bucket(index * HOUR_MS)
            self.assertEqual(bucket % FOUR_HOURS_MS, 0)


if __name__ == "__main__":
    unittest.main()
