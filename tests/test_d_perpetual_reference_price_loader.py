import unittest

import requests

from experiments.d_perpetual.reference_price_loader import (
    HOUR_MS,
    ReferencePriceLoadError,
    fetch_okx_index_price_1h_history,
    fetch_okx_mark_price_1h_history,
    validate_reference_hourly_candles,
)


def row(ts, confirm="1"):
    return [str(ts), "100", "102", "99", "101", confirm]


class FakeResponse:
    def __init__(self, data, code="0", msg=""):
        self.payload = {"code": code, "msg": msg, "data": data}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, dict(params)))
        if not self.pages:
            return FakeResponse([])
        item = self.pages.pop(0)
        return item if isinstance(item, FakeResponse) else FakeResponse(item)


class ReferencePriceLoaderTests(unittest.TestCase):
    def test_mark_price_uses_mark_endpoint_and_pages(self):
        session = FakeSession([
            [row(2*HOUR_MS), row(HOUR_MS)],
            [row(0)],
        ])
        candles, report = fetch_okx_mark_price_1h_history(
            "BTC-USDT-SWAP", 0, 3*HOUR_MS,
            session=session, sleep_fn=lambda _: None
        )
        self.assertEqual(len(candles), 3)
        self.assertTrue(report["complete"])
        self.assertIn("history-mark-price-candles", session.calls[0][0])
        self.assertEqual(session.calls[1][1]["after"], str(HOUR_MS))

    def test_index_price_uses_index_endpoint_and_explicit_index_id(self):
        session = FakeSession([[row(HOUR_MS), row(0)]])
        candles, report = fetch_okx_index_price_1h_history(
            "BTC-USD", 0, 2*HOUR_MS,
            session=session, sleep_fn=lambda _: None
        )
        self.assertTrue(report["complete"])
        self.assertEqual(session.calls[0][1]["instId"], "BTC-USD")
        self.assertIn("history-index-candles", session.calls[0][0])

    def test_unclosed_reference_candle_is_excluded_and_gap_reported(self):
        session = FakeSession([[row(2*HOUR_MS), row(HOUR_MS, "0"), row(0)]])
        candles, report = fetch_okx_mark_price_1h_history(
            "ETH-USDT-SWAP", 0, 3*HOUR_MS,
            session=session, sleep_fn=lambda _: None
        )
        self.assertEqual(len(candles), 2)
        self.assertFalse(report["complete"])
        self.assertEqual(report["missing_timestamps"], [HOUR_MS])

    def test_duplicate_page_overlap_marks_series_incomplete(self):
        session = FakeSession([
            [row(2*HOUR_MS), row(HOUR_MS)],
            [row(HOUR_MS), row(0)],
        ])
        _, report = fetch_okx_index_price_1h_history(
            "BTC-USD", 0, 3*HOUR_MS,
            session=session, sleep_fn=lambda _: None
        )
        self.assertEqual(report["api_duplicate_count"], 1)
        self.assertFalse(report["complete"])

    def test_stalled_pagination_raises(self):
        session = FakeSession([
            [row(2*HOUR_MS), row(HOUR_MS)],
            [row(2*HOUR_MS), row(HOUR_MS)],
        ])
        with self.assertRaises(ReferencePriceLoadError):
            fetch_okx_mark_price_1h_history(
                "BTC-USDT-SWAP", 0, 3*HOUR_MS,
                session=session, sleep_fn=lambda _: None
            )

    def test_retries_network_error(self):
        class RetrySession:
            calls = 0
            def get(self, url, params, timeout):
                self.calls += 1
                if self.calls == 1:
                    raise requests.Timeout("temporary")
                return FakeResponse([row(0)])
        session = RetrySession()
        candles, report = fetch_okx_mark_price_1h_history(
            "BTC-USDT-SWAP", 0, HOUR_MS,
            session=session, sleep_fn=lambda _: None
        )
        self.assertEqual(session.calls, 2)
        self.assertTrue(report["complete"])

    def test_invalid_price_ohlc_fails(self):
        bad = [["0", "100", "90", "99", "101", "1"]]
        with self.assertRaises(ReferencePriceLoadError):
            fetch_okx_mark_price_1h_history(
                "BTC-USDT-SWAP", 0, HOUR_MS,
                session=FakeSession([bad]), sleep_fn=lambda _: None
            )

    def test_rejects_mark_non_swap_instrument(self):
        with self.assertRaises(ValueError):
            fetch_okx_mark_price_1h_history(
                "BTC-USDT", 0, HOUR_MS
            )

    def test_validator_detects_order_duplicate_gap(self):
        report = validate_reference_hourly_candles(
            [{"time": HOUR_MS}, {"time": 0}, {"time": HOUR_MS}],
            0, 2*HOUR_MS
        )
        self.assertFalse(report["ordered"])
        self.assertFalse(report["unique"])
        self.assertEqual(report["duplicate_count"], 1)
        self.assertFalse(report["complete"])


if __name__ == "__main__":
    unittest.main()
