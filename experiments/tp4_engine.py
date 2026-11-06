"""Isolated TP1-TP4 execution primitives for the D strategy experiment.

Targets are experimental ATR multiples (1R, 2R, 3R, 4R where R=1 ATR).
This module does not change or import the production D strategy logic.
"""
from __future__ import annotations

DEFAULT_TARGET_ATRS = (1.0, 2.0, 3.0, 4.0)
DEFAULT_ALLOCATIONS = (0.40, 0.30, 0.20, 0.10)


def build_tp4_position(
    side,
    entry_reference,
    atr,
    stop_atr=1.5,
    target_atrs=DEFAULT_TARGET_ATRS,
    allocations=DEFAULT_ALLOCATIONS,
):
    """Build an isolated position state; entry_reference is the next-bar open."""
    side = str(side).upper()
    if side not in ("LONG", "SHORT"):
        raise ValueError("side must be LONG or SHORT")
    if entry_reference <= 0 or atr <= 0 or stop_atr <= 0:
        raise ValueError("entry_reference, atr and stop_atr must be positive")
    if len(target_atrs) != 4 or len(allocations) != 4:
        raise ValueError("exactly four targets and allocations are required")
    if any(value <= 0 for value in target_atrs):
        raise ValueError("target ATR multiples must be positive")
    if any(value <= 0 for value in allocations):
        raise ValueError("allocations must be positive")
    if abs(sum(allocations) - 1.0) > 1e-9:
        raise ValueError("allocations must sum to 1.0")
    if tuple(target_atrs) != tuple(sorted(target_atrs)):
        raise ValueError("target ATR multiples must be ascending")

    sign = 1 if side == "LONG" else -1
    return {
        "side": side,
        "entry_reference": float(entry_reference),
        "stop": float(entry_reference - sign * atr * stop_atr),
        "targets": [
            float(entry_reference + sign * atr * multiple)
            for multiple in target_atrs
        ],
        "allocations": tuple(float(value) for value in allocations),
        "targets_hit": [],
        "remaining_fraction": 1.0,
        "realized_return": 0.0,
    }


def process_tp4_bar(position, candle, cost_rate=0.0):
    """Process one OHLC bar, returning deterministic partial-exit events.

    Conservative rule: if the stop and any remaining target are touched in
    the same bar, the stop closes the entire remaining fraction first.
    Otherwise, all touched targets are filled in target order.
    """
    if not 0 <= cost_rate < 1:
        raise ValueError("cost_rate must be in [0, 1)")
    if position["remaining_fraction"] <= 1e-12:
        return []

    side = position["side"]
    high = float(candle["high"])
    low = float(candle["low"])
    open_price = float(candle["open"])
    stop = position["stop"]
    remaining_targets = [
        index for index in range(4)
        if index not in position["targets_hit"]
    ]
    stop_hit = low <= stop if side == "LONG" else high >= stop
    targets_hit_now = [
        index for index in remaining_targets
        if (
            high >= position["targets"][index]
            if side == "LONG"
            else low <= position["targets"][index]
        )
    ]

    if stop_hit:
        reference = min(open_price, stop) if side == "LONG" else max(open_price, stop)
        fraction = position["remaining_fraction"]
        fill = reference * (1 - cost_rate if side == "LONG" else 1 + cost_rate)
        gross = (
            fill / position["entry_reference"] - 1
            if side == "LONG"
            else position["entry_reference"] / fill - 1
        )
        result = gross * fraction
        position["realized_return"] += result
        position["remaining_fraction"] = 0.0
        return [{
            "reason": "STOP_LOSS",
            "fill": fill,
            "fraction": fraction,
            "return_contribution": result,
        }]

    events = []
    for index in targets_hit_now:
        fraction = min(
            position["allocations"][index],
            position["remaining_fraction"],
        )
        if fraction <= 1e-12:
            continue
        reference = position["targets"][index]
        fill = reference * (1 - cost_rate if side == "LONG" else 1 + cost_rate)
        gross = (
            fill / position["entry_reference"] - 1
            if side == "LONG"
            else position["entry_reference"] / fill - 1
        )
        result = gross * fraction
        position["targets_hit"].append(index)
        position["remaining_fraction"] -= fraction
        position["realized_return"] += result
        events.append({
            "reason": f"TP{index + 1}",
            "fill": fill,
            "fraction": fraction,
            "return_contribution": result,
        })

    if position["remaining_fraction"] < 1e-12:
        position["remaining_fraction"] = 0.0
    return events
