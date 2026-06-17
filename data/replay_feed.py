# ═══════════════════════════════════════════════════════════
# AURUM AI · data/replay_feed.py
# Offline data so the ENTIRE system (analysis → signals → risk
# → paper execution → learning) runs with NO MT5 installed.
#
#   • ReplayFeed     — wraps a historical DataFrame and serves
#                      it candle-by-candle (for the backtester)
#   • SyntheticMarket — generates realistic XAUUSD-like OHLCV
#                      with genuine trend/range/reversal regimes
#                      so structure logic has real patterns to
#                      find without needing a broker.
# ═══════════════════════════════════════════════════════════

import numpy as np
import pandas as pd

import config


class ReplayFeed:
    """Serves a stored OHLCV history one bar at a time per timeframe.

    Used by the backtester. `get_ohlcv(tf)` returns everything up to
    the current cursor so the analysis engine never sees the future.
    """

    def __init__(self, frames: dict[str, pd.DataFrame], base_tf: str = "M5"):
        self.frames = {tf: df.reset_index(drop=True) for tf, df in frames.items()}
        self.base_tf = base_tf
        self.cursor = 0
        self._max = len(self.frames[base_tf]) if base_tf in self.frames else 0

    def __len__(self):
        return self._max

    def seek(self, i: int):
        self.cursor = i

    def step(self) -> bool:
        self.cursor += 1
        return self.cursor < self._max

    def _cutoff_time(self):
        base = self.frames[self.base_tf]
        i = min(self.cursor, len(base) - 1)
        return base["time"].iloc[i]

    def get_ohlcv(self, timeframe: str, bars: int = None) -> pd.DataFrame:
        df = self.frames.get(timeframe)
        if df is None or df.empty:
            return pd.DataFrame(columns=["time", "open", "high", "low",
                                         "close", "tick_volume", "spread"])
        cutoff = self._cutoff_time()
        visible = df[df["time"] <= cutoff]
        if bars:
            visible = visible.tail(bars)
        return visible.reset_index(drop=True)

    def price(self) -> dict:
        df = self.get_ohlcv(self.base_tf)
        if df.empty:
            return {"bid": None, "ask": None, "spread_pips": 3.0}
        c = float(df["close"].iloc[-1])
        return {"bid": round(c - 0.15, 2), "ask": round(c + 0.15, 2),
                "spread_pips": 3.0}


class SyntheticMarket:
    """Generate multi-timeframe XAUUSD-like data with real regimes.

    A base M1 series is built from alternating trend/range/reversal
    legs (so HH/HL, LH/LL, BOS, CHoCH and sweeps genuinely occur),
    then resampled up to every timeframe. Deterministic via seed.
    """

    TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30,
                  "H1": 60, "H4": 240, "D1": 1440}

    def __init__(self, seed: int = 7, start_price: float = 2400.0,
                 minutes: int = 60 * 24 * 30):
        self.rng = np.random.default_rng(seed)
        self.start_price = start_price
        self.minutes = minutes

    def _base_series(self) -> pd.DataFrame:
        n = self.minutes
        price = self.start_price
        out = []
        i = 0
        # build leg by leg until we fill n minutes
        while i < n:
            regime = self.rng.choice(["trend_up", "trend_down", "range"],
                                     p=[0.38, 0.38, 0.24])
            leg = int(self.rng.integers(120, 600))   # 2h–10h legs
            drift = {"trend_up": 0.018, "trend_down": -0.018,
                     "range": 0.0}[regime]
            vol = 0.11 if regime != "range" else 0.07
            for _ in range(leg):
                if i >= n:
                    break
                shock = self.rng.normal(drift, vol)
                # occasional liquidity-grab spike then revert
                if self.rng.random() < 0.012:
                    shock += self.rng.choice([-1, 1]) * self.rng.uniform(0.6, 1.4)
                price = max(50.0, price + shock)
                out.append(price)
                i += 1
        close = np.array(out[:n])
        # build OHLC around the close path
        openp = np.concatenate([[close[0]], close[:-1]])
        hi = np.maximum(openp, close) + np.abs(self.rng.normal(0, 0.12, n))
        lo = np.minimum(openp, close) - np.abs(self.rng.normal(0, 0.12, n))
        t0 = pd.Timestamp("2026-01-01", tz="UTC")
        times = pd.date_range(t0, periods=n, freq="1min")
        return pd.DataFrame({"time": times, "open": openp, "high": hi,
                             "low": lo, "close": close,
                             "tick_volume": self.rng.integers(20, 400, n),
                             "spread": 30})

    @staticmethod
    def _resample(base: pd.DataFrame, minutes: int) -> pd.DataFrame:
        if minutes == 1:
            return base.copy()
        g = base.set_index("time")
        rule = f"{minutes}min"
        df = g.resample(rule, label="right", closed="right").agg({
            "open": "first", "high": "max", "low": "min", "close": "last",
            "tick_volume": "sum", "spread": "mean"}).dropna().reset_index()
        return df

    def build(self, timeframes: list[str] = None) -> dict[str, pd.DataFrame]:
        timeframes = timeframes or config.TIMEFRAMES
        base = self._base_series()
        return {tf: self._resample(base, self.TF_MINUTES[tf])
                for tf in timeframes}
