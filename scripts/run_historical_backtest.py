#!/usr/bin/env python3
"""Run an isolated historical comparison of strategies A/B/C/D on OKX spot candles.

This script does not send Telegram messages and does not place orders.
"""
import csv
import datetime as dt
import json
import logging
import math
import sys
from pathlib import Path

import main

DAYS = 180
SYMBOLS = list(main.SYMBOLS)
STRATEGIES = {
    "D": main.backtest_ema_filtered,
}
LABELS = {
    "D": "1H EMA 20/60 + completed 4H EMA 20/60/200 + RSI bands LONG 55-68 / SHORT 32-45",
}
OUT = Path("historical_backtest_results")
HOUR_MS = 60 * 60 * 1000


def iso_utc(timestamp_ms):
    return dt.datetime.fromtimestamp(
        timestamp_ms / 1000, tz=dt.timezone.utc
    ).isoformat()


def validate_history(symbol, candles):
    if len(candles) < int(DAYS * 24 * 0.95):
        raise RuntimeError(
            f"{symbol}: insufficient candles ({len(candles)}; "
            f"expected at least {int(DAYS * 24 * 0.95)})"
        )
    span_days = (candles[-1]["time"] - candles[0]["time"]) / (24 * HOUR_MS)
    if span_days < DAYS - 1.5:
        raise RuntimeError(
            f"{symbol}: insufficient date coverage ({span_days:.2f} days)"
        )
    times = [c["time"] for c in candles]
    gaps = sum(
        1 for left, right in zip(times, times[1:])
        if right - left != HOUR_MS
    )
    gap_pct = gaps / max(1, len(candles) - 1) * 100
    if gap_pct > 1.0:
        raise RuntimeError(
            f"{symbol}: too many missing hourly intervals ({gaps}, {gap_pct:.2f}%)"
        )
    return {
        "bars": len(candles),
        "span_days": round(span_days, 2),
        "first_candle_utc": iso_utc(candles[0]["time"]),
        "last_candle_utc": iso_utc(candles[-1]["time"]),
        "missing_hour_intervals": gaps,
        "gap_pct": round(gap_pct, 4),
    }


def safe_number(value):
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def main_run():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    OUT.mkdir(exist_ok=True)
    main.BACKTEST_DAYS = DAYS
    main.BACKTEST_MAX_BARS = DAYS * 24 + 100

    all_summary = []
    all_trades = []
    coverage = {}
    failures = []

    logging.info(
        "Starting %s-day OKX historical backtest; spot candles; "
        "fee %.3f%% + slippage %.3f%% each side",
        DAYS, main.FEE_RATE * 100, main.SLIPPAGE_RATE * 100,
    )

    for symbol in SYMBOLS:
        logging.info("Fetching %s historical candles", symbol)
        try:
            candles = main.get_backtest_klines(symbol, DAYS)
            coverage[symbol] = validate_history(symbol, candles)
            logging.info(
                "%s data validated: %s bars / %.2f days / %s gaps",
                symbol, coverage[symbol]["bars"],
                coverage[symbol]["span_days"],
                coverage[symbol]["missing_hour_intervals"],
            )
            for strategy_code, strategy_fn in STRATEGIES.items():
                trade_rows = []
                result = strategy_fn(
                    symbol, candles=candles, trade_log=trade_rows
                )
                if result.get("insufficient_data"):
                    raise RuntimeError(
                        f"{symbol} {strategy_code}: strategy reported insufficient data"
                    )
                for row in trade_rows:
                    row["strategy_code"] = strategy_code
                    row["strategy_label"] = LABELS[strategy_code]
                all_trades.extend(trade_rows)

                all_summary.append({
                    "symbol": symbol,
                    "strategy": strategy_code,
                    "strategy_label": LABELS[strategy_code],
                    "bars": result["bars"],
                    "period_days": round(result["period_days"], 2),
                    "trades": result["trades"],
                    "win_rate_pct": round(result["win_rate"], 4),
                    "profit_factor": safe_number(result["profit_factor"]),
                    "max_drawdown_pct": round(result["max_drawdown"], 4),
                    "total_return_pct": round(result["total_return"], 4),
                    "low_sample": result["low_sample"],
                    "forced_exit_at_end": result["forced_exit_at_end"],
                    "fee_rate_one_way_pct": main.FEE_RATE * 100,
                    "slippage_one_way_pct": main.SLIPPAGE_RATE * 100,
                })
        except Exception as exc:
            logging.exception("%s historical test failed", symbol)
            failures.append({"symbol": symbol, "error": str(exc)})
        finally:
            import time
            time.sleep(0.25)

    with (OUT / "coverage.json").open("w", encoding="utf-8") as f:
        json.dump(coverage, f, ensure_ascii=False, indent=2)
    with (OUT / "failures.json").open("w", encoding="utf-8") as f:
        json.dump(failures, f, ensure_ascii=False, indent=2)
    with (OUT / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(all_summary, f, ensure_ascii=False, indent=2)

    if all_summary:
        with (OUT / "summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_summary[0]))
            writer.writeheader()
            writer.writerows(all_summary)
    if all_trades:
        fields = list(all_trades[0])
        with (OUT / "trades.csv").open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(all_trades)

    lines = [
        f"# OKX {DAYS}-day historical strategy comparison",
        "",
        f"- Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        "- Data: OKX public **spot** 1H candles (USDT pairs), closed candles only",
        f"- Costs: fee {main.FEE_RATE * 100:.3f}% + slippage {main.SLIPPAGE_RATE * 100:.3f}% per side",
        "- Leverage and funding fees: excluded",
        "- Execution: signal on closed 1H candle, entry at next 1H open; conservative stop-first when stop and target are both touched",
        "- This is a historical simulation, not a live result or a guarantee of future performance",
        "",
        "## Data coverage",
        "",
        "| Symbol | Bars | Days | Missing hourly intervals | First UTC | Last UTC |",
        "|---|---:|---:|---:|---|---|",
    ]
    for symbol, info in coverage.items():
        lines.append(
            f"| {symbol} | {info['bars']} | {info['span_days']:.2f} | "
            f"{info['missing_hour_intervals']} | {info['first_candle_utc']} | "
            f"{info['last_candle_utc']} |"
        )

    lines.extend([
        "",
        "## Strategy results",
        "",
        "| Symbol | Group | Trades | Win rate | Profit factor | Max drawdown | Total return | Sample warning |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ])
    for row in all_summary:
        pf = "N/A" if row["profit_factor"] is None else f"{row['profit_factor']:.2f}"
        lines.append(
            f"| {row['symbol']} | {row['strategy']} | {row['trades']} | "
            f"{row['win_rate_pct']:.2f}% | {pf} | "
            f"{row['max_drawdown_pct']:.2f}% | {row['total_return_pct']:.2f}% | "
            f"{'LOW' if row['low_sample'] else 'OK'} |"
        )

    lines.extend([
        "",
        "## Limitations",
        "",
        "- OKX spot candles are used as a consistent price series; perpetual swap basis, funding, liquidation and contract-specific fees are not modeled.",
        "- The 4H EMA200 strategies require at least 200 completed 4H bars before signals can qualify; their effective signal history is shorter than the full displayed period.",
        "- Missing hourly intervals are reported; incomplete 4H buckets are excluded by the existing aggregation function.",
        "- Results are compounded trade returns from the existing strategy engine; position sizing, portfolio-level capital allocation and concurrent-symbol exposure are not modeled.",
        "",
        f"## Data fetch failures: {len(failures)}",
    ])
    for item in failures:
        lines.append(f"- {item['symbol']}: {item['error']}")
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    expected_rows = len(SYMBOLS) * len(STRATEGIES)
    if failures or len(all_summary) != expected_rows:
        logging.error(
            "Historical run incomplete: %s/%s strategy-symbol rows; %s failed symbols",
            len(all_summary), expected_rows, len(failures),
        )
        return 1

    logging.info(
        "Historical run complete: %s strategy-symbol rows, %s closed trades",
        len(all_summary), len(all_trades),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main_run())
