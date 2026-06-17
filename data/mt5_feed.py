# ═══════════════════════════════════════════════════════════
# AURUM AI · data/mt5_feed.py
# Read-only MT5 data feed. Connect, resolve the Gold symbol,
# pull OHLCV per timeframe, read price + account. No orders
# here — order routing lives in trading/execution.py.
# ═══════════════════════════════════════════════════════════

import time

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

import config
from core.utils import get_logger

log = get_logger("mt5_feed")


class MT5Error(Exception):
    pass


class MT5Feed:
    """Live market data from the local MetaTrader 5 terminal."""

    @staticmethod
    def _tf():
        return {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
                "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1}

    def __init__(self):
        self.connected = False
        self.account = None

    def connect(self) -> bool:
        if mt5 is None:
            raise MT5Error("MetaTrader5 library not importable (Windows only).")
        last = None
        for attempt in range(1, 4):
            log.info("MT5 connect %d/3 ...", attempt)
            if mt5.initialize(path=config.MT5_PATH, login=config.MT5_LOGIN,
                              password=config.MT5_PASSWORD,
                              server=config.MT5_SERVER):
                if mt5.login(config.MT5_LOGIN, password=config.MT5_PASSWORD,
                             server=config.MT5_SERVER) and self._resolve():
                    self.connected = True
                    self.account = mt5.account_info()
                    a = self.account
                    log.info("Connected #%s %s %s | %s | trade_mode=%s",
                             a.login, a.company, a.server, config.SYMBOL,
                             a.trade_mode)
                    return True
                mt5.shutdown()
            last = mt5.last_error()
            time.sleep(4)
        raise MT5Error(f"Connect failed after 3 attempts: {last}")

    def _resolve(self) -> bool:
        if mt5.symbol_info(config.SYMBOL) is None:
            names = [s.name for s in (mt5.symbols_get() or [])]
            cand = ([n for n in names if n.upper().startswith("XAUUSD")] or
                    [n for n in names if "XAU" in n.upper() and "USD" in n.upper()] or
                    [n for n in names if "GOLD" in n.upper()])
            if not cand:
                return False
            config.SYMBOL = sorted(cand, key=len)[0]
            log.warning("Gold symbol resolved -> %s", config.SYMBOL)
        info = mt5.symbol_info(config.SYMBOL)
        if info and not info.visible:
            mt5.symbol_select(config.SYMBOL, True)
        return info is not None

    def is_demo(self) -> bool:
        a = self.account or (mt5.account_info() if mt5 else None)
        return bool(a and a.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO)

    def get_ohlcv(self, timeframe: str, bars: int = None) -> pd.DataFrame:
        tf = self._tf().get(timeframe)
        if tf is None:
            raise ValueError(f"bad timeframe {timeframe}")
        bars = bars or config.BAR_COUNT.get(timeframe, 400)
        rates = mt5.copy_rates_from_pos(config.SYMBOL, tf, 0, bars)
        if rates is None or len(rates) == 0:
            log.error("no %s data: %s", timeframe, mt5.last_error())
            return pd.DataFrame(columns=["time", "open", "high", "low",
                                         "close", "tick_volume", "spread"])
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        cols = ["time", "open", "high", "low", "close", "tick_volume", "spread"]
        return df[[c for c in cols if c in df.columns]].reset_index(drop=True)

    def price(self) -> dict:
        t = mt5.symbol_info_tick(config.SYMBOL)
        if t is None:
            return {"bid": None, "ask": None, "spread_pips": None}
        return {"bid": t.bid, "ask": t.ask,
                "spread_pips": round((t.ask - t.bid) / config.PIP_SIZE, 1)}

    def account_info(self) -> dict:
        a = mt5.account_info()
        if a is None:
            return {}
        return {"balance": a.balance, "equity": a.equity,
                "currency": a.currency, "demo": self.is_demo()}

    def disconnect(self):
        if mt5 is not None and self.connected:
            mt5.shutdown()
        self.connected = False
