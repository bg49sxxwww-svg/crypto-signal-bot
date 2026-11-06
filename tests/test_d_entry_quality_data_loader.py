import unittest

import requests

from experiments.d_entry_quality.data_loader import (
    HOUR_MS,
    HistoryLoadError,
    fetch_okx_1h_history,
    validate_hourly_candles,
)


def okx_row(ts, confirm="1"):
    return [str(ts), "100", "102", "99", "101", "10", "10", "10", confirm]


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return {"code": "0", "msg": "", "data": self.data}


class FakeSession:
    def __init__(self, pages):
        self.pages = list(pages)
        self.params = []

    def get(self, url, params, timeout):
        self.params.append(dict(params))
        if not self.pages:
            return FakeResponse([])
        return FakeResponse(self.pages.pop(0))


class HistoryLoaderTests(unittest.TestCase):
    def test_fetches_multiple_pages_and_sorts_oldest_first(self):
        session = FakeSession([
            [okx_row(3 * HOUR_MS), okx_row(2 * HOUR_MS)],
            [okx_row(HOUR_MS), okx_row(0)],
        ])
        rows, report = fetch_okx_1h_history(
            "BTCUSDT", 0, 4 * HOUR_MS, session=session, sleep_fn=lambda _: None
        )
        self.assertEqual([r["time"] for r in rows], [0, HOUR_MS, 2 * HOUR_MS, 3 * HOUR_MS])
        self.assertTrue(report["complete"])
        self.assertEqual(report["pages_fetched"], 2)
        self.assertEqual(session.params[0]["instId"], "BTC-USDT")
        self.assertEqual(session.params[1]["after"], str(2 * HOUR_MS))

    def test_unclosed_candles_are_excluded_and_reported_as_missing(self):
        session = FakeSession([[
            okx_row(2 * HOUR_MS),
            okx_row(HOUR_MS, confirm="0"),
            okx_row(0),
        ]])
        rows, report = fetch_okx_1h_history(
            "ETHUSDT", 0, 3 * HOUR_MS, session=session, sleep_fn=lambda _: None
        )
        self.assertEqual([r["time"] for r in rows], [0, 2 * HOUR_MS])
        self.assertFalse(report["complete"])
        self.assertEqual(report["missing_timestamps"], [HOUR_MS])

    def test_validator_detects_duplicate_and_out_of_order_rows(self):
        rows = [
            {"time": HOUR_MS},
            {"time": 0},
            {"time": HOUR_MS},
        ]
        report = validate_hourly_candles(rows, 0, 2 * HOUR_MS)
        self.assertEqual(report["duplicate_count"], 1)
        self.assertFalse(report["ordered"])
        self.assertFalse(report["unique"])
        self.assertFalse(report["complete"])

    def test_pagination_stall_fails_loudly(self):
        session = FakeSession([
            [okx_row(2 * HOUR_MS), okx_row(HOUR_MS)],
            [okx_row(2 * HOUR_MS), okx_row(HOUR_MS)],
        ])
        with self.assertRaises(HistoryLoadError):
            fetch_okx_1h_history(
                "BTCUSDT", 0, 4 * HOUR_MS, session=session, sleep_fn=lambda _: None
            )

    def test_rejects_unaligned_timestamps(self):
        session = FakeSession([[okx_row(1)]])
        with self.assertRaises(HistoryLoadError):
            fetch_okx_1h_history(
                "BTCUSDT", 0, 2 * HOUR_MS, session=session, sleep_fn=lambda _: None
            )

    def test_rejects_invalid_range_and_symbol(self):
        with self.assertRaises(ValueError):
            fetch_okx_1h_history("BTCUSDT", 100, 100, session=FakeSession([]))
        with self.assertRaises(ValueError):
            fetch_okx_1h_history("BTC-USD", 0, HOUR_MS, session=FakeSession([]))


    def test_retries_transient_connection_error_then_succeeds(self):
        class RetrySession:
            def __init__(self):
                self.calls = 0

            def get(self, url, params, timeout):
                self.calls += 1
                if self.calls == 1:
                    raise requests.ConnectionError("temporary network failure")
                return FakeResponse([okx_row(0)])

        session = RetrySession()
        rows, report = fetch_okx_1h_history(
            "BTCUSDT", 0, HOUR_MS, session=session, sleep_fn=lambda _: None
        )
        self.assertEqual(session.calls, 2)
        self.assertEqual(len(rows), 1)
        self.assertTrue(report["complete"])

    def test_nonretryable_api_error_fails_immediately(self):
        class ErrorResponse(FakeResponse):
            def json(self):
                return {"code": "51000", "msg": "Invalid parameter", "data": []}

        class ErrorSession:
            def __init__(self):
                self.calls = 0

            def get(self, url, params, timeout):
                self.calls += 1
                return ErrorResponse([])

        session = ErrorSession()
        with self.assertRaises(HistoryLoadError):
            fetch_okx_1h_history(
                "BTCUSDT", 0, HOUR_MS, session=session, sleep_fn=lambda _: None
            )
        self.assertEqual(session.calls, 1)


if __name__ == "__main__":
    unittest.main()
