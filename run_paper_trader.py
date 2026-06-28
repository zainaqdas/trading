#!/usr/bin/env python3
"""Run the ATM-TS paper trader with live diagnostic logging."""

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M'
)

from atm_ts import Config, LiveTrader

cfg = Config(
    paper_trading=True,
    check_interval_seconds=60
)

trader = LiveTrader(cfg)
trader.run_loop()
