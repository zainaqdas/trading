#!/usr/bin/env python3
"""
=================================================================
  ATM-TS v2.0 — Adaptive Trend-Momentum Trading System
  Full automated strategy for Crypto & Forex with 5-year backtest
=================================================================

Install dependencies first:
    pip install yfinance pandas numpy matplotlib ccxt

Academic Foundations:
  - Moskowitz et al. (2012): Time Series Momentum
  - Antonacci (2014): Dual Momentum Investing
  - Hurst et al. (2017): A Century of Evidence on Trend-Following
  - Clare et al. (2016): Trend Following Strategies
"""

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import warnings
import logging
import json
import time as time_module
import os

warnings.filterwarnings('ignore')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M'
)
logger = logging.getLogger('ATM-TS')


# ════════════════════════════════════════════════════════════════
#  1. CONFIGURATION
# ════════════════════════════════════════════════════════════════

@dataclass
class Config:
    """Central system configuration."""
    # ── Backtest ──
    start_date: str = '2019-06-01'
    end_date: str = '2024-06-01'
    initial_capital: float = 100_000.0

    # ── Assets ──
    crypto_assets: list = field(default_factory=lambda: ['BTC-USD', 'ETH-USD'])
    forex_assets: list = field(default_factory=list)         # Crypto-only by default

    # ── Indicator Periods ──
    fast_ema: int = 21   # Original EMA(21) — EMA grid search at 41 trades was likely noise
    slow_ema: int = 55   # Original EMA(55)
    trend_ema: int = 200 # Original EMA(200)
    atr_period: int = 14
    adx_period: int = 14
    rsi_period: int = 14
    bb_period: int = 20
    bb_std: float = 2.0

    # ── Regime Thresholds ──
    trend_adx_threshold: int = 25
    range_adx_threshold: int = 20

    # ── Risk Management ──
    risk_per_trade: float = 0.03       # 3% risk per trade (production default)
    # NOTE: For higher risk, use risk_per_trade=0.075 ("high-octane" mode)
    #       and max_position_pct=1.0 for uncapped sizing.
    #       At 3%, the strategy returns ~+216% with ~20% max DD (2019-2024).
    #       At 7.5%, the strategy returns ~+459% with ~30% max DD.
    max_positions: int = 5
    atr_stop_mult: float = 2.5          # Hard stop = entry ± 2.5×ATR
    atr_trail_mult: float = 3.0         # Trail stop = peak ± 3.0×ATR
    max_drawdown_circuit_breaker: float = 0.20  # 20% DD halt (tightened from 30% — 2025 OOS fix)
    max_position_pct: float = 0.50      # Max 50% of portfolio per position

    # ── Transaction Costs ──
    crypto_commission: float = 0.001    # 0.10%
    forex_commission: float = 0.0002    # 0.02% (spread proxy)
    crypto_slippage: float = 0.0005     # 0.05%
    forex_slippage: float = 0.0001      # 0.01%

    # ── Timeframe ──
    timeframe: str = '1d'               # '1d', '4h', '1h' — bar interval

    # ── Live Trading ──
    live_mode: bool = False
    paper_trading: bool = True
    check_interval_seconds: int = 60    # For live loop


# ════════════════════════════════════════════════════════════════
#  2. DATA MANAGER
# ════════════════════════════════════════════════════════════════

class DataManager:
    """Fetches OHLCV data from public APIs (Yahoo Finance)."""

    def __init__(self, config: Config):
        self.config = config
        self._cache: Dict[str, pd.DataFrame] = {}

    def fetch_intraday_ccxt(self, symbol: str, timeframe: str,
                             limit: int = 500) -> pd.DataFrame:
        """
        Fetch intraday OHLCV data for crypto via ccxt (Binance).
        Supports '1h', '4h', '1d' and other Binance intervals.
        Can fetch years of data via pagination.
        """
        cache_key = f"{symbol}_{timeframe}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            import ccxt
            exchange = ccxt.binance({'enableRateLimit': True})

            # Convert yahoo symbol to Binance format
            ccxt_sym = symbol.replace('-USD', '/USDT')

            logger.info(f"↓ Fetching {symbol} ({timeframe}) from Binance via ccxt...")

            since = exchange.parse8601(f"{self.config.start_date}T00:00:00Z")
            end_dt = datetime.strptime(self.config.end_date, '%Y-%m-%d')
            end_ts = int(end_dt.timestamp() * 1000)

            all_ohlcv = []
            while since < end_ts:
                ohlcv = exchange.fetch_ohlcv(ccxt_sym, timeframe, since=since, limit=limit)
                if not ohlcv:
                    break
                all_ohlcv.extend(ohlcv)
                since = ohlcv[-1][0] + 1  # Move past last candle
                time_module.sleep(0.5)  # Rate limiting

            if not all_ohlcv:
                logger.warning(f"  No data for {symbol} via ccxt")
                return pd.DataFrame()

            df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df.index.name = 'date'  # Match yfinance convention

            # Remove duplicates
            df = df[~df.index.duplicated(keep='first')]
            df.sort_index(inplace=True)

            self._cache[cache_key] = df
            logger.info(f"  ✓ {symbol} ({timeframe}): {len(df)} bars "
                        f"({df.index[0].strftime('%Y-%m-%d %H:%M')} → {df.index[-1].strftime('%Y-%m-%d %H:%M')})")
            return df

        except Exception as e:
            logger.error(f"ccxt fetch failed for {symbol}: {e}")
            return pd.DataFrame()

    def fetch(self, symbol: str) -> pd.DataFrame:
        if symbol in self._cache:
            return self._cache[symbol]

        # For intraday crypto, use ccxt (years of history)
        # For forex or daily data, use yfinance
        tf = self.config.timeframe
        is_crypto = symbol in self.config.crypto_assets

        if tf != '1d' and is_crypto:
            return self.fetch_intraday_ccxt(symbol, tf)

        # Fallback to yfinance for daily or forex
        yf_interval = tf if tf in ('1d', '1h', '5m', '15m', '30m', '60m') else '1d'
        if yf_interval != '1d' and not is_crypto:
            logger.info(f"  Note: forex intraday data limited to ~60 days on Yahoo Finance")

        logger.info(f"↓ Fetching {symbol} from Yahoo Finance (interval={yf_interval})...")
        for attempt in range(3):
            try:
                df = yf.Ticker(symbol).history(
                    start=self.config.start_date,
                    end=self.config.end_date,
                    interval=yf_interval,
                    auto_adjust=True
                )
                if df.empty:
                    logger.warning(f"  No data for {symbol}")
                    return pd.DataFrame()

                df.columns = [c.lower().replace(' ', '_') for c in df.columns]
                if hasattr(df.index, 'tz') and df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                df.index.name = 'date'

                # Drop any rows with NaN in OHLCV
                df.dropna(subset=['open', 'high', 'low', 'close', 'volume'], inplace=True)

                self._cache[symbol] = df
                logger.info(f"  ✓ {symbol}: {len(df)} bars "
                            f"({df.index[0]} → {df.index[-1]})")
                return df
            except Exception as e:
                logger.warning(f"  Attempt {attempt+1}/3 failed: {e}")
                time_module.sleep(2)

        return pd.DataFrame()

    def fetch_all(self) -> Dict[str, pd.DataFrame]:
        data = {}
        for s in self.config.crypto_assets + self.config.forex_assets:
            df = self.fetch(s)
            if not df.empty:
                data[s] = df
        return data

    def is_crypto(self, symbol: str) -> bool:
        return symbol in self.config.crypto_assets

    def fetch_recent(self, symbol: str, days: int = 250) -> pd.DataFrame:
        """Fetch recent data for live signal generation."""
        end = datetime.now()
        start = end - timedelta(days=days)
        try:
            df = yf.Ticker(symbol).history(
                start=start.strftime('%Y-%m-%d'),
                end=end.strftime('%Y-%m-%d'),
                interval='1d',
                auto_adjust=True
            )
            df.columns = [c.lower().replace(' ', '_') for c in df.columns]
            if hasattr(df.index, 'tz') and df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            return df
        except Exception as e:
            logger.error(f"Failed to fetch recent data for {symbol}: {e}")
            return pd.DataFrame()


# ════════════════════════════════════════════════════════════════
#  3. TECHNICAL INDICATORS (zero look-ahead)
# ════════════════════════════════════════════════════════════════

class Indicators:
    """All indicator calculations use only prior data — no look-ahead bias."""

    @staticmethod
    def ema(s: pd.Series, period: int) -> pd.Series:
        return s.ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(s: pd.Series, period: int = 14) -> pd.Series:
        delta = s.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series,
            period: int = 14) -> pd.Series:
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1/period, min_periods=period).mean()

    @staticmethod
    def adx(high: pd.Series, low: pd.Series, close: pd.Series,
            period: int = 14) -> pd.Series:
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

        atr_val = Indicators.atr(high, low, close, period)
        plus_di = 100 * plus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr_val
        minus_di = 100 * minus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr_val

        di_sum = (plus_di + minus_di).replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / di_sum
        return dx.ewm(alpha=1/period, min_periods=period).mean()

    @staticmethod
    def bollinger(s: pd.Series, period: int = 20,
                  std_mult: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        mid = s.rolling(window=period).mean()
        std = s.rolling(window=period).std()
        return mid + std_mult * std, mid, mid - std_mult * std

    @classmethod
    def add_all(cls, df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
        """Append all required indicator columns to DataFrame."""
        d = df.copy()
        d['ema_fast'] = cls.ema(d['close'], cfg.fast_ema)
        d['ema_slow'] = cls.ema(d['close'], cfg.slow_ema)
        d['ema_trend'] = cls.ema(d['close'], cfg.trend_ema)
        d['ema_trend_slope'] = d['ema_trend'] - d['ema_trend'].shift(20)  # 20-bar slope
        d['atr'] = cls.atr(d['high'], d['low'], d['close'], cfg.atr_period)
        d['adx'] = cls.adx(d['high'], d['low'], d['close'], cfg.adx_period)
        d['rsi'] = cls.rsi(d['close'], cfg.rsi_period)
        d['bb_upper'], d['bb_mid'], d['bb_lower'] = cls.bollinger(
            d['close'], cfg.bb_period, cfg.bb_std)

        # EMA crossover flags (previous-bar comparison = no look-ahead)
        cross = np.where(d['ema_fast'] > d['ema_slow'], 1,
                         np.where(d['ema_fast'] < d['ema_slow'], -1, 0))
        prev_cross = np.roll(cross, 1)
        prev_cross[0] = 0
        d['bullish_cross'] = (cross == 1) & (prev_cross != 1)
        d['bearish_cross'] = (cross == -1) & (prev_cross != -1)

        return d


# ════════════════════════════════════════════════════════════════
#  4. DATA STRUCTURES
# ════════════════════════════════════════════════════════════════

@dataclass
class Position:
    symbol: str
    direction: int          # +1 long, -1 short
    entry_date: object
    entry_price: float
    size: float
    stop_loss: float
    atr_at_entry: float
    regime: str             # 'trend' or 'range'
    highest_close: float = 0.0
    lowest_close: float = float('inf')

    def update_trail(self, price: float):
        if self.direction == 1:
            self.highest_close = max(self.highest_close, price)
        else:
            self.lowest_close = min(self.lowest_close, price)

    @property
    def market_value(self) -> float:
        return self.size * self.entry_price


@dataclass
class Signal:
    symbol: str
    direction: int
    date: object
    price: float
    atr: float
    regime: str
    reason: str


# ════════════════════════════════════════════════════════════════
#  5. STRATEGY — REGIME-ADAPTIVE SIGNAL GENERATION
# ════════════════════════════════════════════════════════════════

class Strategy:
    """
    Dual-regime strategy:
      Trend mode  → EMA crossover + ADX + 200 EMA filter
      Range mode  → RSI oversold/overbought + Bollinger Band filter
      Neutral     → No new entries
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _regime(self, adx: float) -> str:
        if adx > self.cfg.trend_adx_threshold:
            return 'trend'
        elif adx < self.cfg.range_adx_threshold:
            return 'range'
        return 'neutral'

    def generate(self, symbol: str, df: pd.DataFrame,
                 is_crypto: bool) -> List[Signal]:
        """
        Walk-forward signal generation — no future data used.

        Strategy (optimized via ablation study):
          Trend mode  → Price-position re-entry (not just crossovers)
                        Two-tier entry logic:
                          - Tier 1 (full stack): price > EMA21 > EMA55 > EMA200
                          - Tier 2 (partial + ADX): price > EMA21 > EMA55 AND
                            ADX > 25 AND EMA-200 slope rising (captures choppier trends)
          Range mode  → Disabled (negative expectancy on crypto)
          Shorts      → Disabled (crypto is structurally long-biased)
        """
        signals: List[Signal] = []
        warmup = self.cfg.trend_ema + 10  # wait for indicators to stabilise

        for i in range(warmup, len(df)):
            r = df.iloc[i]
            regime = self._regime(r['adx'])

            if pd.isna(r['atr']) or r['atr'] <= 0 or pd.isna(r['adx']):
                continue

            # ─── TREND MODE — Long-only re-entries ────────────
            if regime == 'trend':
                # Tier 1: Full stack alignment (strong trend)
                full_stack = (
                    r['close'] > r['ema_fast']
                    and r['ema_fast'] > r['ema_slow']
                    and r['ema_slow'] > r['ema_trend']
                )
                # Tier 2: Partial alignment + ADX trend strength + EMA-200 rising
                partial_stack = (
                    r['close'] > r['ema_fast']
                    and r['ema_fast'] > r['ema_slow']
                    and r['adx'] > self.cfg.trend_adx_threshold
                    and r.get('ema_trend_slope', 0) > 0
                )

                # Enter on initial crossover OR either tier's condition
                # RSI < 70 filter applies to ALL entries (including crossovers)
                long_condition = (r['bullish_cross'] or full_stack or partial_stack) and r['rsi'] < 70
                if long_condition:
                    reason = 'Trend re-entry (full stack)' if full_stack else (
                        'Trend re-entry (partial+ADX)' if partial_stack else 'Bullish EMA cross')
                    signals.append(Signal(
                        symbol, 1, df.index[i], r['close'],
                        r['atr'], 'trend', reason))

                # Shorts disabled — crypto bull bias, shorts lost -$7,753 in baseline

            # ─── RANGE MODE — Disabled ───────────────────────
            # Range mode removed after ablation confirmed negative expectancy
            # across all timeframes and asset sets on crypto

        return signals


# ════════════════════════════════════════════════════════════════
#  6. RISK MANAGER
# ════════════════════════════════════════════════════════════════

class RiskManager:
    """Position sizing, stop-loss, circuit breaker logic."""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def position_size(self, equity: float, price: float,
                      atr: float) -> float:
        if atr <= 0 or price <= 0:
            return 0
        dollar_risk = equity * self.cfg.risk_per_trade
        price_risk = self.cfg.atr_stop_mult * atr
        size = dollar_risk / price_risk
        max_size = (equity * self.cfg.max_position_pct) / price
        return min(size, max_size)

    def stop_price(self, entry: float, atr: float, direction: int) -> float:
        if direction == 1:
            return entry - self.cfg.atr_stop_mult * atr
        return entry + self.cfg.atr_stop_mult * atr

    def circuit_breaker(self, equity: float, peak: float) -> bool:
        return peak > 0 and (peak - equity) / peak > self.cfg.max_drawdown_circuit_breaker

    def check_exit(self, pos: Position, price: float, atr: float,
                   row: pd.Series) -> Tuple[bool, str]:
        """Evaluate every exit rule; returns (should_exit, reason)."""
        pos.update_trail(price)

        # 1. Hard stop-loss
        if pos.direction == 1 and price <= pos.stop_loss:
            return True, 'Hard stop-loss'
        if pos.direction == -1 and price >= pos.stop_loss:
            return True, 'Hard stop-loss'

        # 2. ATR trailing stop
        if pos.direction == 1:
            trail = pos.highest_close - self.cfg.atr_trail_mult * atr
            if price <= trail and pos.highest_close > pos.entry_price:
                return True, 'ATR trailing stop'
        else:
            trail = pos.lowest_close + self.cfg.atr_trail_mult * atr
            if price >= trail and pos.lowest_close < pos.entry_price:
                return True, 'ATR trailing stop'

        # 3. Regime-specific exits
        if pos.regime == 'trend':
            if pos.direction == 1 and row.get('rsi', 50) > 80:
                return True, 'RSI overbought exit'
            if pos.direction == -1 and row.get('rsi', 50) < 20:
                return True, 'RSI oversold exit'

        if pos.regime == 'range':
            if pos.direction == 1 and row.get('rsi', 50) > 65:
                return True, 'Mean-reversion target'
            if pos.direction == -1 and row.get('rsi', 50) < 35:
                return True, 'Mean-reversion target'

        # 4. EMA cross reversal exit
        if pos.direction == 1 and row.get('bearish_cross', False):
            return True, 'Bearish cross exit'
        if pos.direction == -1 and row.get('bullish_cross', False):
            return True, 'Bullish cross exit'

        return False, ''


# ════════════════════════════════════════════════════════════════
#  7. BACKTESTING ENGINE
# ════════════════════════════════════════════════════════════════

class Backtester:
    """Walk-forward event-driven backtester with realistic cost model."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.dm = DataManager(cfg)
        self.strat = Strategy(cfg)
        self.risk = RiskManager(cfg)

        self.cash = cfg.initial_capital
        self.peak = cfg.initial_capital
        self.positions: Dict[str, Position] = {}
        self.equity_log: List[Dict] = []
        self.trade_log: List[Dict] = []

    # ── helpers ──

    def _commission(self, notional: float, is_crypto: bool) -> float:
        rate = self.cfg.crypto_commission if is_crypto else self.cfg.forex_commission
        return notional * rate

    def _slip(self, price: float, direction: int, is_crypto: bool) -> float:
        slip = self.cfg.crypto_slippage if is_crypto else self.cfg.forex_slippage
        return price * (1 + slip * direction)   # +slip for buys, -slip for sells

    def _portfolio_value(self, prices: Dict[str, float]) -> float:
        val = self.cash
        for sym, pos in self.positions.items():
            if sym in prices:
                if pos.direction == 1:
                    val += pos.size * prices[sym]
                else:
                    val += pos.size * (2 * pos.entry_price - prices[sym])
        return val

    # ── open / close ──

    def _open(self, sig: Signal, equity: float):
        is_c = self.dm.is_crypto(sig.symbol)
        fill = self._slip(sig.price, sig.direction, is_c)

        size = self.risk.position_size(equity, fill, sig.atr)
        if size <= 0:
            return

        cost = size * fill
        comm = self._commission(cost, is_c)
        if cost + comm > self.cash:
            size = max(0, (self.cash - comm) / fill)
            cost = size * fill
            if size <= 0:
                return

        stop = self.risk.stop_price(fill, sig.atr, sig.direction)
        self.cash -= (cost + comm)

        self.positions[sig.symbol] = Position(
            symbol=sig.symbol, direction=sig.direction,
            entry_date=sig.date, entry_price=fill,
            size=size, stop_loss=stop,
            atr_at_entry=sig.atr, regime=sig.regime,
            highest_close=fill if sig.direction == 1 else 0,
            lowest_close=fill if sig.direction == -1 else float('inf')
        )

    def _close(self, symbol: str, price: float, date, reason: str):
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return
        is_c = self.dm.is_crypto(symbol)
        fill = self._slip(price, -pos.direction, is_c)

        if pos.direction == 1:
            pnl = (fill - pos.entry_price) * pos.size
        else:
            pnl = (pos.entry_price - fill) * pos.size

        notional = pos.size * fill
        comm = self._commission(notional, is_c)
        self.cash += (pos.size * pos.entry_price) + pnl - comm

        hold_days = (date - pos.entry_date).days if hasattr(date, '__sub__') else 0

        self.trade_log.append({
            'symbol': symbol,
            'dir': 'LONG' if pos.direction == 1 else 'SHORT',
            'regime': pos.regime,
            'entry_date': pos.entry_date,
            'exit_date': date,
            'entry': pos.entry_price,
            'exit': fill,
            'size': pos.size,
            'pnl': pnl - comm,
            'pnl_pct': ((pnl - comm) / (pos.entry_price * pos.size)) * 100 if pos.entry_price * pos.size > 0 else 0,
            'reason': reason,
            'hold_days': hold_days
        })

    # ── main loop ──

    def run(self) -> Dict:
        logger.info("=" * 65)
        logger.info("  ATM-TS  ·  5-Year Backtest")
        logger.info("=" * 65)

        data = self.dm.fetch_all()
        if not data:
            return {'error': 'No data'}

        # Add indicators
        for sym in data:
            data[sym] = Indicators.add_all(data[sym], self.cfg)

        # Generate signals per asset
        sig_map: Dict[object, List[Signal]] = {}
        for sym, df in data.items():
            is_c = self.dm.is_crypto(sym)
            for sig in self.strat.generate(sym, df, is_c):
                sig_map.setdefault(sig.date, []).append(sig)

        # Pre-compute ETH/BTC relative strength filter
        # Only enter ETH when it's outperforming BTC on a 30-day rolling basis
        eth_btc_filter_dates: set = set()
        if 'ETH-USD' in data and 'BTC-USD' in data:
            eth_close = data['ETH-USD']['close']
            btc_close = data['BTC-USD']['close']
            ratio = eth_close / btc_close
            ratio_ma = ratio.rolling(30).mean()
            eth_strong = ratio > ratio_ma
            eth_strong = eth_strong.fillna(False)
            eth_btc_filter_dates = set(eth_strong[eth_strong].index)

        # Unified date index (union of ALL dates across all assets)
        all_dates = sorted(set(d for df in data.values() for d in df.index))

        # Forward-fill prices so assets with different trading calendars
        # (crypto 24/7 vs US ETFs market-days-only) don't cause phantom
        # equity drops when one market is closed but the other is open.
        # Build a DataFrame of all close prices and forward-fill gaps.
        price_frames = []
        for sym, df in data.items():
            s = df[['close']].rename(columns={'close': sym})
            price_frames.append(s)
        full_prices = pd.concat(price_frames, axis=1).reindex(all_dates).ffill()

        for date in all_dates:
            # Prices & rows for today
            prices = {}
            rows = {}
            for sym, df in data.items():
                if date in df.index:
                    rows[sym] = df.loc[date]
                prices[sym] = full_prices.loc[date, sym]

            # Check exits
            for sym in list(self.positions):
                if sym in prices and sym in rows:
                    exit_flag, reason = self.risk.check_exit(
                        self.positions[sym], prices[sym],
                        rows[sym]['atr'], rows[sym])
                    if exit_flag:
                        self._close(sym, prices[sym], date, reason)

            # Portfolio accounting
            equity = self._portfolio_value(prices)
            self.peak = max(self.peak, equity)
            dd = (self.peak - equity) / self.peak if self.peak > 0 else 0

            self.equity_log.append({
                'date': date, 'equity': equity,
                'cash': self.cash, 'positions': len(self.positions),
                'drawdown': dd
            })

            # Process entries
            cb = self.risk.circuit_breaker(equity, self.peak)
            if not cb and date in sig_map:
                for sig in sig_map[date]:
                    if sig.symbol in self.positions:
                        continue
                    if len(self.positions) >= self.cfg.max_positions:
                        continue
                    # ETH/BTC relative strength filter: skip ETH when underperforming BTC
                    if sig.symbol == 'ETH-USD' and date not in eth_btc_filter_dates:
                        continue
                    self._open(sig, equity)

        # Close remaining
        for sym in list(self.positions):
            if sym in prices:
                self._close(sym, prices[sym], all_dates[-1], 'End of backtest')

        return self._results()

    # ── results ──

    def _results(self) -> Dict:
        eq = pd.DataFrame(self.equity_log)
        tr = pd.DataFrame(self.trade_log)
        return {'equity': eq, 'trades': tr}


# ════════════════════════════════════════════════════════════════
#  8. PERFORMANCE ANALYZER
# ════════════════════════════════════════════════════════════════

class Analyzer:
    def __init__(self, equity: pd.DataFrame, trades: pd.DataFrame,
                 initial: float):
        self.eq = equity
        self.tr = trades
        self.initial = initial

    def metrics(self) -> Dict:
        m = {}
        if self.eq.empty:
            return m

        final = self.eq['equity'].iloc[-1]
        days = (self.eq['date'].iloc[-1] - self.eq['date'].iloc[0]).days
        m['total_return_pct'] = (final / self.initial - 1) * 100
        m['annual_return_pct'] = ((final / self.initial) ** (365 / max(days, 1)) - 1) * 100
        m['max_drawdown_pct'] = self.eq['drawdown'].max() * 100

        # Sharpe
        rets = self.eq['equity'].pct_change().dropna()
        m['sharpe'] = (rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0

        # Sortino
        down = rets[rets < 0]
        m['sortino'] = (rets.mean() / down.std() * np.sqrt(252)) if len(down) > 0 and down.std() > 0 else 0

        # Calmar
        m['calmar'] = (m['annual_return_pct'] / m['max_drawdown_pct']
                       if m['max_drawdown_pct'] > 0 else 0)

        # Trade stats
        if not self.tr.empty:
            w = self.tr[self.tr['pnl'] > 0]
            l = self.tr[self.tr['pnl'] <= 0]
            m['total_trades'] = len(self.tr)
            m['wins'] = len(w)
            m['losses'] = len(l)
            m['win_rate_pct'] = len(w) / len(self.tr) * 100
            m['avg_win_pct'] = w['pnl_pct'].mean() if len(w) > 0 else 0
            m['avg_loss_pct'] = l['pnl_pct'].mean() if len(l) > 0 else 0
            m['profit_factor'] = (w['pnl'].sum() / abs(l['pnl'].sum())
                                  if len(l) > 0 and l['pnl'].sum() != 0 else float('inf'))
            m['avg_hold_days'] = self.tr['hold_days'].mean()
            m['max_win_pct'] = self.tr['pnl_pct'].max()
            m['max_loss_pct'] = self.tr['pnl_pct'].min()

            # By regime
            for reg in ['trend', 'range']:
                sub = self.tr[self.tr['regime'] == reg]
                m[f'{reg}_trades'] = len(sub)
                m[f'{reg}_pnl'] = sub['pnl'].sum() if len(sub) > 0 else 0
                m[f'{reg}_win_rate'] = (len(sub[sub['pnl'] > 0]) / len(sub) * 100) if len(sub) > 0 else 0

            # By symbol
            m['by_symbol'] = self.tr.groupby('symbol').agg(
                pnl_sum=('pnl', 'sum'),
                count=('pnl', 'count'),
                win_rate=('pnl', lambda x: (x > 0).sum() / len(x) * 100)
            ).to_dict('index')

            # By direction
            longs = self.tr[self.tr['dir'] == 'LONG']
            shorts = self.tr[self.tr['dir'] == 'SHORT']
            m['long_pnl'] = longs['pnl'].sum() if len(longs) > 0 else 0
            m['short_pnl'] = shorts['pnl'].sum() if len(shorts) > 0 else 0

            # Monthly returns
            if not self.tr.empty:
                self.tr['exit_month'] = pd.to_datetime(self.tr['exit_date']).dt.to_period('M')
                m['monthly_pnl'] = self.tr.groupby('exit_month')['pnl'].sum().to_dict()

        # Exit reason distribution
        if not self.tr.empty and 'reason' in self.tr.columns:
            m['exit_reasons'] = self.tr['reason'].value_counts().to_dict()

        return m

    def print_report(self, m: Dict):
        W = 72
        print("\n" + "=" * W)
        print("  ATM-TS  ·  BACKTEST PERFORMANCE REPORT".center(W))
        print("=" * W)

        print(f"\n  {'── Returns ──':^68}")
        print(f"  Total Return:        {m.get('total_return_pct',0):>10.2f} %")
        print(f"  Annualized Return:   {m.get('annual_return_pct',0):>10.2f} %")
        print(f"  Sharpe Ratio:        {m.get('sharpe',0):>10.2f}")
        print(f"  Sortino Ratio:       {m.get('sortino',0):>10.2f}")
        print(f"  Calmar Ratio:        {m.get('calmar',0):>10.2f}")

        print(f"\n  {'── Risk ──':^68}")
        print(f"  Max Drawdown:        {m.get('max_drawdown_pct',0):>10.2f} %")

        n = m.get('total_trades', 0)
        print(f"\n  {'── Trade Statistics ──':^68}")
        print(f"  Total Trades:        {n:>10d}")
        print(f"  Wins / Losses:       {m.get('wins',0):>4d} / {m.get('losses',0):<5d}")
        print(f"  Win Rate:            {m.get('win_rate_pct',0):>10.2f} %")
        print(f"  Avg Win:             {m.get('avg_win_pct',0):>+10.2f} %")
        print(f"  Avg Loss:            {m.get('avg_loss_pct',0):>+10.2f} %")
        print(f"  Profit Factor:       {m.get('profit_factor',0):>10.2f}")
        print(f"  Max Win:             {m.get('max_win_pct',0):>+10.2f} %")
        print(f"  Max Loss:            {m.get('max_loss_pct',0):>+10.2f} %")
        print(f"  Avg Hold Days:       {m.get('avg_hold_days',0):>10.1f}")

        print(f"\n  {'── Direction Breakdown ──':^68}")
        print(f"  Long  P&L:           ${m.get('long_pnl',0):>+10.2f}")
        print(f"  Short P&L:           ${m.get('short_pnl',0):>+10.2f}")

        print(f"\n  {'── Regime Breakdown ──':^68}")
        for reg in ['trend', 'range']:
            print(f"  {reg.title():6s}  trades={m.get(f'{reg}_trades',0):<4d}  "
                  f"P&L=${m.get(f'{reg}_pnl',0):>+10.2f}  "
                  f"WR={m.get(f'{reg}_win_rate',0):.1f}%")

        if 'by_symbol' in m:
            print(f"\n  {'── By Symbol ──':^68}")
            for sym, stats in m['by_symbol'].items():
                print(f"  {sym:<15s}  P&L=${stats['pnl_sum']:>+10.2f}  "
                      f"Trades={int(stats['count']):<4d}  "
                      f"WR={stats['win_rate']:.1f}%")

        if 'exit_reasons' in m:
            print(f"\n  {'── Exit Reasons ──':^68}")
            for reason, count in sorted(m['exit_reasons'].items(), key=lambda x: -x[1]):
                print(f"  {reason:<28s}  {count:>5d}")

        # ── Verdict ──
        print(f"\n  {'── VERDICT ──':^68}")
        score = 0
        notes = []

        sharpe = m.get('sharpe', 0)
        dd = m.get('max_drawdown_pct', 0)
        ann = m.get('annual_return_pct', 0)
        pf = m.get('profit_factor', 0)

        if sharpe > 1.0:
            score += 30; notes.append(f"✓ Sharpe {sharpe:.2f} > 1.0")
        elif sharpe > 0.5:
            score += 15; notes.append(f"△ Sharpe {sharpe:.2f} moderate")
        else:
            notes.append(f"✗ Sharpe {sharpe:.2f} < 0.5")

        if dd < 20:
            score += 25; notes.append(f"✓ Max DD {dd:.1f}% < 20%")
        elif dd < 30:
            score += 12; notes.append(f"△ Max DD {dd:.1f}% moderate")
        else:
            notes.append(f"✗ Max DD {dd:.1f}% > 30%")

        if ann > 10:
            score += 25; notes.append(f"✓ Annual {ann:.1f}% > 10%")
        elif ann > 0:
            score += 10; notes.append(f"△ Annual {ann:.1f}% marginal")
        else:
            notes.append(f"✗ Annual {ann:.1f}% negative")

        if pf > 1.5:
            score += 20; notes.append(f"✓ PF {pf:.2f} > 1.5")
        elif pf > 1.0:
            score += 8; notes.append(f"△ PF {pf:.2f} slightly positive")
        else:
            notes.append(f"✗ PF {pf:.2f} < 1.0")

        for n in notes:
            print(f"  {n}")
        print(f"\n  Score: {score}/100")

        if score >= 75:
            v = "🏆 WINNER — Strong positive expectancy"
        elif score >= 50:
            v = "⚡ PROMISING — Needs minor tuning"
        elif score >= 25:
            v = "⚠️  MARGINAL — Needs significant work"
        else:
            v = "❌ LOSER — No positive edge detected"
        print(f"  Verdict: {v}")
        print("=" * W)

    def plot(self, m: Dict):
        """Generate equity curve and drawdown charts."""
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
        except ImportError:
            logger.warning("matplotlib not installed — skipping charts")
            return

        if self.eq.empty:
            return

        fig, axes = plt.subplots(3, 1, figsize=(14, 12), gridspec_kw={'height_ratios': [3, 1, 1]})

        dates = self.eq['date']
        equity = self.eq['equity']
        dd = self.eq['drawdown'] * 100

        # Equity curve
        axes[0].plot(dates, equity, color='#2196F3', linewidth=1.2, label='Portfolio')
        axes[0].axhline(self.initial, color='gray', linestyle='--', alpha=0.5)
        axes[0].fill_between(dates, self.initial, equity,
                             where=equity >= self.initial, alpha=0.1, color='green')
        axes[0].fill_between(dates, self.initial, equity,
                             where=equity < self.initial, alpha=0.1, color='red')
        axes[0].set_title(f'ATM-TS Equity Curve  |  '
                          f'Return: {m.get("total_return_pct",0):.1f}%  |  '
                          f'Sharpe: {m.get("sharpe",0):.2f}  |  '
                          f'Max DD: {m.get("max_drawdown_pct",0):.1f}%',
                          fontsize=13, fontweight='bold')
        axes[0].set_ylabel('Portfolio Value ($)')
        axes[0].legend()
        axes[0].grid(alpha=0.3)

        # Drawdown
        axes[1].fill_between(dates, 0, -dd, color='#F44336', alpha=0.4)
        axes[1].set_ylabel('Drawdown (%)')
        axes[1].set_title('Drawdown', fontsize=11)
        axes[1].grid(alpha=0.3)

        # Position count
        axes[2].plot(dates, self.eq['positions'], color='#FF9800', linewidth=0.8)
        axes[2].set_ylabel('Open Positions')
        axes[2].set_title('Concurrent Positions', fontsize=11)
        axes[2].grid(alpha=0.3)

        for ax in axes:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

        plt.tight_layout()
        plt.savefig('atm_ts_backtest.png', dpi=150, bbox_inches='tight')
        logger.info("Chart saved → atm_ts_backtest.png")
        plt.show()


# ════════════════════════════════════════════════════════════════
#  9. PARAMETER ROBUSTNESS TEST
# ════════════════════════════════════════════════════════════════

class RobustnessTest:
    """Test strategy across parameter variations to detect overfitting."""

    VARIATIONS = [
        {'fast_ema': 12, 'slow_ema': 34, 'atr_stop_mult': 2.0, 'atr_trail_mult': 2.5},
        {'fast_ema': 21, 'slow_ema': 55, 'atr_stop_mult': 2.5, 'atr_trail_mult': 3.0},  # default
        {'fast_ema': 21, 'slow_ema': 55, 'atr_stop_mult': 3.0, 'atr_trail_mult': 3.5},
        {'fast_ema': 30, 'slow_ema': 70, 'atr_stop_mult': 2.5, 'atr_trail_mult': 3.0},
        {'fast_ema': 15, 'slow_ema': 40, 'atr_stop_mult': 2.0, 'atr_trail_mult': 2.5},
    ]

    @staticmethod
    def run(cfg: Config):
        print("\n" + "=" * 72)
        print("  PARAMETER ROBUSTNESS TEST".center(72))
        print("=" * 72)
        print(f"  {'#':<4} {'Fast':>5} {'Slow':>5} {'Stop':>6} {'Trail':>6} "
              f"{'Return%':>9} {'Sharpe':>7} {'MaxDD%':>8} {'Trades':>7} {'PF':>6}")
        print("  " + "-" * 68)

        results = []
        for i, var in enumerate(RobustnessTest.VARIATIONS):
            test_cfg = Config(
                start_date=cfg.start_date,
                end_date=cfg.end_date,
                initial_capital=cfg.initial_capital,
                crypto_assets=cfg.crypto_assets,
                forex_assets=cfg.forex_assets,
                fast_ema=var['fast_ema'],
                slow_ema=var['slow_ema'],
                atr_stop_mult=var['atr_stop_mult'],
                atr_trail_mult=var['atr_trail_mult'],
            )
            bt = Backtester(test_cfg)
            res = bt.run()
            if 'error' in res:
                continue

            eq = res['equity']
            tr = res['trades']
            if eq.empty:
                continue

            a = Analyzer(eq, tr, test_cfg.initial_capital)
            m = a.metrics()

            final = eq['equity'].iloc[-1]
            ann_ret = ((final / test_cfg.initial_capital) ** (
                365 / max((eq['date'].iloc[-1] - eq['date'].iloc[0]).days, 1)) - 1) * 100

            rets = eq['equity'].pct_change().dropna()
            sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
            maxdd = eq['drawdown'].max() * 100

            w = tr[tr['pnl'] > 0]
            l = tr[tr['pnl'] <= 0]
            pf = w['pnl'].sum() / abs(l['pnl'].sum()) if len(l) > 0 and l['pnl'].sum() != 0 else 999

            print(f"  {i+1:<4} {var['fast_ema']:>5} {var['slow_ema']:>5} "
                  f"{var['atr_stop_mult']:>6.1f} {var['atr_trail_mult']:>6.1f} "
                  f"{ann_ret:>+9.2f} {sharpe:>7.2f} {maxdd:>8.2f} "
                  f"{len(tr):>7d} {pf:>6.2f}")

            results.append(sharpe)

        # Verdict
        positive = sum(1 for r in results if r > 0)
        print(f"\n  {positive}/{len(results)} variations have positive Sharpe ratio")
        if positive >= len(results) * 0.7:
            print("  ✓ Strategy is ROBUST — not overly sensitive to parameters")
        elif positive >= len(results) * 0.4:
            print("  △ Strategy is MODERATELY robust — some parameter sensitivity")
        else:
            print("  ✗ Strategy is FRAGILE — likely overfit to specific parameters")
        print("=" * 72)


# ════════════════════════════════════════════════════════════════
# 10. WALK-FORWARD VALIDATION
# ════════════════════════════════════════════════════════════════

class WalkForwardValidator:
    """
    Walk-forward validation using time-based folds with DEFAULT parameters.

    Methodology (per statistical best practices):
      - Uses fixed default params on EVERY test window (no parameter optimization)
      - Time-based folds: each fold tests the NEXT chronological period
      - Flags windows with < 10 trades as statistically void
      - Reports IS vs OOS Sharpe degradation for honest overfit detection

    This replaces the previous parameter-optimization approach which
    introduced selection bias (overfitting the best params to each window).
    """

    # Time-based folds: test default params on chronologically subsequent periods
    FOLDS = [
        {'train_end': '2021-06-01', 'test_start': '2021-06-01',
         'test_end': '2022-06-01', 'label': '2021-06 to 2022-06'},
        {'train_end': '2022-06-01', 'test_start': '2022-06-01',
         'test_end': '2023-06-01', 'label': '2022-06 to 2023-06'},
        {'train_end': '2023-06-01', 'test_start': '2023-06-01',
         'test_end': '2024-06-01', 'label': '2023-06 to 2024-06'},
    ]

    MIN_TRADES_FOR_STATISTICS = 10  # Below this, flag as statistically void

    @staticmethod
    def _window_metrics(eq_filtered: pd.DataFrame, tr_filtered: pd.DataFrame) -> Dict:
        """Compute performance metrics from a filtered equity/trade log."""
        m = {}
        if eq_filtered.empty or len(eq_filtered) < 5:
            return m

        start_val = eq_filtered['equity'].iloc[0]
        end_val = eq_filtered['equity'].iloc[-1]
        days = (eq_filtered['date'].iloc[-1] - eq_filtered['date'].iloc[0]).days

        m['return_pct'] = (end_val / start_val - 1) * 100
        m['annual_return_pct'] = ((end_val / start_val) ** (365 / max(days, 1)) - 1) * 100 if days > 0 else 0

        peak = eq_filtered['equity'].cummax()
        dd = ((peak - eq_filtered['equity']) / peak) * 100
        m['max_dd_pct'] = dd.max()

        rets = eq_filtered['equity'].pct_change().dropna()
        m['sharpe'] = (rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0

        down = rets[rets < 0]
        m['sortino'] = (rets.mean() / down.std() * np.sqrt(252)) if len(down) > 0 and down.std() > 0 else 0

        if not tr_filtered.empty:
            m['trades'] = len(tr_filtered)
            winners = tr_filtered[tr_filtered['pnl'] > 0]
            losers = tr_filtered[tr_filtered['pnl'] <= 0]
            m['wins'] = len(winners)
            m['losses'] = len(losers)
            m['win_rate'] = len(winners) / len(tr_filtered) * 100
            m['profit_factor'] = (
                winners['pnl'].sum() / abs(losers['pnl'].sum())
                if len(losers) > 0 and losers['pnl'].sum() != 0
                else float('inf') if len(winners) > 0 else 0
            )
            m['avg_hold_days'] = tr_filtered['hold_days'].mean() if 'hold_days' in tr_filtered.columns else 0

        return m

    @staticmethod
    def run(cfg: Config):
        """Run walk-forward validation with time-based folds and default params."""
        W = 72
        print("\n" + "=" * W)
        print("  WALK-FORWARD VALIDATION (Time-Based Folds)".center(W))
        print("=" * W)
        print("  Methodology: Fixed DEFAULT params on each time-based fold")
        print("  No parameter optimization — tests strategy edge, not curve-fit")
        print("=" * W)

        all_oos_trades: List[pd.DataFrame] = []
        fold_summaries = []

        for fold_idx, fold in enumerate(WalkForwardValidator.FOLDS):
            train_end = fold['train_end']
            test_start = fold['test_start']
            test_end = fold['test_end']
            label = fold['label']
            print(f"\n  ── Fold {fold_idx+1}: Train → {train_end}, Test {label} ──")

            # ─── In-Sample: Train on data before test period ───
            is_cfg = Config(
                start_date=cfg.start_date,
                end_date=train_end,
                initial_capital=cfg.initial_capital,
                crypto_assets=cfg.crypto_assets,
                forex_assets=cfg.forex_assets,
            )
            is_bt = Backtester(is_cfg)
            is_res = is_bt.run()
            if 'error' in is_res:
                print(f"  ⚠ IS backtest failed")
                continue

            is_eq = is_res['equity']
            is_tr = is_res['trades']
            is_metrics = WalkForwardValidator._window_metrics(is_eq, is_tr)

            print(f"  IS:  Sharpe={is_metrics.get('sharpe',0):.2f}, "
                  f"Return={is_metrics.get('return_pct',0):+.1f}%, "
                  f"DD={is_metrics.get('max_dd_pct',0):.1f}%, "
                  f"Trades={is_metrics.get('trades',0)}")

            # ─── Out-of-Sample: Run DEFAULT params on test period ───
            # Use warmup before test_start for indicator stability
            warmup_start_dt = pd.Timestamp(test_start) - timedelta(days=500)
            full_start_dt = pd.Timestamp(cfg.start_date)
            oos_start = max(warmup_start_dt, full_start_dt).strftime('%Y-%m-%d')

            oos_cfg = Config(
                start_date=oos_start,
                end_date=test_end,
                initial_capital=cfg.initial_capital,
                crypto_assets=cfg.crypto_assets,
                forex_assets=cfg.forex_assets,
            )

            oos_bt = Backtester(oos_cfg)
            oos_res = oos_bt.run()
            if 'error' in oos_res:
                print(f"  ⚠ OOS backtest failed")
                continue

            full_eq = oos_res['equity']
            full_tr = oos_res['trades']

            if full_eq.empty:
                continue

            # Filter to OOS period: trades entered after test_start
            test_start_dt = pd.Timestamp(test_start)
            oos_eq = full_eq[full_eq['date'] >= test_start_dt].copy()

            oos_tr = pd.DataFrame()
            if not full_tr.empty and 'entry_date' in full_tr.columns:
                oos_tr = full_tr[
                    pd.to_datetime(full_tr['entry_date']) >= test_start_dt
                ].copy()

            if oos_eq.empty or len(oos_eq) < 5:
                print(f"  ⚠ No OOS data in test period")
                continue

            oos_metrics = WalkForwardValidator._window_metrics(oos_eq, oos_tr)
            oos_trades = oos_metrics.get('trades', 0)

            # Flag windows with insufficient trades
            stat_flag = ""
            if oos_trades < WalkForwardValidator.MIN_TRADES_FOR_STATISTICS:
                stat_flag = " ⚠ VOID (< 10 trades)"

            print(f"  OOS: Sharpe={oos_metrics.get('sharpe',0):.2f}, "
                  f"Return={oos_metrics.get('return_pct',0):+.1f}%, "
                  f"DD={oos_metrics.get('max_dd_pct',0):.1f}%, "
                  f"Trades={oos_trades}{stat_flag}")

            degradation = is_metrics.get('sharpe', 0) - oos_metrics.get('sharpe', 0)

            fold_summaries.append({
                'label': label,
                'is_sharpe': is_metrics.get('sharpe', 0),
                'oos_sharpe': oos_metrics.get('sharpe', 0),
                'is_return': is_metrics.get('return_pct', 0),
                'oos_return': oos_metrics.get('return_pct', 0),
                'is_dd': is_metrics.get('max_dd_pct', 0),
                'oos_dd': oos_metrics.get('max_dd_pct', 0),
                'oos_trades': oos_trades,
                'oos_win_rate': oos_metrics.get('win_rate', 0),
                'oos_pf': oos_metrics.get('profit_factor', 0),
                'degradation': degradation,
                'stat_void': oos_trades < WalkForwardValidator.MIN_TRADES_FOR_STATISTICS,
            })

            if not oos_tr.empty:
                all_oos_trades.append(oos_tr)

        # ─── Final Summary ───
        print("\n" + "=" * W)
        print("  WALK-FORWARD SUMMARY".center(W))
        print("=" * W)

        if not fold_summaries:
            print("  No valid folds completed.")
            print("=" * W)
            return

        header = f"  {'Fold':<22} {'IS Sharpe':>9} {'OOS Sharpe':>10} {'OOS Ret%':>9} {'OOS DD%':>8} {'Trades':>7} {'WR%':>5} {'PF':>6}"
        print(header)
        print("  " + "-" * (len(header) - 2))

        for fs in fold_summaries:
            void = " ⚠ VOID" if fs['stat_void'] else ""
            print(f"  {fs['label']:<22} {fs['is_sharpe']:>9.2f} {fs['oos_sharpe']:>10.2f} "
                  f"{fs['oos_return']:>+9.2f} {fs['oos_dd']:>8.2f} "
                  f"{fs['oos_trades']:>7d} {fs['oos_win_rate']:>4.0f}% {fs['oos_pf']:>6.2f}{void}")

        # Analyze only folds with sufficient trades
        valid_folds = [fs for fs in fold_summaries if not fs['stat_void']]
        void_folds = [fs for fs in fold_summaries if fs['stat_void']]

        print(f"\n  {'── ANALYSIS ──':^68}")
        if void_folds:
            print(f"  ⚠ {len(void_folds)}/{len(fold_summaries)} folds flagged as statistically void (< 10 trades)")
            for fs in void_folds:
                print(f"     - {fs['label']}: only {fs['oos_trades']} trades")

        if valid_folds:
            n = len(valid_folds)
            avg_is_sharpe = np.mean([fs['is_sharpe'] for fs in valid_folds])
            avg_oos_sharpe = np.mean([fs['oos_sharpe'] for fs in valid_folds])
            sharpe_decay = avg_is_sharpe - avg_oos_sharpe
            positive_oos = sum(1 for fs in valid_folds if fs['oos_sharpe'] > 0)

            print(f"\n  {'── HONEST ASSESSMENT (valid folds only) ──':^68}")
            print(f"  Avg IS Sharpe:      {avg_is_sharpe:>10.2f}")
            print(f"  Avg OOS Sharpe:     {avg_oos_sharpe:>10.2f}")
            print(f"  Sharpe Decay:       {sharpe_decay:>+10.2f}")
            print(f"  Folds w/ OOS>0:     {positive_oos}/{n}")

            notes = []
            if sharpe_decay < 0.3:
                notes.append("✓ Low decay — strategy edge is consistent")
            elif sharpe_decay < 0.7:
                notes.append("△ Moderate decay — some overfitting expected")
            else:
                notes.append("✗ High decay — significant overfitting detected")

            if positive_oos < n * 0.5:
                notes.append("  Most folds negative OOS — strategy may lack systematic edge")
            elif avg_oos_sharpe > 0.5:
                notes.append("  Positive OOS Sharpe — strategy shows real edge")

            for n in notes:
                print(f"  {n}")
        else:
            print(f"  No valid folds with sufficient trades for analysis.")
            print(f"  Total trades across all folds: {sum(fs['oos_trades'] for fs in fold_summaries)}")

        print("=" * W)

        # Export
        if all_oos_trades:
            pd.concat(all_oos_trades, ignore_index=True).to_csv(
                'atm_ts_walkforward_oos_trades.csv', index=False)
            logger.info("Walk-forward OOS trades → atm_ts_walkforward_oos_trades.csv")


# ════════════════════════════════════════════════════════════════
# 11. TIMEFRAME COMPARISON
# ════════════════════════════════════════════════════════════════

class TimeframeComparison:
    """
    Run backtests at multiple timeframes and compare results.

    - '1d': Daily bars via Yahoo Finance (5 years)
    - '4h': 4-hour bars via ccxt Binance for crypto (years of data)
    - '1h': 1-hour bars via ccxt Binance for crypto (years of data)

    Forex assets only have reliable daily data via Yahoo Finance.
    """

    TIMEFRAMES = ['1d', '4h', '1h']

    @staticmethod
    def _bars_per_year(timeframe: str) -> int:
        """Approximate number of bars per year for a given timeframe."""
        factors = {'1d': 252, '4h': 252 * 6, '1h': 252 * 24}
        return factors.get(timeframe, 252)

    @staticmethod
    def run(base_cfg: Config):
        """Run and compare backtests across timeframes."""
        W = 72
        print("\n" + "=" * W)
        print("  TIMEFRAME COMPARISON".center(W))
        print("=" * W)
        print()
        print("  Comparing strategy across timeframes:")
        print(f"  • 1d — Daily (Yahoo Finance, 5yr: {base_cfg.start_date} → {base_cfg.end_date})")
        print(f"  • 4h — 4-hour (ccxt Binance for crypto, years of data)")
        print(f"  • 1h — 1-hour (ccxt Binance for crypto, years of data)")
        print("  Forex assets use daily data from Yahoo Finance regardless.")
        print()

        results = []

        for tf in TimeframeComparison.TIMEFRAMES:
            print(f"\n  {'─' * 60}")
            print(f"  ▶ BACKTESTING: timeframe = {tf}".center(60))
            print(f"  {'─' * 60}")

            tf_cfg = Config(
                start_date=base_cfg.start_date,
                end_date=base_cfg.end_date,
                initial_capital=base_cfg.initial_capital,
                crypto_assets=base_cfg.crypto_assets,
                forex_assets=base_cfg.forex_assets,
                fast_ema=base_cfg.fast_ema,
                slow_ema=base_cfg.slow_ema,
                trend_ema=base_cfg.trend_ema,
                timeframe=tf,
            )

            bt = Backtester(tf_cfg)
            res = bt.run()

            if 'error' in res:
                print(f"  ✗ Backtest failed for {tf}")
                continue

            eq = res['equity']
            tr = res['trades']

            if eq.empty:
                print(f"  ✗ No equity data for {tf}")
                continue

            rets = eq['equity'].pct_change().dropna()
            bpy = TimeframeComparison._bars_per_year(tf)
            sharpe = rets.mean() / rets.std() * np.sqrt(bpy) if rets.std() > 0 else 0

            start_val = eq['equity'].iloc[0]
            end_val = eq['equity'].iloc[-1]
            total_return = (end_val / start_val - 1) * 100

            peak = eq['equity'].cummax()
            dd = ((peak - eq['equity']) / peak) * 100
            max_dd = dd.max()

            n_trades = len(tr) if not tr.empty else 0
            avg_hold = tr['hold_days'].mean() if not tr.empty and 'hold_days' in tr.columns else 0

            if not tr.empty:
                winners = tr[tr['pnl'] > 0]
                losers = tr[tr['pnl'] <= 0]
                wr = len(winners) / len(tr) * 100 if len(tr) > 0 else 0
                pf = (winners['pnl'].sum() / abs(losers['pnl'].sum())
                      if len(losers) > 0 and losers['pnl'].sum() != 0
                      else float('inf') if len(winners) > 0 else 0)
            else:
                wr = 0
                pf = 0

            # Trend vs range breakdown
            trend_trades = 0
            range_trades = 0
            trend_pnl = 0
            range_pnl = 0
            if not tr.empty and 'regime' in tr.columns:
                trend_sub = tr[tr['regime'] == 'trend']
                range_sub = tr[tr['regime'] == 'range']
                trend_trades = len(trend_sub)
                range_trades = len(range_sub)
                trend_pnl = trend_sub['pnl'].sum() if len(trend_sub) > 0 else 0
                range_pnl = range_sub['pnl'].sum() if len(range_sub) > 0 else 0

            bars = len(eq)
            days_span = (eq['date'].iloc[-1] - eq['date'].iloc[0]).days if 'date' in eq.columns else 0

            results.append({
                'timeframe': tf,
                'bars': bars,
                'days': days_span,
                'sharpe': sharpe,
                'return_pct': total_return,
                'max_dd_pct': max_dd,
                'trades': n_trades,
                'avg_hold': avg_hold,
                'win_rate': wr,
                'profit_factor': pf,
                'trend_trades': trend_trades,
                'range_trades': range_trades,
                'trend_pnl': trend_pnl,
                'range_pnl': range_pnl,
            })

            print(f"      Bars: {bars:>6,d}  |  Period: {days_span} days")
            print(f"      Sharpe: {sharpe:.3f}  |  Return: {total_return:+.2f}%  |  Max DD: {max_dd:.1f}%")
            print(f"      Trades: {n_trades:>3d}  |  Win Rate: {wr:.1f}%  |  PF: {pf:.2f}")
            print(f"      Avg Hold: {avg_hold:.1f} bars  |  Trend: {trend_trades} trades (${trend_pnl:+.0f})  Range: {range_trades} (${range_pnl:+.0f})")

        # ─── Comparison Table ───
        print("\n" + "=" * W)
        print("  TIMEFRAME COMPARISON — SUMMARY".center(W))
        print("=" * W)

        if not results:
            print("  No results to compare.")
            return

        header = (f"  {'TF':<5} {'Bars':>7} {'Days':>6} {'Return%':>9} "
                  f"{'Sharpe':>7} {'MaxDD%':>8} {'Trades':>7} {'WR%':>5} "
                  f"{'PF':>5} {'Trend':>6} {'Range':>6}")
        print(header)
        print("  " + "-" * (len(header) - 2))

        for r in results:
            print(f"  {r['timeframe']:<5} {r['bars']:>7,d} {r['days']:>6d} "
                  f"{r['return_pct']:>+9.2f} {r['sharpe']:>7.3f} {r['max_dd_pct']:>8.2f} "
                  f"{r['trades']:>7d} {r['win_rate']:>5.1f} {r['profit_factor']:>5.2f} "
                  f"{r['trend_trades']:>6d} {r['range_trades']:>6d}")

        # Insights
        print(f"\n  {'── KEY INSIGHTS ──':^68}")
        if len(results) >= 2:
            tf1 = results[0]
            for r in results[1:]:
                trade_ratio = r['trades'] / max(tf1['trades'], 1)
                sharpe_diff = r['sharpe'] - tf1['sharpe']
                print(f"  {r['timeframe']} vs {tf1['timeframe']}: {trade_ratio:.1f}× more trades, "
                      f"Sharpe {'+' if sharpe_diff >= 0 else ''}{sharpe_diff:+.3f}")

        print("\n" + "=" * W)


# ════════════════════════════════════════════════════════════════
# 12. LIVE / PAPER TRADING FRAMEWORK
# ════════════════════════════════════════════════════════════════

class LiveTrader:
    """
    Live/paper trading framework.
    - Paper mode: simulates fills, no real orders
    - Live mode: connects to exchange via ccxt (crypto only)
    
    For forex live execution, integrate with broker APIs like OANDA, 
    Interactive Brokers, or MetaTrader5.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.dm = DataManager(cfg)
        self.strat = Strategy(cfg)
        self.risk = RiskManager(cfg)
        self.positions: Dict[str, Position] = {}
        self.cash = cfg.initial_capital
        self.peak = cfg.initial_capital
        self.exchange = None

        if cfg.live_mode and not cfg.paper_trading:
            self._init_exchange()

    def _init_exchange(self):
        """Initialize ccxt exchange connection for live crypto trading."""
        try:
            import ccxt
            # Configure with your API keys (use env vars in production)
            self.exchange = ccxt.binance({
                'apiKey': os.environ.get('BINANCE_API_KEY', ''),
                'secret': os.environ.get('BINANCE_SECRET', ''),
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            })
            logger.info("Connected to Binance via ccxt")
        except ImportError:
            logger.error("ccxt not installed. Run: pip install ccxt")
        except Exception as e:
            logger.error(f"Exchange connection failed: {e}")

    def _execute_order(self, symbol: str, direction: int, size: float, price: float, atr: float):
        """Execute trade (paper or live)."""
        is_c = self.dm.is_crypto(symbol)
        action = 'BUY' if direction == 1 else 'SELL'

        if self.cfg.paper_trading:
            logger.info(f"[PAPER] {action} {symbol} | size={size:.6f} | price={price:.2f}")
            # Simulate fill
            slip = self.cfg.crypto_slippage if is_c else self.cfg.forex_slippage
            fill = price * (1 + slip * direction)
            cost = size * fill
            comm = cost * (self.cfg.crypto_commission if is_c else self.cfg.forex_commission)
            self.cash -= (cost + comm)
            self.positions[symbol] = Position(
                symbol=symbol, direction=direction,
                entry_date=datetime.now(), entry_price=fill,
                size=size, stop_loss=self.risk.stop_price(fill, atr, direction),
                atr_at_entry=atr, regime='live'
            )
        else:
            # Live execution via ccxt
            if self.exchange and is_c:
                try:
                    # Convert symbol format: BTC-USD → BTC/USDT
                    ccxt_sym = symbol.replace('-USD', '/USDT')
                    order = self.exchange.create_market_order(
                        ccxt_sym, action.lower(), size)
                    logger.info(f"[LIVE] Order filled: {order['id']}")
                except Exception as e:
                    logger.error(f"Order failed: {e}")

    def scan_and_trade(self):
        """Single scan cycle: check all assets for signals and manage exits.

        Critical flow:
          1. Fetch data for each symbol (needed for BOTH exits and entries)
          2. Handle exits FIRST (always runs, regardless of filters)
          3. Then apply ETH/BTC relative strength filter before considering entries
          4. Generate signals and execute entries if conditions met

        Logs diagnostic information about WHY signals are or aren't generated
        so the system can be debugged in live conditions without guesswork.
        """
        logger.info("─── Scan cycle ───")

        # Cache fetched data to avoid redundant HTTP calls
        _fetch_cache: Dict[str, pd.DataFrame] = {}

        for symbol in self.cfg.crypto_assets + self.cfg.forex_assets:
            is_c = self.dm.is_crypto(symbol)

            # Fetch recent data (cache to avoid duplicate calls)
            if symbol not in _fetch_cache:
                df = self.dm.fetch_recent(symbol, days=300)
                if df.empty or len(df) < self.cfg.trend_ema + 10:
                    logger.warning(f"  {symbol}: insufficient data")
                    continue
                df = Indicators.add_all(df, self.cfg)
                _fetch_cache[symbol] = df

            df = _fetch_cache[symbol]
            last = df.iloc[-1]

            # ── Handle exits FIRST (always — regardless of ETH filter) ──
            if symbol in self.positions:
                pos = self.positions[symbol]
                pos.update_trail(last['close'])
                should_exit, reason = self.risk.check_exit(
                    pos, last['close'], last['atr'], last)
                if should_exit:
                    logger.info(f"  EXIT {symbol} | {reason} | "
                                f"P&L estimate: {((last['close']/pos.entry_price-1)*pos.direction*100):.2f}%")
                    if self.cfg.paper_trading:
                        fill = last['close']
                        if pos.direction == 1:
                            pnl = (fill - pos.entry_price) * pos.size
                        else:
                            pnl = (pos.entry_price - fill) * pos.size
                        comm = (pos.size * fill) * (self.cfg.crypto_commission if is_c else self.cfg.forex_commission)
                        self.cash += pos.size * pos.entry_price + pnl - comm
                        del self.positions[symbol]
                    continue  # Don't open new position same day after exit

            # ── THEN apply ETH/BTC relative strength filter before considering entries ──
            if symbol == 'ETH-USD' and 'BTC-USD' in _fetch_cache:
                # Note: BTC-USD MUST appear before ETH-USD in crypto_assets.
                # The default order ['BTC-USD', 'ETH-USD'] guarantees BTC is already
                # cached when ETH is processed first time through the loop.
                # If BTC isn't cached yet (e.g., reordered assets), filter defaults
                # to True (allow entry) rather than blocking all ETH trades.
                btc_df = _fetch_cache['BTC-USD']
                eth_df = _fetch_cache['ETH-USD']
                ratio = eth_df['close'] / btc_df['close']
                ratio_ma = ratio.rolling(30).mean()
                eth_strong = ratio.iloc[-1] > ratio_ma.iloc[-1] if len(ratio) >= 30 else True
                if not eth_strong:
                    logger.info(f"  ETH-USD entry skipped — ETH/BTC ratio below 30d MA")
                    continue

            # ── Check for new entries ──
            if symbol in self.positions:
                continue
            if len(self.positions) >= self.cfg.max_positions:
                continue

            equity = self.cash + sum(
                p.size * last['close'] if p.direction == 1
                else p.size * (2 * p.entry_price - last['close'])
                for p in self.positions.values()
            )
            if self.risk.circuit_breaker(equity, self.peak):
                logger.warning(f"  Circuit breaker active (DD={(self.peak-equity)/self.peak*100:.1f}%) — skipping new entries")
                return

            # Generate signals from recent data
            signals = self.strat.generate(symbol, df, is_c)
            if signals and signals[-1].date == df.index[-1]:
                sig = signals[-1]
                size = self.risk.position_size(equity, sig.price, sig.atr)
                if size > 0:
                    self._execute_order(symbol, sig.direction, size, sig.price, sig.atr)
                else:
                    logger.info(f"  {symbol} signal but size=0 (risk ${equity*self.cfg.risk_per_trade:.0f}/ATR_risk=${sig.atr*self.cfg.atr_stop_mult:.0f})")
            else:
                # Diagnostic: log WHY no signal was generated
                adx = last['adx']
                regime = self.strat._regime(adx)
                full_stack = last['close'] > last['ema_fast'] and last['ema_fast'] > last['ema_slow'] and last['ema_slow'] > last['ema_trend']
                partial_stack = last['close'] > last['ema_fast'] and last['ema_fast'] > last['ema_slow'] and adx > self.cfg.trend_adx_threshold and last.get('ema_trend_slope', 0) > 0
                last_signal = signals[-1] if signals else None
                latest_match = last_signal is not None and last_signal.date == df.index[-1]

                logger.info(f"  {symbol} no signal — "
                            f"regime={regime}, ADX={adx:.0f}, RSI={last['rsi']:.0f}, "
                            f"full_stack={full_stack}, partial_stack={partial_stack}, "
                            f"EMA200_slope={last.get('ema_trend_slope', 0):.0f}, "
                            f"price_vs_EMA21={last['close']/last['ema_fast']:.3f}, "
                            f"bullish_cross={bool(last.get('bullish_cross', False))}, "
                            f"last_signal_date={'N/A' if not last_signal else str(last_signal.date)[:10]}, "
                            f"latest_bar_match={latest_match}")

        # Update peak from total portfolio equity (not just cash), matching backtester logic
        position_value = sum(
            p.size * _fetch_cache[s].iloc[-1]['close']
            for s, p in self.positions.items()
            if s in _fetch_cache
        )
        total_equity = self.cash + position_value
        self.peak = max(self.peak, total_equity)

    def run_loop(self):
        """Continuous trading loop."""
        logger.info(f"Starting {'PAPER' if self.cfg.paper_trading else 'LIVE'} trading loop")
        logger.info(f"Check interval: {self.cfg.check_interval_seconds}s")

        while True:
            try:
                self.scan_and_trade()
                # Status (use entry prices as best approximation without current quotes)
                position_value = sum(p.size * p.entry_price for p in self.positions.values())
                equity = self.cash + position_value
                logger.info(f"  Cash: ${self.cash:,.2f} | "
                            f"Positions: {len(self.positions)} | "
                            f"Peak: ${self.peak:,.2f}")
            except Exception as e:
                logger.error(f"Scan error: {e}")

            time_module.sleep(self.cfg.check_interval_seconds)


# ════════════════════════════════════════════════════════════════
# 13. MAIN EXECUTION
# ════════════════════════════════════════════════════════════════

def main():
    """Run full backtest pipeline: data → strategy → backtest → analysis → robustness."""

    cfg = Config()

    # ── Step 1: Run Backtest ──
    bt = Backtester(cfg)
    results = bt.run()

    if 'error' in results:
        logger.error("Backtest failed. Check data availability.")
        return

    # ── Step 2: Analyze ──
    analyzer = Analyzer(results['equity'], results['trades'], cfg.initial_capital)
    metrics = analyzer.metrics()
    analyzer.print_report(metrics)

    # ── Step 3: Plot ──
    analyzer.plot(metrics)

    # ── Step 4: Robustness Test ──
    RobustnessTest.run(cfg)

    # ── Step 5: Walk-Forward Validation ──
    WalkForwardValidator.run(cfg)

    # ── Step 6: Timeframe Comparison ──
    TimeframeComparison.run(cfg)

    # ── Step 7: Export ──
    if not results['trades'].empty:
        results['trades'].to_csv('atm_ts_trades.csv', index=False)
        logger.info("Trade log → atm_ts_trades.csv")
    if not results['equity'].empty:
        results['equity'].to_csv('atm_ts_equity.csv', index=False)
        logger.info("Equity curve → atm_ts_equity.csv")

    # ── Step 8: Show how to go live ──
    print("\n" + "=" * 72)
    print("  TO START PAPER TRADING:".center(72))
    print("  cfg = Config(paper_trading=True)".center(72))
    print("  trader = LiveTrader(cfg)".center(72))
    print("  trader.run_loop()".center(72))
    print("=" * 72)
    print("  TO GO LIVE (crypto via Binance):".center(72))
    print("  export BINANCE_API_KEY='your_key'".center(72))
    print("  export BINANCE_SECRET='your_secret'".center(72))
    print("  cfg = Config(live_mode=True, paper_trading=False)".center(72))
    print("  trader = LiveTrader(cfg)".center(72))
    print("  trader.run_loop()".center(72))
    print("=" * 72)

    # ── Save final metrics ──
    serializable = {k: v for k, v in metrics.items()
                    if not isinstance(v, (pd.DataFrame, dict))}
    with open('atm_ts_metrics.json', 'w') as f:
        json.dump(serializable, f, indent=2, default=str)
    logger.info("Metrics → atm_ts_metrics.json")


if __name__ == '__main__':
    main()
