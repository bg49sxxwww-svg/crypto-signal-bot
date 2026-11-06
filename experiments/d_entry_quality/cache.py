"""Atomic CSV cache for Strategy D experiment candles."""
import csv
import os
import tempfile
from pathlib import Path

from .data_loader import HOUR_MS, HistoryLoadError, validate_hourly_candles

FIELDS = ("time", "open", "high", "low", "close", "volume")


def save_candles(path, candles):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = list(candles)
    if rows:
        report = validate_hourly_candles(rows, rows[0]["time"], rows[-1]["time"] + HOUR_MS)
        if not report["complete"]:
            raise HistoryLoadError("Refusing to cache incomplete or invalid candles")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", newline="", encoding="utf-8", dir=target.parent,
            delete=False, suffix=".tmp"
        ) as handle:
            temporary = handle.name
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows({key: row[key] for key in FIELDS} for row in rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load_candles(path):
    with Path(path).open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise HistoryLoadError("Unexpected candle cache columns")
        rows = [{
            "time": int(row["time"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        } for row in reader]
    if rows:
        report = validate_hourly_candles(rows, rows[0]["time"], rows[-1]["time"] + HOUR_MS)
        if not report["complete"]:
            raise HistoryLoadError("Candle cache failed continuity/integrity validation")
    return rows
