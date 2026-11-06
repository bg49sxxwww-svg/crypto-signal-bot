# Changelog

## 2026-11-06
- Added D strategy: 1H EMA 20/60 crossover with completed 4H EMA 20/60/200 trend filter.
- Added D strategy RSI entry bands: LONG 55–68; SHORT 32–45.
- Kept A/B/C strategies unchanged.
- Corrected report methodology: A baseline exits on reverse EMA cross and does not use ATR stop/target; B/C/D use ATR(14) 1.5x stop and 2.5x target.
- Added synthetic 90-day four-strategy end-to-end regression coverage.
- Added regression tests for indicator output, complete 4H aggregation, D RSI boundaries, insufficient-history handling, and report descriptions.
- Added GitHub Actions workflow to run tests and upload text/SVG evidence.
