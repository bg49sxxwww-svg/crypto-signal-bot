# Strategy D Entry-Quality Experiment

## Safety
- Isolated research branch only. Strategy D remains the frozen baseline.
- No production strategy, Telegram, order execution, or live-trading changes.
- PR #1 and PR #2 remain draft and unmerged.

## Frozen baseline
- 1H EMA20/EMA60 cross.
- Most recently completed 4H EMA20/EMA60 alignment and 4H close relative to EMA200.
- RSI(14): LONG 55–68; SHORT 32–45.
- Signal on closed 1H candle; enter next 1H open.
- ATR(14) stop 1.5 ATR; target 2.5 ATR.
- Stop-first on ambiguous stop/target bars; reverse cross at next open; force close at test end.
- Existing one-way fee 0.10% and slippage 0.05%.

## Stage 0 audit
1. `main.py` has a 90-day data limit and a corresponding bar cap. A separate experiment loader is required for 2–3 years.
2. Existing ATR and RSI use simple averages, not Wilder smoothing. Preserve this behavior in D-BASE; document it rather than silently changing the baseline.
3. EMA is seeded from the first close. D waits for 200 completed 4H bars before qualifying signals.
4. `build_4h_candles` uses UTC-aligned buckets and discards incomplete groups. Add tests for missing, duplicate, out-of-order, and boundary candles.
5. New filters must only use information available at the 1H signal close. Entry remains the next 1H open.
6. The existing historical runner mutates global `main.BACKTEST_DAYS` and `main.BACKTEST_MAX_BARS`; the new runner must own its data settings.
7. Results compound per-symbol trades and do not model portfolio concurrency, allocation, leverage, funding, or liquidation. Do not present per-symbol averages as portfolio returns.
8. D and D-TP4 drawdown methods differ; validate the D baseline independently before comparing new filters.

## Data requirements
- Target at least 730–1,095 days of closed 1H candles per symbol, with a warm-up buffer.
- Record source, instrument type, retrieval time, first/last timestamps, row count, duplicates, missing intervals, and fetch failures.
- Never forward-fill missing OHLCV. Build 4H bars only from four contiguous UTC-aligned 1H bars.
- Existing source is OKX spot, not a perpetual execution model.

## One-variable experiments
- D-E1: ADX(14), initial threshold 20; sensitivity 18/20/25.
- D-E2: 4H EMA200 slope; lookback 3/5/10 completed bars.
- D-E3: 1H volume divided by prior 20-bar average; initial 1.2, sensitivity 1.0/1.2/1.5.
- D-E4: close-confirmed break of prior 1H high/low; lookback 10/20/30.
- D-E5: combine only filters that improve standalone out-of-sample results.

## Validation
- Run D-BASE twice on identical frozen candles; require identical metrics and trade logs.
- Compare each candidate on identical data, costs, fills, and D exits.
- Chronological 60/20/20 development/validation/holdout split, then walk-forward testing. Never tune on holdout.
- Report per-symbol results separately from pooled trade-level statistics; neither is a portfolio simulation.
- Report trades, win rate, PF, expectancy, average win/loss, drawdown, return, and costs.
- Stress costs at 1.5x and 2.0x.
- Research gates: OOS PF >= 1.30, positive net expectancy, >=100 OOS trades, no material drawdown deterioration, and stability across symbols/time windows. These are screening rules, not guarantees.
- Insufficient data or sample must remain explicitly inconclusive.

## Stage 0 exit criteria
- Record baseline source commit and specification.
- Pass 4H boundary/completeness and deterministic baseline tests.
- Retrieve and validate at least two years without the 90-day cap.
- No changes to `main.py` or production behavior.
