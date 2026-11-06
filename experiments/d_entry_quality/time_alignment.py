"""Time alignment for isolated D entry experiments; UTC timestamps in ms."""

HOUR_MS = 60 * 60 * 1000
FOUR_HOURS_MS = 4 * HOUR_MS


def latest_completed_4h_bucket(signal_candle_open_ms: int) -> int:
    """Return latest fully closed 4H bucket at the 1H signal candle close."""
    close_time = int(signal_candle_open_ms) + HOUR_MS
    return ((close_time // FOUR_HOURS_MS) - 1) * FOUR_HOURS_MS
