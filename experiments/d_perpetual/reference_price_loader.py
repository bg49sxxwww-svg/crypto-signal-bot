"""Independent OKX mark-price and index-price 1H history loaders.

These series are deliberately separate from contract traded-price candles.
Timestamps are UTC Unix milliseconds and identify candle-open time.
"""
from __future__ import annotations

import time
from typing import Callable

import requests

OKX_MARK_HISTORY_URL = "https://www.okx.com/api/v5/market/history-mark-price-candles"
OKX_INDEX_HISTORY_URL = "https://www.okx.com/api/v5/market/history-index-candles"
HOUR_MS = 3_600_000
PAGE_LIMIT = 100
REQUEST_TIMEOUT = 20
MIN_PAGE_INTERVAL_SECONDS = 0.12
RETRYABLE_HTTP_STATUS = (429, 500, 502, 503, 504)


class ReferencePriceLoadError(RuntimeError):
    """Raised when reference-price history cannot be fetched safely."""


def _parse_reference_row(row, series_name: str) -> dict | None:
    if not isinstance(row, (list, tuple)) or len(row) < 6:
        raise ReferencePriceLoadError(f"Malformed {series_name} candle row")
    try:
        timestamp = int(row[0])
    except (TypeError, ValueError) as exc:
        raise ReferencePriceLoadError(f"Invalid {series_name} timestamp") from exc
    if timestamp % HOUR_MS:
        raise ReferencePriceLoadError(f"Unaligned {series_name} 1H timestamp: {timestamp}")
    if str(row[5]) != "1":
        return None
    try:
        values = [float(row[i]) for i in range(1, 5)]
    except (TypeError, ValueError) as exc:
        raise ReferencePriceLoadError(f"Invalid {series_name} OHLC at {timestamp}") from exc
    open_px, high_px, low_px, close_px = values
    if any(value <= 0 for value in values):
        raise ReferencePriceLoadError(f"Non-positive {series_name} price at {timestamp}")
    if high_px < max(open_px, close_px, low_px) or low_px > min(open_px, close_px, high_px):
        raise ReferencePriceLoadError(f"Invalid {series_name} OHLC range at {timestamp}")
    return {
        "time": timestamp,
        "open": open_px,
        "high": high_px,
        "low": low_px,
        "close": close_px,
    }


def validate_reference_hourly_candles(candles: list[dict], start_ms: int, end_ms: int) -> dict:
    try:
        timestamps = [int(row["time"]) for row in candles]
    except (KeyError, TypeError, ValueError) as exc:
        raise ReferencePriceLoadError("Malformed normalized reference-price candle") from exc
    expected_start = ((start_ms + HOUR_MS - 1) // HOUR_MS) * HOUR_MS
    expected_end = (end_ms // HOUR_MS) * HOUR_MS
    ordered = timestamps == sorted(timestamps)
    unique = len(timestamps) == len(set(timestamps))
    aligned = all(ts % HOUR_MS == 0 for ts in timestamps)
    in_range = all(expected_start <= ts < expected_end for ts in timestamps)
    present = set(timestamps)
    missing = [ts for ts in range(expected_start, expected_end, HOUR_MS) if ts not in present]
    return {
        "row_count": len(candles),
        "duplicate_count": len(timestamps) - len(present),
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


def _fetch_reference_history(
    endpoint: str,
    inst_id: str,
    start_ms: int,
    end_ms: int,
    series_name: str,
    *,
    session=None,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_pages: int = 20_000,
    max_retries: int = 4,
) -> tuple[list[dict], dict]:
    if not isinstance(inst_id, str) or not inst_id.strip():
        raise ValueError("inst_id must be a non-empty string")
    if end_ms <= start_ms or start_ms < 0:
        raise ValueError("invalid requested timestamp range")
    if max_pages < 1 or max_retries < 0:
        raise ValueError("max_pages must be >= 1 and max_retries >= 0")

    client = session or requests.Session()
    by_timestamp = {}
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
                response = client.get(endpoint, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ReferencePriceLoadError("OKX response must be a JSON object")
                code = str(payload.get("code"))
                if code == "0":
                    break
                if code != "50011":
                    raise ReferencePriceLoadError(
                        f"{series_name} OKX error {code}: {payload.get('msg')}"
                    )
                retry_error = f"OKX rate limit: {payload.get('msg')}"
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status not in RETRYABLE_HTTP_STATUS:
                    raise ReferencePriceLoadError(f"{series_name} HTTP error: {exc}") from exc
                retry_error = str(exc)
            except (requests.ConnectionError, requests.Timeout) as exc:
                retry_error = str(exc)
            except ValueError as exc:
                retry_error = f"invalid JSON response: {exc}"
            if attempt >= max_retries:
                raise ReferencePriceLoadError(
                    f"{series_name} request exhausted retries: {retry_error}"
                )
            sleep_fn(0.5 * (2 ** attempt))

        if payload is None or str(payload.get("code")) != "0":
            raise ReferencePriceLoadError(f"{series_name} request failed after retries")
        raw_rows = payload.get("data")
        if not isinstance(raw_rows, list):
            raise ReferencePriceLoadError(f"{series_name} response data must be a list")
        if not raw_rows:
            break

        page_timestamps = []
        for row in raw_rows:
            if not isinstance(row, (list, tuple)) or not row:
                raise ReferencePriceLoadError(f"Malformed {series_name} page row")
            try:
                page_timestamps.append(int(row[0]))
            except (TypeError, ValueError) as exc:
                raise ReferencePriceLoadError(f"Invalid {series_name} page timestamp") from exc
        oldest = min(page_timestamps)
        if cursor is not None and oldest >= cursor:
            raise ReferencePriceLoadError(
                f"{series_name} pagination stalled: oldest={oldest}, cursor={cursor}"
            )

        for raw_row in raw_rows:
            candle = _parse_reference_row(raw_row, series_name)
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
        raise ReferencePriceLoadError(f"{series_name} exceeded max_pages={max_pages}")

    candles = sorted(by_timestamp.values(), key=lambda row: row["time"])
    report = validate_reference_hourly_candles(candles, start_ms, end_ms)
    report.update({
        "instrument_id": inst_id,
        "series": series_name,
        "endpoint": endpoint,
        "bar": "1H",
        "pages_fetched": pages,
        "api_duplicate_count": api_duplicate_count,
        "requested_start_ms": start_ms,
        "requested_end_ms": end_ms,
        "complete": report["complete"] and api_duplicate_count == 0,
    })
    return candles, report


def fetch_okx_mark_price_1h_history(inst_id: str, start_ms: int, end_ms: int, **kwargs):
    """Fetch historical mark-price candles for a derivative instrument."""
    if not inst_id.endswith("-SWAP"):
        raise ValueError("mark-price inst_id must identify a SWAP instrument")
    return _fetch_reference_history(
        OKX_MARK_HISTORY_URL, inst_id, start_ms, end_ms, "mark_price", **kwargs
    )


def fetch_okx_index_price_1h_history(index_inst_id: str, start_ms: int, end_ms: int, **kwargs):
    """Fetch historical index candles; pass the exact OKX index ID separately."""
    return _fetch_reference_history(
        OKX_INDEX_HISTORY_URL, index_inst_id, start_ms, end_ms, "index_price", **kwargs
    )
