# ATM-TS Session Context — June 27, 2026

This file captures the complete development and review history of ATM-TS v2.0 so a fresh session can resume with full context.

---

## Project Overview

**ATM-TS v2.0** — Adaptive Trend-Momentum Trading System. A long-only trend-following system for crypto and ETFs with strong capital preservation in bear markets.

**Core identity (final, after 8 review rounds):**
> A long-only trend-following system with strong capital preservation in bear markets, modest positive expectancy in trending markets, and no edge in ranging markets.

**Defensible use case:** Managed multi-asset exposure that keeps you out of major drawdowns while capturing a reasonable portion of bull trends.

---

## Development Journey — 8 Review Rounds

### Baseline (Pre-Review)
- Yahoo Finance data, 4 assets (BTC, ETH, EURUSD, GBPUSD)
- EMA(21/55/200), 1% risk, range mode + shorts enabled
- Result: **−5.46% return**, Sharpe −0.37 — LOSER
- Key problems: range mode negative expectancy (−$6,746), shorts had no edge (−$7,753)

### Round 1 — Ablation Study & Structural Fixes
- Ablation tested 7 fixes independently
- Best combo (C+E+F): trend re-entries + no range mode + no shorts = **+36.14%**
- Data source changed from Yahoo Finance to Binance ccxt for crypto
- Entry logic changed from crossover-only to price-position re-entry

### Round 2 — Risk Scaling & EMA Optimization
- Risk levels 1%–15% tested: Sharpe dropped from 0.88 to 0.72 as risk increased
- EMA grid search (27 combinations): 15/45/180 "optimal" but noise at 41 trades
- Defaults temporarily set to EMA(15/45/180), 7.5% risk, 100% position cap, 50% circuit breaker

### Round 3 — Multi-Asset & Drawdown Bug Fix
- Added QQQ, GLD, USO, TLT (ETFs instead of futures to avoid rollover artifacts)
- **Critical bug found**: 100% drawdown from date misalignment (crypto 24/7 vs ETF market-days-only)
- **Fix**: Forward-filled price DataFrame via `pd.concat().reindex().ffill()`
- Walk-forward with 6 assets: 3/3 folds valid, 0.998 Sharpe, 16.3% DD

### Round 4 — Honest Validation & Walk-Forward Rewrite
- Risk defaults reverted: 3% risk, 50% position cap, 30% circuit breaker
- EMAs reverted to 21/55/200 (grid search confirmed as noise)
- Walk-forward rewritten: time-based folds with fixed default params (no per-window optimization)
- **2025 OOS test**: −1.64% (crypto-only) — failed to capture BTC's +60% rally
- **2017-2019 bear market test**: −3.64% vs BTC's −80% — drawdown control confirmed
- ATM_TS_FINDINGS.md created with honest assessments

### Round 5 — Root Cause Diagnosis & Three Fixes
- **Root cause**: BTC's EMA stack never aligned — 0/634 bars met entry condition
- **Fix 1**: Two-tier EMA entry (full_stack OR partial_stack with ADX + EMA-200 slope)
- **Fix 2**: ETH/BTC relative strength filter (skip ETH when underperforming BTC)
- **Fix 3**: Circuit breaker tightened to 20%
- Post-fix results: 148% return (was 181%), 14.3% DD (was 16.3%), WF decay 0.63 (was 0.68)
- 2025 OOS still negative (−2.53%) but inconclusive (10 trades)

### Round 6 — LiveTrader Parity
- Duplicate `fetch()` method removed from DataManager
- RSI filter fixed to apply to ALL entries including crossovers
- ETH/BTC filter replicated in LiveTrader
- Diagnostic signal logging added

### Round 7 — LiveTrader Bug Fixes
- Duplicate `is_crypto()` removed
- **Critical fix**: ETH/BTC filter was skipping exit checks — restructured to handle exits BEFORE filter
- `_fetch_cache` added to eliminate redundant HTTP calls
- `_eth_btc_strong()` helper removed (logic inlined with cached data)

### Round 8 — Final Peak Tracking Fix
- `self.peak` now uses total portfolio equity (not just cash)
- BTC-first ordering dependency documented
- Document circuit breaker value corrected to 0.20

---

## Current Code State

### Files (all in project root `~/`)
| File | Description | Status |
|------|-------------|--------|
| `atm_ts.py` | Main trading system | **Production-ready** |
| `ATM_TS_FINDINGS.md` | Research & findings document | Complete |
| `CHANGELOG.md` | Version history across 8 rounds | Complete |
| `CONTEXT.md` | This file — session context | Complete |
| `README.md` | Project documentation | Complete |

### Key Code Architecture
- **`Config`** — Dataclass with all parameters. `risk_per_trade=0.03`, `max_position_pct=0.50`, `max_drawdown_circuit_breaker=0.20`
- **`DataManager`** — Fetches data from Binance (crypto via ccxt) and Yahoo Finance (ETFs). Caches results.
- **`Indicators`** — EMA, RSI, ATR, ADX, Bollinger Bands. Zero look-ahead.
- **`Strategy`** — Two-tier entry: full_stack (price > EMA-21 > EMA-55 > EMA-200) OR partial_stack (price > EMA-21 > EMA-55, ADX > 25, EMA-200 rising). RSI < 70 required for all entries.
- **`RiskManager`** — Position sizing (equity-based compounding), ATR trailing stops, circuit breaker at 20%.
- **`Backtester`** — Event-driven loop with forward-filled prices for multi-asset alignment.
- **`LiveTrader`** — Paper/live trading with diagnostic logging, ETH/BTC filter, same logic as backtester.
- **`WalkForwardValidator`** — Time-based folds with fixed params, minimum 10-trade filter.

### Validation Results (Post-Fix, 6 assets)
| Test | Result |
|------|--------|
| Full period (2019-2024) | +148%, 0.898 Sharpe, 14.3% DD, 70 trades, PF 2.18 |
| Walk-forward | 1.03→0.40 Sharpe, decay 0.63, 2/3 folds positive OOS |
| 2025 OOS | −2.53%, 10 trades (inconclusive) |
| 2017-2019 bear market | −3.64%, 16 trades (capital preservation confirmed) |

### Unresolved (Cosmetic Only)
- Redundant ADX check in `partial_stack` (guaranteed true by regime gate). No behavioral impact.

---

## How to Start Paper Trading

```python
from atm_ts import Config, LiveTrader

cfg = Config(paper_trading=True)  # Paper mode by default
trader = LiveTrader(cfg)
trader.run_loop()  # Continuous scan cycle with diagnostic logging
```

The diagnostic logging will log WHY signals are or aren't generated on every scan cycle, including `regime`, `ADX`, `RSI`, `full_stack`, `partial_stack`, `EMA200_slope`, price vs EMA-21, and bullish cross status.

---

## Recommended Next Steps (from review)

1. **Run 2025 H2 (Jul-Dec 2025) OOS test** with 6 assets and all fixes — last remaining validation
2. **Replace TLT with EEM** — TLT had only 2 trades (0% WR), EEM is genuinely uncorrelated
3. **Deploy paper trader** on 2026 live data for at least one complete market cycle
4. **Compare live diagnostic logs** against backtest predictions — the only remaining validation that matters
