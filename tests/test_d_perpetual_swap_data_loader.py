import unittest

import requests

from experiments.d_perpetual.swap_data_loader import (
    HOUR_MS,
    SwapHistoryLoadError,
    fetch_okx_swap_1h_history,
    validate_swap_hourly_candles,
)


def row(ts, confirm="1"):
    return [str(ts), "100", "102", "99", "101", "10", "1000", "1000", confirm]


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
        self.calls.append(dict(params))
        if not self.pages:
            return FakeResponse([])
        result = self.pages.pop(0)
        return result if isinstance(result, FakeResponse) else FakeResponse(result)


class SwapLoaderTests(unittest.TestCase):
    def test_fetches_pages_and_returns_ascending_closed_rows(self):
        session = FakeSession([
            [row(3 * HOUR_MS), row(2 * HOUR_MS)],
            [row(HOUR_MS), row(0)],
        ])
        candles, report = fetch_okx_swap_1h_history(
            "BTC-USDT-SWAP", 0, 4 * HOUR_MS, session=session, sleep_fn=lambda _: None
        )
        self.assertEqual([x["time"] for x in candles], [0, HOUR_MS, 2*HOUR_MS, 3*HOUR_MS])
        self.assertTrue(report["complete"])
        self.assertEqual(session.calls[0]["instId"], "BTC-USDT-SWAP")
        self.assertEqual(session.calls[1]["after"], str(2 * HOUR_MS))
        self.assertEqual(report["market_type"], "SWAP")

    def test_unclosed_row_is_excluded_and_creates_gap(self):
        session = FakeSession([[row(2*HOUR_MS), row(HOUR_MS, "0"), row(0)]])
        candles, report = fetch_okx_swap_1h_history(
            "ETH-USDT-SWAP", 0, 3*HOUR_MS, session=session, sleep_fn=lambda _: None
        )
        self.assertEqual([x["time"] for x in candles], [0, 2*HOUR_MS])
        self.assertFalse(report["complete"])
        self.assertEqual(report["missing_timestamps"], [HOUR_MS])

    def test_duplicate_page_overlap_is_not_silently_accepted(self):
        session = FakeSession([
            [row(3*HOUR_MS), row(2*HOUR_MS)],
            [row(2*HOUR_MS), row(HOUR_MS), row(0)],
        ])
        candles, report = fetch_okx_swap_1h_history(
            "BTC-USDT-SWAP", 0, 4*HOUR_MS, session=session, sleep_fn=lambda _: None
        )
        self.assertEqual(len(candles), 4)
        self.assertEqual(report["api_duplicate_count"], 1)
        self.assertFalse(report["complete"])

    def test_stalled_pagination_fails(self):
        session = FakeSession([
            [row(3*HOUR_MS), row(2*HOUR_MS)],
            [row(3*HOUR_MS), row(2*HOUR_MS)],
        ])
        with self.assertRaises(SwapHistoryLoadError):
            fetch_okx_swap_1h_history(
                "BTC-USDT-SWAP", 0, 4*HOUR_MS, session=session, sleep_fn=lambda _: None
            )

    def test_retries_transient_connection_error(self):
        class RetrySession:
            calls = 0
            def get(self, url, params, timeout):
                self.calls += 1
                if self.calls == 1:
                    raise requests.ConnectionError("temporary")
                return FakeResponse([row(0)])
        session = RetrySession()
        candles, report = fetch_okx_swap_1h_history(
            "BTC-USDT-SWAP", 0, HOUR_MS, session=session, sleep_fn=lambda _: None
        )
        self.assertEqual(session.calls, 2)
        self.assertTrue(report["complete"])

    def test_non_retryable_api_error_fails_immediately(self):
        session = FakeSession([FakeResponse([], code="51000", msg="bad instrument")])
        with self.assertRaises(SwapHistoryLoadError):
            fetch_okx_swap_1h_history(
                "BTC-USDT-SWAP", 0, HOUR_MS, session=session, sleep_fn=lambda _: None
            )
        self.assertEqual(len(session.calls), 1)

    def test_invalid_instrument_and_range_rejected(self):
        with self.assertRaises(ValueError):
            fetch_okx_swap_1h_history("BTC-USDT", 0, HOUR_MS)
        with self.assertRaises(ValueError):
            fetch_okx_swap_1h_history("BTC-USDT-SWAP", 10, 10)

    def test_validator_rejects_order_duplicates_and_gaps(self):
        result = validate_swap_hourly_candles(
            [{"time": HOUR_MS}, {"time": 0}, {"time": HOUR_MS}],
            0, 2*HOUR_MS
        )
        self.assertFalse(result["ordered"])
        self.assertFalse(result["unique"])
        self.assertEqual(result["duplicate_count"], 1)
        self.assertFalse(result["complete"])

    def test_bad_timestamp_and_bad_ohlc_fail_loudly(self):
        with self.assertRaises(SwapHistoryLoadError):
            fetch_okx_swap_1h_history(
                "BTC-USDT-SWAP", 0, HOUR_MS,
                session=FakeSession([[[ "not-a-time", "1", "1", "1", "1", "1", "1", "1", "1" ]]]),
                sleep_fn=lambda _: None
            )
        with self.assertRaises(SwapHistoryLoadError):
            fetch_okx_swap_1h_history(
                "BTC-USDT-SWAP", 0, HOUR_MS,
                session=FakeSession([[["0", "100", "90", "99", "101", "10", "10", "10", "1"]]]),
                sleep_fn=lambda _: None
            )


if __name__ == "__main__":
    unittest.main()
