# Changelog

## 2026-11-06
- Added an isolated TP1-TP4 partial-exit engine for D strategy experiments, with configurable ATR targets and 40/30/20/10 allocation defaults.
- Added regression tests for long/short target geometry, partial exits, stop-first same-bar handling, full closure, and invalid allocation validation.
- This is an experimental execution primitive only; strategy D and its production behavior remain unchanged. Historical integration and performance validation are pending.

## 2026-11-06
- Clarified Telegram trade ideas as candidate entry plans, with explicit LONG/SHORT labels and percentage distances to stop-loss and take-profit; added regression coverage for both directions.

## 2026-11-06
- Extended the isolated OKX historical backtest to 180 days and narrowed the run to strategy D only, retaining all eight symbols and the existing data/cost validation.

## 2026-11-06
- Added an isolated 90-day OKX spot historical comparison runner for strategies A/B/C/D, with candle coverage validation and JSON/CSV/Markdown outputs.
- Added a dedicated GitHub Actions workflow to run regression tests before the historical comparison and upload the resulting evidence.
- Added D strategy: 1H EMA 20/60 crossover with completed 4H EMA 20/60/200 trend filter.
- Added D strategy RSI entry bands: LONG 55–68; SHORT 32–45.
- Kept A/B/C strategies unchanged.
- Corrected report methodology: A baseline exits on reverse EMA cross and does not use ATR stop/target; B/C/D use ATR(14) 1.5x stop and 2.5x target.
- Added synthetic 90-day four-strategy end-to-end regression coverage.
- Added regression tests for indicator output, complete 4H aggregation, D RSI boundaries, insufficient-history handling, and report descriptions.
- Added GitHub Actions workflow to run tests and upload text/SVG evidence.

## 2026-11-06
- Fixed D strategy end-of-backtest forced-exit records being mislabeled as strategy C; added a targeted regression test to keep D trade logs correctly attributed.
- Added separate close-based and conservative OHLC intrabar maximum drawdown metrics for strategy D; retained `max_drawdown` as the close-based compatibility field and exposed both values in reports.
- Refined D intrabar drawdown ordering so current-bar realized equity only becomes a peak for subsequent bars; added coverage for a target-only exit after an adverse intrabar move.
