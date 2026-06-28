# ATM-TS v2.0 — Local Setup Guide

A step-by-step guide to installing and running the Adaptive Trend-Momentum Trading System on a fresh machine.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Installation](#2-installation)
3. [Verify Everything Works](#3-verify-everything-works)
4. [Run the Full Backtest Pipeline](#4-run-the-full-backtest-pipeline)
5. [Run Paper Trading](#5-run-paper-trading)
6. [Run Live Trading (Binance)](#6-run-live-trading-binance)
7. [Understanding the Output](#7-understanding-the-output)
8. [Configuration Reference](#8-configuration-reference)
9. [Troubleshooting](#9-troubleshooting)
10. [Quick Reference Card](#10-quick-reference-card)

---

## 1. Prerequisites

### Required

| Requirement | Minimum | Notes |
|------------|---------|-------|
| **Python** | 3.8+ | 3.10 or 3.11 recommended. Check with `python3 --version` |
| **pip** | Latest | Package manager. `pip install --upgrade pip` |
| **OS** | Linux, macOS, Windows (WSL) | Windows users should use **WSL2** (Ubuntu 22.04 recommended) |

### Optional

| Software | Why |
|----------|-----|
| **tmux** (Linux/macOS) | Run the paper trader persistently in the background |
| **matplotlib** | Generate equity curve charts (pip will install it) |

---

## 2. Installation

### Step 1: Get the code

```bash
# Option A: Clone from git
git clone <your-repo-url> atm-ts
cd atm-ts

# Option B: Copy the files manually
# Ensure atm_ts.py and any .csv/.md files are in the same directory
```

### Step 2: Create a virtual environment (strongly recommended)

```bash
# Create a virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate       # Linux/macOS
# venv\Scripts\activate        # Windows (Command Prompt)
# source venv/Scripts/activate  # Windows (Git Bash)

# You should see (venv) in your terminal prompt
```

### Step 3: Install dependencies

```bash
# Install everything in one command
pip install yfinance pandas numpy matplotlib ccxt
```

This installs:

| Package | Version | Purpose |
|---------|---------|---------|
| `yfinance` | Latest | Fetch ETF data from Yahoo Finance (QQQ, GLD, USO, EEM) |
| `pandas` | Latest | Data manipulation and analysis |
| `numpy` | Latest | Numerical computing (indicators, statistics) |
| `matplotlib` | Latest | Generate equity curve charts and visualizations |
| `ccxt` | Latest | Fetch crypto data from Binance (BTC-USD, ETH-USD) |

### Step 4: Verify dependencies are installed

```bash
python3 -c "
import yfinance as yf
import pandas as pd
import numpy as np
import ccxt
print('matplotlib:', end=' ')
try:
    import matplotlib
    print('OK')
except ImportError:
    print('optional (charts)')
print('All core dependencies OK')
"
```

---

## 3. Verify Everything Works

### Quick import test

```bash
python3 -c "from atm_ts import Config, Backtester, LiveTrader; print('✓ ATM-TS imports OK')"
```

Expected output:
```
✓ ATM-TS imports OK
```

### Quick smoke test (runs a mini backtest on 1 asset)

```bash
python3 -c "
from atm_ts import Config, Backtester

# Test with 1 crypto asset only (fast data from Binance)
cfg = Config()
cfg.crypto_assets = ['BTC-USD']
cfg.etf_assets = []
cfg.forex_assets = []
cfg.start_date = '2023-06-01'
cfg.end_date = '2024-06-01'

bt = Backtester(cfg)
res = bt.run()

if 'error' in res:
    print('✗ Backtest failed:', res['error'])
else:
    eq = res['equity']
    ret = (eq['equity'].iloc[-1] / cfg.initial_capital - 1) * 100
    trades = len(res['trades'])
    print(f'✓ BTC-only backtest completed: {ret:+.2f}% return, {trades} trades')
"
```

Expected output (numbers will vary):
```
↓ Fetching BTC-USD (1d) from Binance via ccxt...
  ✓ BTC-USD (1d): 366 bars (2023-06-01 → 2024-06-01)
  ...log messages...
  ✓ BTC-only backtest completed: +XX.XX% return, X trades
```

---

## 4. Run the Full Backtest Pipeline

### One command

```bash
python3 atm_ts.py
```

This executes the `main()` function which runs:

1. **Backtest** — 5-year (2019-2024) multi-asset backtest on 6 assets (BTC, ETH, QQQ, GLD, USO, EEM)
2. **Analysis** — Full performance report (Sharpe, drawdown, trade statistics, per-symbol breakdown)
3. **Plot** — Generates `atm_ts_backtest.png` (equity curve chart)
4. **Robustness Test** — Tests 5 parameter variations to detect overfitting
5. **Walk-Forward Validation** — 3 time-based folds with OOS performance
6. **Timeframe Comparison** — 1d vs 4h vs 1h bar intervals
7. **Export** — Saves `atm_ts_trades.csv`, `atm_ts_equity.csv`, `atm_ts_metrics.json`

### Expected runtime

| Step | Time | Notes |
|------|------|-------|
| Data fetching | 10–30 seconds | Depends on network and API rate limits |
| Backtest | 1–5 seconds | CPU-bound |
| Walk-forward | 5–15 seconds | Runs 3 additional backtests |
| Timeframe comparison | 30–90 seconds | Fetches intraday crypto data (4h, 1h) |
| **Total** | **1–3 minutes** | |

### To skip slow steps (timeframe comparison):

```bash
# Edit main() to comment out TimeframeComparison.run(cfg)
# Or just run the backtest directly:
python3 -c "
from atm_ts import Config, Backtester, Analyzer
cfg = Config()
bt = Backtester(cfg)
res = bt.run()
if 'error' not in res:
    a = Analyzer(res['equity'], res['trades'], cfg.initial_capital)
    m = a.metrics()
    a.print_report(m)
    a.plot(m)
"
```

---

## 5. Run Paper Trading

Paper trading simulates trades without using real money. The system fetches live market data and logs every decision it would make.

### Start paper trading (interactive)

```bash
python3 -c "
from atm_ts import Config, LiveTrader

cfg = Config(
    paper_trading=True,        # Simulate fills (no real orders)
    check_interval_seconds=60  # Check for signals every 60 seconds
)
trader = LiveTrader(cfg)
trader.run_loop()
"
```

The paper trader will:

1. Fetch the last 300 days of data for each asset
2. Calculate all indicators
3. Check for exit signals on open positions
4. Apply the ETH/BTC relative strength filter
5. Check for entry signals
6. Log diagnostic information (why signals are or aren't generated)
7. Sleep 60 seconds, then repeat

### Start paper trading (persistent background with tmux)

```bash
# Start a tmux session
tmux new-session -d -s paper-trader

# Run the paper trader inside it
tmux send-keys -t paper-trader 'cd /path/to/atm-ts && python3 -c "
from atm_ts import Config, LiveTrader
cfg = Config(paper_trading=True)
trader = LiveTrader(cfg)
trader.run_loop()
"' Enter

# Watch the output
tmux attach -t paper-trader

# Detach: Ctrl+B, then D
# Stop: Ctrl+C inside tmux, or: tmux kill-session -t paper-trader
```

### Start paper trading (background with nohup)

```bash
nohup python3 -c "
from atm_ts import Config, LiveTrader
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
cfg = Config(paper_trading=True)
trader = LiveTrader(cfg)
trader.run_loop()
" > paper_trader.log 2>&1 &

# Watch the log
tail -f paper_trader.log

# Stop the process
pkill -f "LiveTrader"
```

### What to expect on first run

```
2026-06-28 05:26 [ATM-TS] Starting PAPER trading loop
2026-06-28 05:26 [ATM-TS] Check interval: 60s
2026-06-28 05:26 [ATM-TS] ─── Scan cycle ───
2026-06-28 05:26 [ATM-TS] ↓ Fetching BTC-USD (1d) from Binance via ccxt...
2026-06-28 05:26 [ATM-TS]   ✓ BTC-USD (1d): 250 bars (2025-09-21 → 2026-06-28)
2026-06-28 05:26 [ATM-TS]   BTC-USD no signal — regime=trend, ADX=22, RSI=45, full_stack=True, ...
2026-06-28 05:26 [ATM-TS] ↓ Fetching ETH-USD (1d) from Binance via ccxt...
2026-06-28 05:26 [ATM-TS]   ✓ ETH-USD (1d): 250 bars (2025-09-21 → 2026-06-28)
2026-06-28 05:26 [ATM-TS]   ETH-USD entry skipped — ETH/BTC ratio below 30d MA
```

**Note on ETF data:** The first few scan cycles may show "insufficient data" for QQQ, GLD, USO, and EEM. This is normal — Yahoo Finance's `fetch_recent()` returns exactly 250 trading days, and the system requires ~210 bars for indicator warmup (200-bar EMA + 10). If the market was closed on some of those days due to holidays, you may get fewer than 210 bars and see warnings. This resolves itself over time as more data accumulates, or you can increase the `days` parameter in `fetch_recent()` (in the `scan_and_trade` method) from 250 to 350.

---

## 6. Run Live Trading (Binance)

**⚠️ WARNING: This trades real money. Test with paper trading first for at least 2 weeks.**

### Step 1: Create a Binance API key

1. Log in to [Binance](https://www.binance.com)
2. Go to **API Management** (under Profile → API Management)
3. Create a new API key
4. **Restrict to spot trading only** (disable withdrawals)
5. Save both the API Key and Secret Key securely

### Step 2: Set environment variables

```bash
# Add to your ~/.bashrc or ~/.zshrc for persistence
export BINANCE_API_KEY='your_api_key_here'
export BINANCE_SECRET='your_secret_key_here'

# Or set them for the current session
export BINANCE_API_KEY='your_api_key_here'
export BINANCE_SECRET='your_secret_key_here'
```

### Step 3: Start live trading

```bash
python3 -c "
from atm_ts import Config, LiveTrader

cfg = Config(
    live_mode=True,
    paper_trading=False,      # REAL ORDERS on Binance
    check_interval_seconds=60  # Check every 60 seconds
)
trader = LiveTrader(cfg)
trader.run_loop()
"
```

**What happens:** The system will:
- Connect to Binance via ccxt using your API keys
- Fetch live market data every 60 seconds
- Place **real market orders** (BUY/SELL) on Binance spot market
- Only trade crypto assets (BTC-USD → BTC/USDT, ETH-USD → ETH/USDT)
- ETFs (QQQ, GLD, USO, EEM) are skipped in live mode — the system only trades crypto via Binance

### Important live trading notes

| Concern | Detail |
|---------|--------|
| **Order type** | Market orders only (no limit orders) |
| **Minimum size** | Binance has minimum notional ($10–$100 depending on asset) |
| **Slippage** | Market orders have slippage; the system's 0.05% estimate is optimistic for volatile assets |
| **ETH/BTC filter** | Still applies — ETH won't trade when underperforming BTC |
| **Startup** | First scan fetches 300 days of history; subsequent scans only check latest bar |
| **Logging** | Everything is logged to stdout — redirect to a file with `>` for persistence |

---

## 7. Understanding the Output

### Backtest report legend

```
══════════════════════════════════════════════════════════════════
  ATM-TS  ·  BACKTEST PERFORMANCE REPORT
══════════════════════════════════════════════════════════════════

  ── Returns ──
  Total Return:              +207.62 %
  Annualized Return:          +24.52 %
  Sharpe Ratio:                   1.02
  Sortino Ratio:                  1.56
  Calmar Ratio:                  12.34

  ── Risk ──
  Max Drawdown:                 15.11 %

  ── Trade Statistics ──
  Total Trades:                    77
  Wins / Losses:               39 / 38
  Win Rate:                     50.65 %
  Avg Win:                      +9.46 %
  Avg Loss:                     -5.38 %
  Profit Factor:                  2.26
```

| Metric | What to look for |
|--------|------------------|
| **Sharpe Ratio** | > 1.0 = good, > 0.5 = acceptable, < 0.5 = weak |
| **Max Drawdown** | < 15% = excellent, < 25% = acceptable |
| **Profit Factor** | > 2.0 = strong, > 1.5 = good, < 1.0 = losing |
| **Win Rate** | 45–55% is normal for trend-following |
| **Total Trades** | > 50 for statistical significance |

### Walk-forward summary

```
  Fold                  IS Sharpe  OOS Sharpe  OOS Ret%   OOS DD%  Trades   WR%      PF
  ──────────────────────────────────────────────────────────────────────────────────────
  2021-06 to 2022-06       0.79       0.42      +11.54     12.82     14     57%    1.75
  2022-06 to 2023-06       1.38       0.28      +14.22     15.26     14     50%    1.50
  2023-06 to 2024-06       1.29       0.72      +18.09     10.53     22     59%    1.88
```

| What | Good sign |
|------|-----------|
| All folds have ≥ 10 trades | ✅ Statistical validity |
| OOS Sharpe > 0 on most folds | ✅ Edge holds out of sample |
| Sharpe decay < 0.70 | ✅ Not severely overfit |

### Diagnostic logging (paper trader)

```
2026-06-28 05:26 [ATM-TS]   BTC-USD no signal —
    regime=trend, ADX=22, RSI=45,
    full_stack=True, partial_stack=False,
    EMA200_slope=12, price_vs_EMA21=1.023,
    bullish_cross=False, latest_bar_match=False
```

| Field | Meaning |
|-------|---------|
| `regime` | Current market regime (trend/neutral/range) |
| `ADX` | Trend strength (25+ = trending) |
| `RSI` | Relative strength (70+ = overbought, no entry) |
| `full_stack` | `price > EMA21 > EMA55` (tier 1 condition) |
| `partial_stack` | Pullback condition (price < EMA21 but > EMA55, ADX>25, EMA200 rising) |
| `price_vs_EMA21` | 1.000 = price at EMA21, > 1 = above, < 1 = below |
| `bullish_cross` | EMA21 just crossed above EMA55 |
| `latest_bar_match` | Whether the last generated signal matches the latest bar |

---

## 8. Configuration Reference

All settings are in the `Config` dataclass at the top of `atm_ts.py`. Here's what each setting does:

### Asset Configuration

```python
crypto_assets: list = ['BTC-USD', 'ETH-USD']    # Crypto via Binance ccxt
etf_assets: list = ['QQQ', 'GLD', 'USO', 'EEM'] # ETFs via Yahoo Finance
# TLT replaced with EEM (Emerging Markets) — better trend following properties
forex_assets: list = []                          # Spot FX (requires broker API)
```

**To change which assets are traded:** Edit these lists. Any Yahoo Finance ticker should work.

### Backtest Period

```python
start_date: str = '2019-06-01'    # YYYY-MM-DD format
end_date: str = '2024-06-01'
initial_capital: float = 100_000.0  # Starting portfolio value ($)
```

### Indicator Periods

```python
fast_ema: int = 21    # EMA-21 (fast trend)
slow_ema: int = 55    # EMA-55 (slow trend)
trend_ema: int = 200  # EMA-200 (major trend — still calculated for slope, not required for entry)
atr_period: int = 14  # ATR lookback
adx_period: int = 14  # ADX lookback
rsi_period: int = 14  # RSI lookback
```

### Risk Management

```python
risk_per_trade: float = 0.03       # 3% of equity risked per trade (production default)
max_positions: int = 5             # Maximum concurrent positions
atr_stop_mult: float = 2.5         # Initial stop = entry ± 2.5×ATR
atr_trail_mult: float = 3.0        # Trail stop = peak ± 3.0×ATR
max_drawdown_circuit_breaker: float = 0.20  # 20% DD halt
max_position_pct: float = 0.50     # Max 50% of portfolio in one position
```

**High-octane mode** (more aggressive):
```python
risk_per_trade = 0.075    # 7.5% risk per trade
max_position_pct = 1.0    # No position size cap
max_drawdown_circuit_breaker = 0.30  # 30% DD halt
```

### Timeframe

```python
timeframe: str = '1d'  # Daily bars. Options: '1d', '4h', '1h'
```

### Transaction Costs

```python
crypto_commission: float = 0.001  # 0.10% — Binance spot taker fee
crypto_slippage: float = 0.0005   # 0.05% — market order slippage estimate
```

### Live Trading

```python
live_mode: bool = False           # Set to True for real orders
paper_trading: bool = True        # Simulate fills (default for safety)
check_interval_seconds: int = 60  # Seconds between scan cycles
```

### Customizing via code (examples)

```python
from atm_ts import Config

# 3-month test with reduced assets
cfg = Config(
    start_date='2024-01-01',
    end_date='2024-04-01',
    crypto_assets=['BTC-USD'],
    etf_assets=['QQQ', 'GLD'],
    initial_capital=10_000,
)

# High-octane mode
cfg_ho = Config(
    risk_per_trade=0.075,
    max_position_pct=1.0,
    max_drawdown_circuit_breaker=0.30,
)

# 4-hour timeframe with few assets
cfg_4h = Config(
    crypto_assets=['BTC-USD'],
    etf_assets=[],
    timeframe='4h',
)
```

---

## 9. Troubleshooting

### "No module named yfinance/pandas/numpy/matplotlib/ccxt"

```bash
# Make sure you're in the virtual environment
source venv/bin/activate

# Reinstall dependencies
pip install yfinance pandas numpy matplotlib ccxt
```

### "ccxt fetch failed for BTC-USD"

Cause: Binance API rate limiting or network issue.

```bash
# Test connectivity
python3 -c "import ccxt; ex = ccxt.binance(); ticker = ex.fetch_ticker('BTC/USDT'); print('BTC:', ticker['last'])"
```

If this fails, you may need a proxy or VPN (Binance is restricted in some regions).

### "No data for QQQ" or "Insufficient data"

Cause: Yahoo Finance rate limiting. The system retries 3 times automatically.

Solution: Wait a few minutes and try again. Yahoo Finance rate-limits to ~5 requests per second per IP. If running multiple tests in quick succession, add a delay:

```python
import time
time.sleep(5)  # Wait between test runs
```

### "No data for ETH-USD via ccxt" → try USDT pair

The code converts `ETH-USD` to `ETH/USDT` for Binance. If you add a new crypto asset, make sure it has a USDT pair on Binance (e.g., `SOL-USD` → `SOL/USDT`).

### Paper trader shows "insufficient data" for ETFs on first run

This is expected if you're running near a market holiday weekend. Yahoo Finance returns exactly the number of trading days requested (250). If some are holidays, you may get fewer than 210 bars (required for 200-bar EMA warmup + 10 buffer).

**Fix:** Increase the `days` parameter in `fetch_recent()`:
- In `atm_ts.py`, find the `scan_and_trade()` method of the `LiveTrader` class
- Change `days=300` to `days=400` on the line:
  ```python
  df = self.dm.fetch_recent(symbol, days=300)
  ```

### "atm_ts_backtest.png" not generated

matplotlib is not installed. Either:

```bash
pip install matplotlib
```

Or accept that charts won't be generated (the console report will still work).

### Walk-forward shows "VOID" for all folds

Cause: Too few trades to reach the 10-trade minimum. This can happen when:
- Testing with only 1-2 assets
- Testing a very short time period (< 1 year)
- Running during non-trending market conditions

**Solution:** Use the default 6-asset configuration or extend the test period.

### Settings not taking effect

Make sure you're modifying the `Config()` instance after creating it, or passing parameters to the constructor:

```python
# Correct way 1: pass to constructor
cfg = Config(start_date='2020-01-01')

# Correct way 2: modify after creation
cfg = Config()
cfg.start_date = '2020-01-01'
```

### "from atm_ts import ..." fails

You need to run the command from the same directory as `atm_ts.py`, or add it to your `PYTHONPATH`:

```bash
cd /path/to/atm-ts/
python3 -c "from atm_ts import Config; print('OK')"

# OR
export PYTHONPATH=/path/to/atm-ts/:$PYTHONPATH
python3 -c "from atm_ts import Config; print('OK')"
```

---

## 10. Quick Reference Card

### One-time setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install yfinance pandas numpy matplotlib ccxt
```

### Run backtest

```bash
source venv/bin/activate   # If not already in venv
python3 atm_ts.py
```

### Run paper trader

```bash
source venv/bin/activate
python3 -c "
from atm_ts import Config, LiveTrader
cfg = Config(paper_trading=True, check_interval_seconds=60)
LiveTrader(cfg).run_loop()
"
```

### Run paper trader (persistent with tmux)

```bash
source venv/bin/activate
tmux new-session -d -s trader \
  'python3 -c "from atm_ts import Config, LiveTrader; LiveTrader(Config(paper_trading=True)).run_loop()"'
tmux attach -t trader
# Detach: Ctrl+B, D
```

### Run live (Binance) — DANGER: real money

```bash
source venv/bin/activate
export BINANCE_API_KEY='your_key'
export BINANCE_SECRET='your_secret'
python3 -c "
from atm_ts import Config, LiveTrader
cfg = Config(live_mode=True, paper_trading=False, check_interval_seconds=60)
LiveTrader(cfg).run_loop()
"
```

### Quick parameter test

```bash
source venv/bin/activate
python3 -c "
from atm_ts import Config, Backtester, Analyzer
cfg = Config(risk_per_trade=0.03)  # Try 0.05, 0.075 for comparison
bt = Backtester(cfg)
res = bt.run()
if 'error' not in res:
    a = Analyzer(res['equity'], res['trades'], cfg.initial_capital)
    m = a.metrics()
    a.print_report(m)
"
```

---

> **Remember:** This is a systematic trading system. Results from historical backtesting do not guarantee future performance. Always paper trade before trading with real capital.
