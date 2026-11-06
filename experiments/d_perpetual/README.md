# Strategy D Perpetual Data Research

Status: research-only design stage. No orders, credentials, account access, or live-trading code.

## Isolation and invariants

- This experiment is isolated from the spot data loader and the frozen Strategy D baseline.
- Do not change `main.py`, production signal generation, Telegram execution, or order code.
- Do not merge or deploy this branch without explicit approval.
- Initial instruments: `BTC-USDT-SWAP` and `ETH-USDT-SWAP`.
- Initial signal timeframe: 1H; completed 4H filter remains owned by the frozen Strategy D implementation.
- Use completed candles only. Preserve UTC timestamp alignment and reject duplicates, gaps, and out-of-order records.

## Required independent datasets

| Dataset | OKX public endpoint | Purpose |
|---|---|---|
| Swap candles | `GET /api/v5/market/history-candles` with SWAP `instId` | Signal and entry-price series |
| Mark-price candles | `GET /api/v5/market/history-mark-price-candles` | Mark-price risk and liquidation simulation |
| Index candles | `GET /api/v5/market/history-index-candles` | Index reference series |
| Funding history | `GET /api/v5/public/funding-rate-history` | Funding cash flows while positions are open |
| Instrument specs | `GET /api/v5/public/instruments?instType=SWAP` | Contract value, multiplier, lot size, tick size, minimum size and state |
| Position tiers | `GET /api/v5/public/position-tiers` | Maintenance-margin and liquidation assumptions |

All endpoints must be independently paginated, timestamp-normalized, validated, cached, and accompanied by coverage metadata. Do not assume that one endpoint's retention window applies to another.

## Critical funding-history gate

The official API documents pagination and a maximum page size of 400 for funding-rate history. The currently verified documentation does not establish that a complete 2–3 year funding archive is available through this endpoint.

Therefore:
- Do not label a multi-year perpetual backtest as fully funding-adjusted unless the funding series covers the entire test interval.
- If funding coverage is shorter, report the exact covered interval and mark the full-period net result as incomplete.
- Do not forward-fill funding rates across missing settlement events or substitute current rates for historical rates.
- Evaluate a separately sourced historical funding archive only after its provenance, timestamps, instrument mapping, and completeness can be validated.

## Data acceptance criteria

1. Confirm each requested instrument is an active USDT-margined linear SWAP and record its contract specifications.
2. Fetch only closed 1H candles; independently check mark/index candle coverage.
3. Verify pagination has no repeated pages, duplicate timestamps, missing hourly bars, or silently truncated history.
4. Store raw API responses or auditable normalized CSV/JSON plus metadata (instrument, endpoint, interval, retrieval time, first/last timestamp, row count, gaps, duplicates).
5. Cache writes must be atomic; cache reads must reject wrong schema, gaps, duplicates, and out-of-order rows.
6. Report coverage separately for swap candles, mark prices, index prices, and funding history.
7. Tests must use deterministic mocked API responses; live smoke tests must be read-only and must never require API keys.

## Backtest requirements (not implemented in this data-only phase)

- Keep Strategy D entry/exit signal logic frozen for the first spot-versus-perpetual comparison.
- Model funding only at actual funding timestamps and only when a position is open at settlement.
- Make stop trigger reference explicit (last price versus mark price); use mark price for liquidation risk.
- Model fees from an explicit configurable fee schedule, slippage, contract sizing/rounding, leverage, isolated margin, maintenance-margin tiers, liquidation fees, and reduce-only exits.
- Use contract specifications for position sizing; never assume one contract equals one unit of base currency.
- Separate signal price, simulated fill price, mark price, and index price in trade records.
- Report spot and perpetual results separately; do not compare them as if execution costs and margin mechanics were identical.

## Proposed implementation sequence

1. Build and test a SWAP candle loader independently of the spot loader.
2. Add mark-price and index-price loaders with independent coverage checks.
3. Add instrument-spec and position-tier snapshots with schema validation.
4. Investigate historical funding coverage and define a hard completeness gate.
5. Only after data acceptance passes, design the derivatives-aware backtest engine.
6. Paper simulation before any discussion of live execution. Live trading remains disabled by default.

## Initial configuration for research only

- Venue: OKX
- Instruments: BTC-USDT-SWAP, ETH-USDT-SWAP
- Timeframes: 1H signal, completed 4H filter
- Leverage scenarios: 1x, 2x, 3x (sensitivity analysis only)
- Margin mode: isolated (simulation only)
- Risk budget reference: 0.5% per trade; 3% daily stop threshold (configurable, not an order instruction)
- Existing Strategy D ATR exits: preserve unchanged for the first comparison
- Live trading: disabled
