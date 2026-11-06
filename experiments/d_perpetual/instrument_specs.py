"""Read-only OKX SWAP instrument metadata loader and strict parser.

All contract quantities remain Decimal strings/values. No account credentials,
position changes, order placement, or leverage configuration are involved.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import requests

OKX_PUBLIC_INSTRUMENTS_URL = "https://www.okx.com/api/v5/public/instruments"
REQUEST_TIMEOUT = 20

_REQUIRED_DECIMALS = ("ctVal", "ctMult", "lotSz", "minSz", "tickSz")
_OPTIONAL_TEXT = (
    "instFamily", "uly", "baseCcy", "quoteCcy", "settleCcy", "ctValCcy",
    "ctType", "state", "listTime", "expTime", "lever",
)


class InstrumentSpecError(RuntimeError):
    """Raised when OKX instrument metadata is absent or unsafe to use."""


def _positive_decimal(value, field: str, *, allow_zero: bool = False) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InstrumentSpecError(f"Invalid decimal for {field}: {value!r}") from exc
    if not parsed.is_finite() or (parsed < 0 if allow_zero else parsed <= 0):
        rule = "non-negative" if allow_zero else "positive"
        raise InstrumentSpecError(f"{field} must be finite and {rule}")
    return parsed


def parse_okx_swap_instrument(
    record: dict, expected_inst_id: str, *, require_usdt_linear: bool = True,
    require_live: bool = True,
) -> dict:
    """Validate and normalize one SWAP instrument record without float coercion."""
    if not isinstance(record, dict):
        raise InstrumentSpecError("Instrument record must be an object")
    if not isinstance(expected_inst_id, str) or not expected_inst_id.endswith("-SWAP"):
        raise ValueError("expected_inst_id must identify a SWAP instrument")
    if record.get("instId") != expected_inst_id:
        raise InstrumentSpecError("Returned instId does not match requested instrument")
    if record.get("instType") != "SWAP":
        raise InstrumentSpecError("Instrument type must be SWAP")
    if require_usdt_linear:
        if record.get("settleCcy") != "USDT":
            raise InstrumentSpecError("Instrument must settle in USDT")
        if record.get("ctType") != "linear":
            raise InstrumentSpecError("Instrument must be a linear contract")
    if require_live and record.get("state") != "live":
        raise InstrumentSpecError("Instrument is not live")

    result = {key: record.get(key, "") for key in _OPTIONAL_TEXT}
    result.update({
        "instId": expected_inst_id,
        "instType": "SWAP",
        "contract_value": _positive_decimal(record.get("ctVal"), "ctVal"),
        "contract_multiplier": _positive_decimal(record.get("ctMult"), "ctMult"),
        "lot_size": _positive_decimal(record.get("lotSz"), "lotSz"),
        "minimum_size": _positive_decimal(record.get("minSz"), "minSz"),
        "tick_size": _positive_decimal(record.get("tickSz"), "tickSz"),
    })
    if result["lot_size"] > result["minimum_size"]:
        # Valid exchange instruments can have minSz equal to or greater than lotSz;
        # no ordering assumption is made here.
        pass
    return result


def fetch_okx_swap_instrument(
    inst_id: str, *, session=None, require_usdt_linear: bool = True,
    require_live: bool = True,
) -> dict:
    """Fetch one instrument from the unauthenticated public instruments endpoint."""
    if not isinstance(inst_id, str) or not inst_id.endswith("-SWAP"):
        raise ValueError("inst_id must end with -SWAP")
    client = session or requests.Session()
    try:
        response = client.get(
            OKX_PUBLIC_INSTRUMENTS_URL,
            params={"instType": "SWAP", "instId": inst_id},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise InstrumentSpecError(f"Unable to fetch instrument metadata: {exc}") from exc
    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        raise InstrumentSpecError(
            f"OKX instrument API error: {payload.get('code') if isinstance(payload, dict) else 'invalid response'}"
        )
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise InstrumentSpecError("OKX instrument response data must be a list")
    matches = [row for row in rows if isinstance(row, dict) and row.get("instId") == inst_id]
    if len(matches) != 1:
        raise InstrumentSpecError(f"Expected exactly one metadata record for {inst_id}")
    return parse_okx_swap_instrument(
        matches[0], inst_id, require_usdt_linear=require_usdt_linear,
        require_live=require_live,
    )
