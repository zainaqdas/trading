# ATM-TS Session Context — June 28, 2026

This file captures the complete development and review history of ATM-TS v2.0 so a fresh session can resume with full context.

---

## Project Overview

**ATM-TS v2.0** — Adaptive Trend-Momentum Trading System. A long-only trend-following system for crypto and ETFs with strong capital preservation in bear markets.

**Core identity (current, after 9 rounds of development):**
> A long-only trend-following system with strong capital preservation in bear markets, modest positive expectancy in trending markets, and no edge in ranging markets.

**Defensible use case:** Managed multi-asset exposure that keeps you out of major drawdowns while capturing a reasonable portion of bull trends.

---

## Development Journey — 9 Rounds

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
- Added QQQ, GLD, USO, TLT via Yahoo Finance
- **Critical bug found**: 100% drawdown from date misalignment (crypto 24/7 vs ETF market-days-only)
- **Fix**: Forward-filled price DataFrame via `pd.concat().reindex().ffill()`
- Walk-forward with 6 assets: 3/3 folds valid

### Round 4 — Honest Validation & Walk-Forward Rewrite
- Risk defaults reverted: 3% risk, 50% position cap, 30% circuit breaker
- EMAs reverted to 21/55/200 (grid search confirmed as noise at 41 trades)
- Walk-forward rewritten: time-based folds with fixed default params
- **2025 OOS test**: −1.64% (crypto-only) — failed to capture BTC's +60% rally
- **2017-2019 bear market test**: −3.64% vs BTC's −80% — drawdown control confirmed

### Round 5 — Root Cause Diagnosis & Three Fixes
- **Root cause**: BTC's EMA stack never aligned — 0/634 bars met entry condition
- **Fix 1**: Two-tier EMA entry (full_stack + partial_stack with ADX)
- **Fix 2**: ETH/BTC relative strength filter
- **Fix 3**: Circuit breaker tightened to 20%
- Post-fix: +148%, 0.898 Sharpe, 14.3% DD

### Rounds 6-8 — LiveTrader Parity, Bug Fixes, Peak Tracking
- Duplicate methods removed, RSI filter fixed for ALL entries
- ETH/BTC filter in LiveTrader: exits handled BEFORE filter (critical)
- `_fetch_cache` added, `_eth_btc_strong()` inlined
- `self.peak` tracks total portfolio equity (not cash)

### Round 9 — Final: Relaxed Entry + Pullback Redesign + Live Fixes (June 2026)

**Three experiments over the session:**
| Experiment | Result | Verdict |
|---|---|---|
| ADX threshold 20 | +77%, 0.62 Sharpe (worse) | ❌ REJECTED |
| Relaxed full_stack (no EMA-200) | +156%, 0.92 Sharpe | ✅ ADOPTED |
| Pullback redesign (partial_stack) | **+174%, 0.98 Sharpe, 15% DD** | ✅ ADOPTED |

**The pullback redesign:** After relaxing `full_stack`, the old `partial_stack` (which checked `price > EMA-21 > EMA-55`) was a subset of `full_stack` — dead code. External code review confirmed this. Redesigned it to catch genuine pullback entries: price dips below EMA-21 but holds above EMA-55 during strong trends. This is the final configuration.

**Additional fixes from review:**
- `fetch_intraday_ccxt()`: Added optional `since` parameter. When provided, `end_ts` defaults to `datetime.now()` instead of `config.end_date`. Fixes live trader silently returning no data.
- `fetch_recent()`: Now passes `since=start` for crypto, fetching only ~300 days instead of full 5-year history.

**Final results (6 assets, 2019-2024):**
- +174.07%, 0.98 Sharpe, 15.11% DD, 77 trades, 2.26 PF
- Walk-forward: 2/3 folds positive OOS, all folds have sufficient trades
- 2025 H2: −1.06%, 1 trade (dormancy not fully solved)
- Exit reasons: 46 ATR trailing, 18 RSI overbought, 9 hard stop, 3 bearish cross

---

## Current Code State

### Files (all in project root `~/`)
| File | Description | Status |
|------|-------------|--------|
| `atm_ts.py` | Main trading system | **Production-ready** |
| `ATM_TS_FINDINGS.md` | Research & findings document | Updated |
| `CHANGELOG.md` | Version history across 9 rounds | Updated |
| `CONTEXT.md` | This file — session context | Updated |
| `README.md` | Project documentation | Updated |

### Key Code Architecture
- **`Config`** — Dataclass with all parameters. `crypto_assets`, `etf_assets`, `forex_assets`.
- **`DataManager`** — Fetches from Binance ccxt (crypto) and Yahoo Finance (ETFs). Caches results.
- **`Indicators`** — EMA, RSI, ATR, ADX, Bollinger Bands. Zero look-ahead.
- **`Strategy`** — Two-tier entry: relaxed full_stack (price > EMA-21 > EMA-55) OR partial_stack (price > EMA-21 > EMA-55, ADX > 25, EMA-200 rising). RSI < 70 required.
- **`RiskManager`** — Equity-based position sizing, ATR trailing stops, circuit breaker at 20%.
- **`Backtester`** — Event-driven loop with forward-filled multi-asset prices.
- **`LiveTrader`** — Paper/live trading with diagnostic logging and ETH/BTC filter.
- **`WalkForwardValidator`** — Time-based folds with fixed params, min 10 trades filter.

### Validation Results (Final, 6 assets)
| Test | Result |
|------|--------|
| Full period (2019-2024) | **+174%, 0.98 Sharpe, 15.11% DD, 77 trades, PF 2.26** |
| Walk-forward | 0.83→0.32 avg OOS Sharpe, 2/3 folds positive OOS |
| 2025 OOS (Jun 2024-Jun 2025) | −2.92%, 9 trades (inconclusive) |
| 2025 H2 (Jul-Dec 2025) | −1.06%, 1 trade (near-dormant) |
| 2017-2019 bear market | −3.64%, 16 trades (capital preservation confirmed) |

### Unresolved (Cosmetic Only)
- Redundant ADX check in `partial_stack` (guaranteed true by regime gate — `partial_stack` is inside `if regime == 'trend'`). No behavioral impact.

---

## How to Start Paper Trading

```python
from atm_ts import Config, LiveTrader

cfg = Config(paper_trading=True)  # Paper mode by default
trader = LiveTrader(cfg)
trader.run_loop()  # Continuous scan cycle with diagnostic logging
```

The diagnostic logging will log WHY signals are or aren't generated on every scan cycle, including `regime`, `ADX`, `RSI`, `relaxed_stack`, `pullback_stack`, `EMA200_slope`, price vs EMA-21, and bullish cross status.

---

## Recommended Next Steps (from review)

1. **Replace TLT with EEM** — TLT has 25% WR across 4 trades, EEM is genuinely uncorrelated
2. **Deploy paper trader** on 2026 live data for at least one complete market cycle
3. **Compare live diagnostic logs** against backtest predictions — the only remaining validation that matters
