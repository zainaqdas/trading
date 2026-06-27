# CHANGELOG — ATM-TS v2.0

All significant changes across eight rounds of independent code review, from initial baseline through paper-trading readiness.

---

## v8 — Final Peak Tracking Fix (2025-06-27)

### Changed
- **LiveTrader peak tracking**: `self.peak` now computed from total portfolio equity (cash + open position mark-to-market values) instead of cash alone. Mirrors backtester's `_portfolio_value()` logic. Circuit breaker now fires relative to true portfolio high.
- **BTC-first ordering documented**: Added comment explaining that `BTC-USD` must appear before `ETH-USD` in `crypto_assets` for the ETH/BTC relative strength filter to work. Fallback behavior (defaults to allowing entry) also documented.
- **ATM_TS_FINDINGS.md**: Added "Code Status: Paper-trading ready" banner to Section 0.

### Fixed
- Circuit breaker could fire prematurely by comparing against cash-based peak rather than full portfolio equity high.

---

## v7 — LiveTrader Bug Fixes (2025-06-27)

### Changed
- **`scan_and_trade()` restructured**: Data fetching and exit checks now run BEFORE the ETH/BTC relative strength filter. This ensures stop-losses and trailing stops for existing ETH positions are evaluated every scan cycle, regardless of whether the ETH/BTC ratio is favorable for new entries.
- **`_fetch_cache` added**: Local dict caches fetched data per scan cycle, eliminating redundant HTTP calls (was 4 Yahoo Finance calls per cycle, now 2).
- **`_eth_btc_strong()` removed**: Logic inlined into `scan_and_trade()` using cached data, eliminating the separate data fetch that created double-fetching.
- **ATM_TS_FINDINGS.md**: Section 3 circuit breaker value corrected to 0.20 to match code.

### Fixed
- **Critical**: ETH/BTC filter at top of symbol loop caused `continue` to skip all symbol processing for ETH, including exit checks on existing positions. If ETH crashed relative to BTC, stop-losses would not fire on the next scan cycle.
- Duplicate `is_crypto()` method removed from DataManager (was at both line 107 and line 221).

---

## v6 — Root Cause Diagnosis & Three Structural Fixes (2025-06-27)

### Added
- **Two-tier EMA entry logic** (`Strategy.generate()`):
  - Tier 1 (full stack): `price > EMA-21 > EMA-55 > EMA-200` (strong trend, unchanged)
  - Tier 2 (partial + ADX): `price > EMA-21 > EMA-55` **AND** `ADX > 25` **AND** `EMA-200 slope rising` (captures choppier trends)
  - `ema_trend_slope` column added to `Indicators.add_all()` (20-bar EMA-200 slope)
- **ETH/BTC relative strength filter** (`Backtester.run()`): Pre-computes ETH/BTC ratio and its 30-day rolling mean; filters out ETH signals when ratio is below its mean.
- **ETH/BTC filter in LiveTrader** (`_eth_btc_strong()` helper): Replicates backtester's filter logic for paper/live trading.
- **Diagnostic signal logging** (`LiveTrader.scan_and_trade()`): Logs `regime`, `ADX`, `RSI`, `full_stack`, `partial_stack`, `EMA200_slope`, `price_vs_EMA21`, `bullish_cross`, last signal date, and latest bar match on every non-signal bar.

### Changed
- **RSI filter applied to all entries**: Changed from `if r['bullish_cross'] or ((full_stack or partial_stack) and r['rsi'] < 70)` to `long_condition = (r['bullish_cross'] or full_stack or partial_stack) and r['rsi'] < 70`. Bullish crossovers no longer bypass the RSI < 70 check.

### Fixed
- Duplicate `def fetch()` and `def fetch_all()` in `DataManager` removed (first pair at lines 107-146, second pair at lines 206-259 kept). Python silently used the second definitions; removal eliminates confusion.

### Removed
- Old entry logic that allowed `bullish_cross` signals at any RSI level.

---

## v5 — Risk Defaults Reverted, Walk-Forward Rewritten (2025-06-27)

### Changed
- **Production defaults tightened**:
  - `risk_per_trade`: 7.5% → **3%** (2-3% recommended for production, 7.5% documented as "high-octane")
  - `max_position_pct`: 100% → **50%**
  - `max_drawdown_circuit_breaker`: 50% → **30%**
- **EMAs reverted**: 15/45/180 → **21/55/200** (grid search confirmed as noise at 41 trades)
- **`forex_assets` default**: `['EURUSD=X', 'GBPUSD=X']` → **empty list** (crypto-only by default)

### Rewritten
- **`WalkForwardValidator`**: Replaced parameter-optimization approach (was selecting best EMA/stop params per window, introducing selection bias) with time-based folds testing fixed default params. Added minimum trade filter (windows with < 10 trades flagged as statistically void).

### Added
- **2025 OOS test**: Run on Jan-Jun 2025 data (genuinely unseen). Result: −6.35%, 7 trades (inconclusive due to sample size).
- **2017-2019 bear market test**: −3.64% vs BTC's −80%. Confirmed drawdown control mechanism functions as designed.
- **Root cause diagnosis**: 2025 OOS failure traced to BTC's EMA stack never aligning (0/634 bars met `price > EMA-21 > EMA-55 > EMA-200`).
- **ATM_TS_FINDINGS.md**: Full document rewritten with validated results, confidence intervals, and honest assessment structure.

### Fixed
- **Date alignment bug** (`Backtester.run()`): Multi-asset equity curves showed 100% drawdowns when mixing crypto (24/7 markets) with US ETFs (market-days-only). Fixed by building a forward-filled price DataFrame via `pd.concat().reindex().ffill()`.

---

## v4 — Multi-Asset Expansion & Validation (2025-06-27)

### Added
- **Multi-asset support**: Added QQQ (NASDAQ), GLD (Gold), USO (Oil), TLT (Bonds) via Yahoo Finance alongside crypto via Binance ccxt.
- **Walk-forward with 6 assets**: All 3 folds valid (14, 14, 22 trades). Avg IS 1.15 → OOS 0.47 Sharpe. 3/3 folds positive OOS returns.
- **95% confidence intervals on win rates**: QQQ's 88% WR across 8 trades has CI of 47–99%, reframed from "confirmed" to "promising."

### Changed
- **Walk-forward reporting**: Added proper void-fold handling (windows < 10 trades flagged).
- **ATM_TS_FINDINGS.md**: Updated validation tables, added confidence intervals, reframed strategy identity.

### Fixed
- **Date alignment between crypto and ETF calendars**: Prices now forward-filled so missing dates for one asset don't cause phantom equity drops.

---

## v3 — Risk Scaling & EMA Optimization (2025-06-27)

### Added
- **Risk scaling analysis**: Tested risk levels from 1% to 15%. Found Sharpe drops from 0.88 (at 1%) to 0.72 (at 7.5%) — higher returns from leverage, not better edge.
- **EMA grid search**: 27 EMA combinations tested. "Optimal" 15/45/180 produced +458% vs default 21/55/200 at +426% (difference within noise at 41 trades).

### Changed
- Default Config updated to `EMA(15/45/180)`, `risk_per_trade=0.075`, `max_position_pct=1.0`, `circuit_breaker=0.50`.

---

## v2 — Ablation Study & Structural Fixes (2025-06-27)

### Added
- **Ablation study**: 7 fixes tested independently against crypto-only Binance-data baseline:
  - C (trend re-entries): +9.77%, 0.265 Sharpe — **best single fix**
  - E (no range mode): +1.41%, 0.130 Sharpe — positive
  - F (no shorts): +2.43%, 0.217 Sharpe — positive
  - C+E+F combo: +36.14%, 0.879 Sharpe — **best combo**

### Changed
- Data source: Yahoo Finance → **Binance ccxt** for crypto intraday data (years of history available)
- Entry logic: crossover-only → **price-position re-entry** (enters during extended trends)

### Removed
- **Range mode**: Disabled for crypto (confirmed negative expectancy across all tests: −$6,746, 14.3% WR)
- **Shorts**: Disabled for crypto (crypto is structurally long-biased: −$7,753 in baseline)

---

## v1 — Original Baseline (Prior to Review)

### Baseline Metrics (Yahoo Finance, 4 assets, EMA 21/55/200, 1% risk)
- Total Return: −5.46%
- Sharpe: −0.37
- Max Drawdown: 5.92%
- Trades: 19
- Score: 12/100 — **LOSER**

### Known Issues (identified retrospectively)
- Range mode: −$6,746 P&L (14 trades, 14.3% WR)
- Shorts: −$7,753 P&L
- Trend mode slightly profitable: +$1,465 (10 trades, 40% WR)
- Only 19 trades across 5 years — statistically meaningless
- No walk-forward validation, no OOS testing, no robustness checks

---

## Unresolved (Cosmetic Only)

- **Redundant ADX check in `partial_stack`** (line 417): `r['adx'] > self.cfg.trend_adx_threshold` is guaranteed true by the outer `if regime == 'trend'` block. Harmless, no behavioral impact.
