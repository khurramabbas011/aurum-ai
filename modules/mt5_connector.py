# ═══════════════════════════════════════════════════════════
# AURUM AI — Step 1 · mt5_connector.py
# Read-only MT5 link: connect, resolve the Gold symbol, pull
# OHLCV per timeframe, read the live price. NO order routing
# (trading tools are locked in Step 1).
# ═══════════════════════════════════════════════════════════

import time

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

import config
from modules.utils import get_logger

log = get_logger("mt5_connector")


class MT5ConnectionError(Exception):
    """Raised when the MT5 terminal cannot be reached/authenticated."""


class MT5Connector:
    """Read-only connection to the local MetaTrader 5 terminal."""

    @staticmethod
    def _tf_map():
        return {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
        }

    def __init__(self):
        self.connected = False

    # ───────────────────────────────────────────────────────
    # CONNECTION
    # ───────────────────────────────────────────────────────
    def connect(self) -> bool:
        """Initialise MT5, log in, resolve the Gold symbol. 3 retries."""
        if mt5 is None:
            raise MT5ConnectionError(
                "MetaTrader5 library not importable — install it on Windows.")
        last = None
        for attempt in range(1, 4):
            log.info("MT5 connect attempt %d/3 ...", attempt)
            if mt5.initialize(path=config.MT5_PATH, login=config.MT5_LOGIN,
                              password=config.MT5_PASSWORD,
                              server=config.MT5_SERVER):
                if not mt5.login(config.MT5_LOGIN,
                                 password=config.MT5_PASSWORD,
                                 server=config.MT5_SERVER):
                    last = mt5.last_error()
                    mt5.shutdown()
                    time.sleep(5)
                    continue
                if not self._resolve_symbol():
                    last = "No XAUUSD-like symbol on this broker"
                    mt5.shutdown()
                    time.sleep(5)
                    continue
                self.connected = True
                a = mt5.account_info()
                if a:
                    log.info("Connected | #%s | %s | %s | symbol=%s",
                             a.login, a.company, a.server, config.SYMBOL)
                return True
            last = mt5.last_error()
            log.warning("initialize failed: %s", last)
            time.sleep(5)
        raise MT5ConnectionError(f"Could not connect after 3 attempts: {last}")

    def _resolve_symbol(self) -> bool:
        """Find the broker's Gold symbol (XAUUSD / XAUUSDm / GOLD ...)."""
        if mt5.symbol_info(config.SYMBOL) is None:
            names = [s.name for s in (mt5.symbols_get() or [])]
            cand = [n for n in names if n.upper().startswith("XAUUSD")] or \
                   [n for n in names if "XAU" in n.upper() and "USD" in n.upper()] or \
                   [n for n in names if "GOLD" in n.upper()]
            if not cand:
                return False
            resolved = sorted(cand, key=len)[0]
            log.warning("Symbol '%s' not found — using '%s'.",
                        config.SYMBOL, resolved)
            config.SYMBOL = resolved
        info = mt5.symbol_info(config.SYMBOL)
        if info is None:
            return False
        if not info.visible:
            mt5.symbol_select(config.SYMBOL, True)
        return True

    def disconnect(self):
        if mt5 is not None and self.connected:
            mt5.shutdown()
        self.connected = False
        log.info("MT5 connection closed.")

    def is_connected(self) -> bool:
        return (mt5 is not None and self.connected
                and mt5.terminal_info() is not None)

    # ───────────────────────────────────────────────────────
    # DATA
    # ───────────────────────────────────────────────────────
    def get_ohlcv(self, timeframe: str, bars: int = None) -> pd.DataFrame:
        """Return a clean GMT-indexed OHLCV DataFrame for a timeframe.

        Columns: time, open, high, low, close, tick_volume, spread.
        Index is a clean 0..n-1 range so swing indexing is simple.
        """
        tf = self._tf_map().get(timeframe)
        if tf is None:
            raise ValueError(f"Unknown timeframe: {timeframe}")
        bars = bars or config.BAR_COUNT.get(timeframe, 300)
        rates = mt5.copy_rates_from_pos(config.SYMBOL, tf, 0, bars)
        if rates is None or len(rates) == 0:
            log.error("No %s data: %s", timeframe, mt5.last_error())
            return pd.DataFrame(columns=["time", "open", "high", "low",
                                         "close", "tick_volume", "spread"])
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        keep = ["time", "open", "high", "low", "close", "tick_volume", "spread"]
        return df[[c for c in keep if c in df.columns]].reset_index(drop=True)

    def get_current_price(self) -> dict:
        """Latest tick: bid, ask, spread in pips."""
        tick = mt5.symbol_info_tick(config.SYMBOL)
        if tick is None:
            return {"bid": None, "ask": None, "spread_pips": None}
        spread_pips = round((tick.ask - tick.bid) / config.PIP_SIZE, 1)
        return {"bid": tick.bid, "ask": tick.ask, "spread_pips": spread_pips}
