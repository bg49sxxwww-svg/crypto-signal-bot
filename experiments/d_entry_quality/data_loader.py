"""Isolated OKX 1H history loader for Strategy D research.

This module deliberately does not modify or reuse main.py's 90-day globals.
Timestamps are UTC Unix milliseconds and candle timestamps are candle-open times.
"""
from __future__ import annotations

import time
from typing import Callable, Iterable

import requests

OKX_HISTORY_URL = "https://www.okx.com/api/v5/market/history-candles"
HOUR_MS = 3_600_000
PAGE_LIMIT = 100
REQUEST_TIMEOUT = 20
MIN_PAGE_INTERVAL_SECONDS = 0.12


class HistoryLoadError(RuntimeError):
    """Raised when historical pagination cannot safely complete."""


def _parse_okx_row(row: list) -> dict | None:
    if len(row) < 9 or str(row[8]) != "1":
        return None
    timestamp = int(row[0])
    if timestamp % HOUR_MS:
        raise HistoryLoadError(f"Unaligned 1H candle timestamp: {timestamp}")
    candle = {
        "time": timestamp,
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
    }
    values = [candle[k] for k in ("open", "high", "low", "close", "volume")]
    if any(v < 0 for v in values) or candle["high"] < max(candle["open"], candle["close"], candle["low"]):
        raise HistoryLoadError(f"Invalid OHLCV row at {timestamp}")
    if candle["low"] > min(candle["open"], candle["close"], candle["high"]):
        raise HistoryLoadError(f"Invalid OHLCV row at {timestamp}")
    return candle


def validate_hourly_candles(
    candles: Iterable[dict], start_ms: int, end_ms: int
) -> dict:
    """Validate unique sorted closed candles in [start_ms, end_ms)."""
    rows = list(candles)
    timestamps = [int(row["time"]) for row in rows]
    duplicates = len(timestamps) - len(set(timestamps))
    ordered = timestamps == sorted(timestamps)
    unique = len(set(timestamps)) == len(timestamps)
    expected_start = ((start_ms + HOUR_MS - 1) // HOUR_MS) * HOUR_MS
    expected_end = (end_ms // HOUR_MS) * HOUR_MS
    in_range = all(expected_start <= ts < expected_end for ts in timestamps)
    aligned = all(ts % HOUR_MS == 0 for ts in timestamps)
    missing = []
    if timestamps:
        present = set(timestamps)
        missing = [
            ts for ts in range(expected_start, expected_end, HOUR_MS)
            if ts not in present
        ]
    else:
        missing = list(range(expected_start, expected_end, HOUR_MS))
    return {
        "row_count": len(rows),
        "duplicate_count": duplicates,
        "ordered": ordered,
        "unique": unique,
        "aligned": aligned,
        "in_range": in_range,
        "missing_count": len(missing),
        "missing_timestamps": missing,
        "first_timestamp": timestamps[0] if timestamps else None,
        "last_timestamp": timestamps[-1] if timestamps else None,
        "complete": bool(rows) and ordered and unique and aligned and in_range and not missing,
    }


def fetch_okx_1h_history(
    symbol: str,
    start_ms: int,
    end_ms: int,
    *,
    session=None,
    sleep_fn: Callable[[float], None] = time.sleep,
    max_pages: int = 20_000,
) -> tuple[list[dict], dict]:
    """Fetch closed OKX spot 1H candles in [start_ms, end_ms), paging backward.

    Caller should include the required 4H EMA200 warm-up buffer in start_ms.
    Raises rather than silently returning partial history when pagination stalls.
    """
    if end_ms <= start_ms:
        raise ValueError("end_ms must be greater than start_ms")
    if not symbol.endswith("USDT"):
        raise ValueError("symbol must be a USDT-quoted symbol such as BTCUSDT")

    client = session or requests.Session()
    inst_id = symbol[:-4] + "-USDT"
    candles_by_time: dict[int, dict] = {}
    duplicate_count = 0
    cursor = None
    pages = 0

    while pages < max_pages:
        params = {"instId": inst_id, "bar": "1H", "limit": str(PAGE_LIMIT)}
        if cursor is not None:
            params["after"] = str(cursor)
        try:
            response = client.get(
                OKX_HISTORY_URL, params=params, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise HistoryLoadError(f"{symbol} history request failed: {exc}") from exc

        if payload.get("code") != "0":
            raise HistoryLoadError(
                f"{symbol} OKX error {payload.get('code')}: {payload.get('msg')}"
            )
        raw = payload.get("data") or []
        if not raw:
            break

        timestamps = [int(row[0]) for row in raw if row and len(row) > 0]
        if not timestamps:
            raise HistoryLoadError(f"{symbol} received malformed empty page")
        oldest = min(timestamps)
        if cursor is not None and oldest >= cursor:
            raise HistoryLoadError(
                f"{symbol} pagination stalled: oldest={oldest}, cursor={cursor}"
            )

        for raw_row in raw:
            candle = _parse_okx_row(raw_row)
            if candle is None:
                continue
            ts = candle["time"]
            if start_ms <= ts < end_ms:
                if ts in candles_by_time:
                    duplicate_count += 1
                candles_by_time[ts] = candle

        pages += 1
        if oldest <= start_ms:
            break
        cursor = oldest
        sleep_fn(MIN_PAGE_INTERVAL_SECONDS)
    else:
        raise HistoryLoadError(f"{symbol} exceeded max_pages={max_pages}")

    candles = sorted(candles_by_time.values(), key=lambda row: row["time"])
    report = validate_hourly_candles(candles, start_ms, end_ms)
    report.update({
        "symbol": symbol,
        "instrument_id": inst_id,
        "source": "OKX spot /api/v5/market/history-candles",
        "bar": "1H",
        "pages_fetched": pages,
        "api_duplicate_count": duplicate_count,
        "requested_start_ms": start_ms,
        "requested_end_ms": end_ms,
        "complete": report["complete"] and duplicate_count == 0,
    })
    return candles, report
