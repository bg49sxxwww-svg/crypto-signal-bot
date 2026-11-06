"""Experimental four-tranche exits for strategy D.

The production D entry rules are reused unchanged by run_d_tp4_backtest.
TP1 retains the original D target at 2.5 ATR; TP2-TP4 are experimental.
OHLC ambiguity policy: at most the nearest remaining target fills per bar.
If stop and a target are both touched, the stop wins. Entry and exit costs
are both included in effective fills.
"""
from __future__ import annotations

import math

DEFAULT_TARGET_ATRS = (2.5, 3.5, 4.5, 5.5)
DEFAULT_ALLOCATIONS = (0.40, 0.30, 0.20, 0.10)


def build_tp4_position(
    side, entry_reference, atr, stop_atr=1.5,
    target_atrs=DEFAULT_TARGET_ATRS, allocations=DEFAULT_ALLOCATIONS,
    entry_cost_rate=0.0015,
):
    side = str(side).upper()
    if side not in ("LONG", "SHORT"):
        raise ValueError("side must be LONG or SHORT")
    if not all(math.isfinite(float(v)) and float(v) > 0
               for v in (entry_reference, atr, stop_atr)):
        raise ValueError("entry_reference, atr and stop_atr must be positive")
    if len(target_atrs) != 4 or len(allocations) != 4:
        raise ValueError("exactly four targets and allocations are required")
    if any(not math.isfinite(float(v)) or float(v) <= 0 for v in target_atrs):
        raise ValueError("target ATR multiples must be positive")
    if any(not math.isfinite(float(v)) or float(v) <= 0 for v in allocations):
        raise ValueError("allocations must be positive")
    if abs(sum(allocations) - 1.0) > 1e-9:
        raise ValueError("allocations must sum to 1.0")
    if tuple(target_atrs) != tuple(sorted(target_atrs)):
        raise ValueError("target ATR multiples must be ascending")
    if not 0 <= entry_cost_rate < 1:
        raise ValueError("entry_cost_rate must be in [0, 1)")
    sign = 1 if side == "LONG" else -1
    reference = float(entry_reference)
    entry_fill = reference * (1 + entry_cost_rate if side == "LONG"
                              else 1 - entry_cost_rate)
    return {
        "side": side,
        "entry_reference": reference,
        "entry_fill": entry_fill,
        "stop": reference - sign * float(atr) * float(stop_atr),
        "targets": [reference + sign * float(atr) * float(m)
                    for m in target_atrs],
        "allocations": tuple(float(v) for v in allocations),
        "targets_hit": [],
        "remaining_fraction": 1.0,
        "realized_return": 0.0,
        "closed": False,
    }


def _event(position, reason, reference, fraction, cost_rate):
    side = position["side"]
    fill = reference * (1 - cost_rate if side == "LONG" else 1 + cost_rate)
    if side == "LONG":
        trade_return = fill / position["entry_fill"] - 1
    else:
        trade_return = position["entry_fill"] / fill - 1
    contribution = trade_return * fraction
    position["realized_return"] += contribution
    position["remaining_fraction"] = max(
        0.0, position["remaining_fraction"] - fraction
    )
    if position["remaining_fraction"] <= 1e-12:
        position["remaining_fraction"] = 0.0
        position["closed"] = True
    return {
        "reason": reason, "fill": fill, "fraction": fraction,
        "return_contribution": contribution,
    }


def process_tp4_bar(position, candle, cost_rate=0.0015):
    if not 0 <= cost_rate < 1:
        raise ValueError("cost_rate must be in [0, 1)")
    if position["closed"] or position["remaining_fraction"] <= 1e-12:
        return []
    high, low, open_price = (float(candle[k]) for k in ("high", "low", "open"))
    if low > high or open_price <= 0:
        raise ValueError("invalid OHLC candle")
    side = position["side"]
    stop_hit = low <= position["stop"] if side == "LONG" else high >= position["stop"]
    remaining = [i for i in range(4) if i not in position["targets_hit"]]
    touched = [
        i for i in remaining
        if (high >= position["targets"][i] if side == "LONG"
            else low <= position["targets"][i])
    ]
    if stop_hit:
        reference = min(open_price, position["stop"]) if side == "LONG" else max(open_price, position["stop"])
        return [_event(position, "STOP_LOSS", reference,
                       position["remaining_fraction"], cost_rate)]
    if not touched:
        return []
    # OHLC does not reveal intrabar path. Fill only the nearest outstanding
    # target per bar; later targets require a subsequent bar confirmation.
    index = touched[0]
    fraction = min(position["allocations"][index], position["remaining_fraction"])
    position["targets_hit"].append(index)
    return [_event(position, f"TP{index + 1}", position["targets"][index],
                   fraction, cost_rate)]


def close_tp4_position(position, reference_price, reason, cost_rate=0.0015):
    if not 0 <= cost_rate < 1:
        raise ValueError("cost_rate must be in [0, 1)")
    if reason not in ("REVERSE_CROSS", "FORCED_END"):
        raise ValueError("unsupported close reason")
    if position["closed"] or position["remaining_fraction"] <= 1e-12:
        return []
    return [_event(position, reason, float(reference_price),
                   position["remaining_fraction"], cost_rate)]


def run_d_tp4_backtest(symbol, candles, trade_log=None,
                       target_atrs=DEFAULT_TARGET_ATRS,
                       allocations=DEFAULT_ALLOCATIONS):
    """Run unchanged D entries with experimental partial exits."""
    import main

    empty = {
        "trades": 0, "win_rate": 0.0, "profit_factor": None,
        "max_drawdown": 0.0, "total_return": 0.0, "bars": len(candles),
        "period_days": 0.0, "open_position": False,
        "forced_exit_at_end": False, "low_sample": True,
        "insufficient_data": True, "entry_signals": 0,
    }
    if len(candles) < 250:
        return empty
    closes = [c["close"] for c in candles]
    fast = main.ema_series(closes, 20)
    slow = main.ema_series(closes, 60)
    atr_values = [
        main.calculate_atr(candles[max(0, i - 14):i + 1], 14)
        for i in range(len(candles))
    ]
    rsi_values = [
        main.calculate_rsi(closes[max(0, i - 14):i + 1], 14)
        for i in range(len(candles))
    ]
    four_hour = main.build_4h_candles(candles)
    if len(four_hour) < 205:
        return empty
    htf_closes = [c["close"] for c in four_hour]
    htf_fast = main.ema_series(htf_closes, 20)
    htf_slow = main.ema_series(htf_closes, 60)
    htf_long = main.ema_series(htf_closes, 200)
    htf_index = {c["time"]: i for i, c in enumerate(four_hour)}
    hour_ms = 3600000
    four_hours_ms = 4 * hour_ms
    cost = main.FEE_RATE + main.SLIPPAGE_RATE
    equity = peak = 1.0
    max_drawdown = 0.0
    position = None
    closed_returns = []
    forced = False
    entries = 0

    def apply_events(events, timestamp):
        nonlocal equity, position
        for event in events:
            position["trade_events"].append(event)
            if event["reason"] in ("STOP_LOSS", "REVERSE_CROSS", "FORCED_END") or position["closed"]:
                closed_returns.append(position["realized_return"])
                equity *= max(0.0, 1.0 + position["realized_return"])
                if trade_log is not None:
                    trade_log.append({
                        "strategy": "D_TP4", "symbol": symbol,
                        "side": position["side"],
                        "entry_time_utc": main.utc_time_from_ms(position["entry_time"]),
                        "entry_price": round(position["entry_fill"], 10),
                        "exit_time_utc": main.utc_time_from_ms(timestamp),
                        "exit_price": round(event["fill"], 10),
                        "exit_reason": event["reason"],
                        "return_pct": round(position["realized_return"] * 100, 6),
                        "fee_rate_one_way": main.FEE_RATE,
                        "slippage_rate_one_way": main.SLIPPAGE_RATE,
                        "tp_events": ";".join(e["reason"] for e in position["trade_events"]),
                    })
                position = None
                break

    for i in range(60, len(candles)):
        candle = candles[i]
        position_at_start = position
        if position is not None:
            reverse = (
                fast[i - 2] >= slow[i - 2] and fast[i - 1] < slow[i - 1]
                if position["side"] == "LONG"
                else fast[i - 2] <= slow[i - 2] and fast[i - 1] > slow[i - 1]
            )
            if reverse:
                apply_events(close_tp4_position(position, candle["open"],
                                                 "REVERSE_CROSS", cost), candle["time"])
            else:
                apply_events(process_tp4_bar(position, candle, cost), candle["time"])

        if position is None and i < len(candles) - 1:
            cross_up = fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]
            cross_down = fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]
            close_time = candle["time"] + hour_ms
            bucket = ((close_time // four_hours_ms) - 1) * four_hours_ms
            htf_i = htf_index.get(bucket)
            if htf_i is not None and htf_i >= 199:
                trend_up = htf_fast[htf_i] > htf_slow[htf_i] and htf_closes[htf_i] > htf_long[htf_i]
                trend_down = htf_fast[htf_i] < htf_slow[htf_i] and htf_closes[htf_i] < htf_long[htf_i]
                rsi, atr = rsi_values[i], atr_values[i]
                if atr is not None and atr > 0 and rsi is not None:
                    next_open = candles[i + 1]["open"]
                    side = "LONG" if cross_up and trend_up and main.d_rsi_filter("LONG", rsi) else (
                        "SHORT" if cross_down and trend_down and main.d_rsi_filter("SHORT", rsi) else None
                    )
                    if side:
                        position = build_tp4_position(
                            side, next_open, atr, target_atrs=target_atrs,
                            allocations=allocations, entry_cost_rate=cost,
                        )
                        position.update({
                            "entry_time": candles[i + 1]["time"],
                            "trade_events": [],
                        })
                        entries += 1

        marked = equity
        if position is not None and position is position_at_start:
            mark = candle["close"] * (1 - cost if position["side"] == "LONG" else 1 + cost)
            unrealized = (
                mark / position["entry_fill"] - 1 if position["side"] == "LONG"
                else position["entry_fill"] / mark - 1
            )
            marked = equity * max(
                0.0,
                1.0 + position["realized_return"]
                + unrealized * position["remaining_fraction"],
            )
        peak = max(peak, marked)
        max_drawdown = max(max_drawdown, (peak - marked) / peak if peak > 0 else 0.0)

    if position is not None:
        apply_events(close_tp4_position(position, candles[-1]["close"], "FORCED_END", cost),
                     candles[-1]["time"])
        forced = True
    wins = [r for r in closed_returns if r > 0]
    losses = [r for r in closed_returns if r < 0]
    gross_loss = abs(sum(losses))
    pf = sum(wins) / gross_loss if gross_loss else None
    peak = max(peak, equity)
    max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 0.0)
    return {
        "trades": len(closed_returns),
        "win_rate": len(wins) / len(closed_returns) * 100 if closed_returns else 0.0,
        "profit_factor": pf,
        "max_drawdown": max_drawdown * 100,
        "total_return": (equity - 1) * 100,
        "bars": len(candles),
        "period_days": (candles[-1]["time"] - candles[0]["time"]) / (24 * hour_ms),
        "open_position": False, "forced_exit_at_end": forced,
        "low_sample": len(closed_returns) < main.BACKTEST_MIN_TRADES,
        "insufficient_data": False, "entry_signals": entries,
    }
