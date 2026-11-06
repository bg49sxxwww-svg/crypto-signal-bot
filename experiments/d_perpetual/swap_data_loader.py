"""Independent OKX USDT-margined SWAP 1H history loader.

This module is intentionally separate from the spot research loader.
Timestamps are UTC Unix milliseconds; candle timestamps are candle-open times.
"""
from __future__ import annotations

import time
from typing import Callable

import requests

OKX_SWAP_HISTORY_URL = "https://www.okx.com/api/v5/market/history-candles"
HOUR_MS = 3_600_000
PAGE_LIMIT = 100
REQUEST_TIMEOUT = 20
MIN_PAGE_INTERVAL_SECONDS = 0.12
RETRYABLE_HTTP_STATUS = (429, 500, 502, 503, 504)


class SwapHistoryLoadError(RuntimeError):
    """Raised when SWAP history cannot be fetched and validated safely."""


def _parse_swap_row(row: list) -> dict | None:
    if not isinstance(row, (list, tuple)) or len(row) < 9:
        raise SwapHistoryLoadError("Malformed SWAP candle row")
    try:
        timestamp = int(row[0])
    except (TypeError, ValueError) as exc:
        raise SwapHistoryLoadError(f"Invalid SWAP candle timestamp: {row[0]!r}") from exc
    if timestamp % HOUR_MS:
        raise SwapHistoryLoadError(f"Unaligned 1H SWAP candle timestamp: {timestamp}")
    if str(row[8]) != "1":
        return None
    try:
        candle = {
            "time": timestamp,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
    except (TypeError, ValueError) as exc:
        raise SwapHistoryLoadError(f"Invalid SWAP OHLCV values at {timestamp}") from exc

    values = [candle[k] for k in ("open", "high", "low", "close", "volume")]
    if any(v < 0 for v in values):
        raise SwapHistoryLoadError(f"Negative SWAP OHLCV value at {timestamp}")
    if candle["high"] < max(candle["open"], candle["close"], candle["low"]):
        raise SwapHistoryLoadError(f"Invalid SWAP high at {timestamp}")
    if candle["low"] > min(candle["open"], candle["close"], candle["high"]):
        raise SwapHistoryLoadError(f"Invalid SWAP low at {timestamp}")
    return candle


def validate_swap_hourly_candles(candles: list[dict], start_ms: int, end_ms: int) -> dict:
    """Validate ordered, unique, aligned candles in the half-open interval."""
    timestamps = []
    try:
        timestamps = [int(row["time"]) for row in candles]
    except (KeyError, TypeError, ValueError) as exc:
        raise SwapHistoryLoadError("Malformed normalized SWAP candle") from exc

    expected_start = ((start_ms + HOUR_MS - 1) // HOUR_MS) * HOUR_MS
    expected_end = (end_ms // HOUR_MS) * HOUR_MS
    ordered = timestamps == sorted(timestamps)
    unique = len(timestamps) == len(set(timestamps))
    aligned = all(ts % HOUR_MS == 0 for ts in timestamps)
    in_range = all(expected_start <= ts < expected_end for ts in timestamps)
    present = set(timestamps)
    missing = [ts for ts in range(expected_start, expected_end, HOUR_MS) if ts not in present]
    duplicate_count = len(timestamps) - len(present)
    return {
        "row_count": len(candles),
        "duplicate_count": duplicate_count,
        "ordered": ordered,
        "unique": unique,
        "aligned": aligned,
        "in_range": in_range,
        "missing_count": len(missing),
        "missing_timestamps": missing,
        "first_timestamp": timestamps[0] if timestamps else None,
        "last_timestamp": timestamps[-1] if timestamps else None,
        "complete": bool(candles) and ordered and unique and aligned and in_range and not missing,
    }


def fetch_okx_swap_1h_history(
    inst_id: str,
    start_ms: int,
    end_ms: int,
    *,
    session=None,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_pages: int = 20_000,
    max_retries: int = 4,
) -> tuple[list[dict], dict]:
    """Fetch closed USDT-SWAP 1H candles in [start_ms, end_ms), paging backward.

    Example instrument IDs: BTC-USDT-SWAP and ETH-USDT-SWAP.
    Raises on stalled pagination and reports incomplete coverage instead of
    silently filling missing timestamps.
    """
    if not isinstance(inst_id, str) or not inst_id.endswith("-USDT-SWAP"):
        raise ValueError("inst_id must be a USDT-margined SWAP, e.g. BTC-USDT-SWAP")
    if end_ms <= start_ms:
        raise ValueError("end_ms must be greater than start_ms")
    if start_ms < 0 or end_ms < 0:
        raise ValueError("timestamps must be non-negative")
    if max_pages < 1 or max_retries < 0:
        raise ValueError("max_pages must be >= 1 and max_retries must be >= 0")

    client = session or requests.Session()
    by_timestamp: dict[int, dict] = {}
    api_duplicate_count = 0
    cursor = None
    pages = 0

    while pages < max_pages:
        params = {"instId": inst_id, "bar": "1H", "limit": str(PAGE_LIMIT)}
        if cursor is not None:
            params["after"] = str(cursor)

        payload = None
        for attempt in range(max_retries + 1):
            try:
                response = client.get(
                    OKX_SWAP_HISTORY_URL, params=params, timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise SwapHistoryLoadError("OKX SWAP response must be a JSON object")
                code = str(payload.get("code"))
                if code == "0":
                    break
                if code != "50011":
                    raise SwapHistoryLoadError(
                        f"{inst_id} OKX error {code}: {payload.get('msg')}"
                    )
                retry_error = f"OKX rate limit: {payload.get('msg')}"
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status not in RETRYABLE_HTTP_STATUS:
                    raise SwapHistoryLoadError(f"{inst_id} HTTP error: {exc}") from exc
                retry_error = str(exc)
            except (requests.ConnectionError, requests.Timeout) as exc:
                retry_error = str(exc)
            except ValueError as exc:
                retry_error = f"invalid JSON response: {exc}"

            if attempt >= max_retries:
                raise SwapHistoryLoadError(
                    f"{inst_id} request exhausted retries: {retry_error}"
                )
            sleep_fn(0.5 * (2 ** attempt))

        if payload is None or str(payload.get("code")) != "0":
            raise SwapHistoryLoadError(f"{inst_id} request failed after retries")
        raw_rows = payload.get("data")
        if raw_rows is None:
            raise SwapHistoryLoadError(f"{inst_id} response missing data field")
        if not isinstance(raw_rows, list):
            raise SwapHistoryLoadError(f"{inst_id} response data must be a list")
        if not raw_rows:
            break

        page_timestamps = []
        for raw_row in raw_rows:
            if not isinstance(raw_row, (list, tuple)) or not raw_row:
                raise SwapHistoryLoadError(f"{inst_id} received malformed page row")
            try:
                page_timestamps.append(int(raw_row[0]))
            except (TypeError, ValueError) as exc:
                raise SwapHistoryLoadError(
                    f"{inst_id} received invalid timestamp in page"
                ) from exc
        oldest = min(page_timestamps)
        if cursor is not None and oldest >= cursor:
            raise SwapHistoryLoadError(
                f"{inst_id} pagination stalled: oldest={oldest}, cursor={cursor}"
            )

        for raw_row in raw_rows:
            candle = _parse_swap_row(raw_row)
            if candle is None:
                continue
            ts = candle["time"]
            if start_ms <= ts < end_ms:
                if ts in by_timestamp:
                    api_duplicate_count += 1
                else:
                    by_timestamp[ts] = candle

        pages += 1
        if oldest <= start_ms:
            break
        cursor = oldest
        sleep_fn(MIN_PAGE_INTERVAL_SECONDS)
    else:
        raise SwapHistoryLoadError(f"{inst_id} exceeded max_pages={max_pages}")

    candles = sorted(by_timestamp.values(), key=lambda row: row["time"])
    report = validate_swap_hourly_candles(candles, start_ms, end_ms)
    report.update({
        "instrument_id": inst_id,
        "market_type": "SWAP",
        "settlement_currency": "USDT",
        "source": "OKX /api/v5/market/history-candles",
        "bar": "1H",
        "pages_fetched": pages,
        "api_duplicate_count": api_duplicate_count,
        "requested_start_ms": start_ms,
        "requested_end_ms": end_ms,
        "complete": report["complete"] and api_duplicate_count == 0,
    })
    return candles, report
