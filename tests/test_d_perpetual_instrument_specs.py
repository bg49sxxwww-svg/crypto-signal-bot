import unittest
from decimal import Decimal

from experiments.d_perpetual.instrument_specs import (
    InstrumentSpecError,
    fetch_okx_swap_instrument,
    parse_okx_swap_instrument,
)


def instrument(**overrides):
    row = {
        "instId": "BTC-USDT-SWAP",
        "instType": "SWAP",
        "settleCcy": "USDT",
        "ctType": "linear",
        "state": "live",
        "instFamily": "BTC-USDT",
        "uly": "BTC-USDT",
        "ctVal": "0.01",
        "ctMult": "1",
        "ctValCcy": "BTC",
        "lotSz": "1",
        "minSz": "1",
        "tickSz": "0.1",
        "lever": "125",
        "listTime": "1600000000000",
        "expTime": "",
    }
    row.update(overrides)
    return row


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, dict(params), timeout))
        return FakeResponse(self.payload)


class InstrumentSpecTests(unittest.TestCase):
    def test_parses_linear_usdt_swap_with_decimal_precision(self):
        result = parse_okx_swap_instrument(instrument(), "BTC-USDT-SWAP")
        self.assertEqual(result["contract_value"], Decimal("0.01"))
        self.assertEqual(result["contract_multiplier"], Decimal("1"))
        self.assertEqual(result["tick_size"], Decimal("0.1"))
        self.assertEqual(result["settleCcy"], "USDT")
        self.assertEqual(result["state"], "live")

    def test_rejects_wrong_instrument_id(self):
        with self.assertRaises(InstrumentSpecError):
            parse_okx_swap_instrument(instrument(), "ETH-USDT-SWAP")

    def test_rejects_non_swap(self):
        with self.assertRaises(InstrumentSpecError):
            parse_okx_swap_instrument(
                instrument(instType="SPOT"), "BTC-USDT-SWAP"
            )

    def test_rejects_non_usdt_settlement(self):
        with self.assertRaises(InstrumentSpecError):
            parse_okx_swap_instrument(
                instrument(settleCcy="BTC"), "BTC-USDT-SWAP"
            )

    def test_rejects_inverse_contract(self):
        with self.assertRaises(InstrumentSpecError):
            parse_okx_swap_instrument(
                instrument(ctType="inverse"), "BTC-USDT-SWAP"
            )

    def test_rejects_inactive_contract_by_default(self):
        with self.assertRaises(InstrumentSpecError):
            parse_okx_swap_instrument(
                instrument(state="suspend"), "BTC-USDT-SWAP"
            )

    def test_rejects_missing_required_decimal(self):
        row = instrument()
        del row["ctVal"]
        with self.assertRaises(InstrumentSpecError):
            parse_okx_swap_instrument(row, "BTC-USDT-SWAP")

    def test_rejects_zero_or_nonfinite_decimal(self):
        for value in ("0", "-1", "NaN", "Infinity", "not-a-number"):
            with self.subTest(value=value):
                with self.assertRaises(InstrumentSpecError):
                    parse_okx_swap_instrument(
                        instrument(tickSz=value), "BTC-USDT-SWAP"
                    )

    def test_public_fetch_routes_inst_type_and_exact_inst_id(self):
        session = FakeSession({"code": "0", "data": [instrument()], "msg": ""})
        result = fetch_okx_swap_instrument(
            "BTC-USDT-SWAP", session=session
        )
        self.assertEqual(result["instId"], "BTC-USDT-SWAP")
        self.assertEqual(session.calls[0][1], {
            "instType": "SWAP", "instId": "BTC-USDT-SWAP"
        })

    def test_public_fetch_rejects_missing_or_duplicate_match(self):
        for rows in ([], [instrument(), instrument()]):
            with self.subTest(rows=len(rows)):
                session = FakeSession({"code": "0", "data": rows, "msg": ""})
                with self.assertRaises(InstrumentSpecError):
                    fetch_okx_swap_instrument(
                        "BTC-USDT-SWAP", session=session
                    )

    def test_rejects_api_error(self):
        session = FakeSession({"code": "50000", "data": [], "msg": "error"})
        with self.assertRaises(InstrumentSpecError):
            fetch_okx_swap_instrument("BTC-USDT-SWAP", session=session)

    def test_rejects_non_swap_id_before_request(self):
        with self.assertRaises(ValueError):
            fetch_okx_swap_instrument("BTC-USDT")


if __name__ == "__main__":
    unittest.main()
