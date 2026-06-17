# ═══════════════════════════════════════════════════════════
# AURUM AI · analysis/structure.py
# Deterministic market-structure engine — the analytical core.
# Implements the Step-1 methodology, with improvements:
#   • swing detection w/ per-TF lookback (fractal, both sides)
#   • HH/HL/LH/LL labelling
#   • market state via a *scored* recent-label tally (not a
#     brittle exact-sequence match) + range detection
#   • BOS / CHoCH with the strict 2-close confirmation rule
#   • liquidity sweep: 1-candle wick beyond + body back
#   • fair value gaps (3-candle imbalance)
#   • premium/discount location
# Returns a typed StructureMap. No look-ahead, no trading.
# ═══════════════════════════════════════════════════════════

import pandas as pd

import config
from core.models import (FVG, State, EventType, StructureEvent, StructureMap,
                         Sweep, Swing)
from core.utils import get_logger, to_pips

log = get_logger("structure")


class StructureEngine:

    # ---------- swings ----------
    @staticmethod
    def swings(df: pd.DataFrame, lookback: int) -> list[Swing]:
        out: list[Swing] = []
        n = len(df)
        if n < lookback * 2 + 1:
            return out
        hi = df["high"].values
        lo = df["low"].values
        t = df["time"]
        for i in range(lookback, n - lookback):
            wh = hi[i - lookback:i + lookback + 1]
            wl = lo[i - lookback:i + lookback + 1]
            if hi[i] == wh.max() and (wh == hi[i]).sum() == 1:
                out.append(Swing(i, "HIGH", float(hi[i]), t.iloc[i]))
            if lo[i] == wl.min() and (wl == lo[i]).sum() == 1:
                out.append(Swing(i, "LOW", float(lo[i]), t.iloc[i]))
        out.sort(key=lambda s: s.index)
        return out

    @staticmethod
    def label(swings: list[Swing]) -> list[Swing]:
        last_h = last_l = None
        for s in swings:
            if s.kind == "HIGH":
                s.label = "SH" if last_h is None else (
                    "HH" if s.price > last_h else "LH")
                last_h = s.price
            else:
                s.label = "SL" if last_l is None else (
                    "HL" if s.price > last_l else "LL")
                last_l = s.price
        return swings

    # ---------- state ----------
    def state(self, swings: list[Swing], df: pd.DataFrame):
        labelled = [s for s in swings if s.label]
        if len(labelled) < 3:
            return State.SIDEWAYS, False, []
        recent = [s.label for s in labelled[-6:]]
        bull = recent.count("HH") + recent.count("HL")
        bear = recent.count("LH") + recent.count("LL")

        # range check: are the last few highs (and lows) clustered?
        hi = [s.price for s in labelled if s.kind == "HIGH"][-3:]
        lo = [s.price for s in labelled if s.kind == "LOW"][-3:]
        tol = config.RANGE_TOLERANCE_PIPS * config.PIP_SIZE
        flat = (len(hi) >= 2 and (max(hi) - min(hi)) <= tol and
                len(lo) >= 2 and (max(lo) - min(lo)) <= tol)

        if flat or abs(bull - bear) <= 1:
            return State.SIDEWAYS, False, recent
        if bull > bear:
            intact = recent[-1] in ("HH", "HL") and recent.count("HH") >= 1
            return State.BULLISH, intact, recent
        intact = recent[-1] in ("LH", "LL") and recent.count("LL") >= 1
        return State.BEARISH, intact, recent

    # ---------- 2-close break helper ----------
    @staticmethod
    def _confirmed_break(df, start_idx, level, direction):
        """Two consecutive closes beyond `level` after start_idx."""
        c = df["close"].values
        n = len(df)
        streak = 0
        for i in range(start_idx + 1, n):
            beyond = c[i] > level if direction == "above" else c[i] < level
            if beyond:
                streak += 1
                if streak >= config.CONFIRM_CLOSES:
                    return {"ok": True, "idx": i, "time": df["time"].iloc[i]}
            else:
                streak = 0
        return {"ok": False}

    # ---------- BOS / CHoCH ----------
    def event(self, df, swings, state) -> StructureEvent:
        highs = [s for s in swings if s.kind == "HIGH"]
        lows = [s for s in swings if s.kind == "LOW"]
        if not highs or not lows:
            return StructureEvent()
        events = []
        lh, ll = highs[-1], lows[-1]

        up = self._confirmed_break(df, lh.index, lh.price, "above")
        if up["ok"]:
            is_bos = state in (State.BULLISH, State.SIDEWAYS)
            events.append(StructureEvent(
                EventType.BOS if is_bos else EventType.CHOCH, State.BULLISH,
                round(lh.price, 2), up["time"], True,
                "continuation" if is_bos else "reversal"))

        dn = self._confirmed_break(df, ll.index, ll.price, "below")
        if dn["ok"]:
            is_bos = state in (State.BEARISH, State.SIDEWAYS)
            events.append(StructureEvent(
                EventType.BOS if is_bos else EventType.CHOCH, State.BEARISH,
                round(ll.price, 2), dn["time"], True,
                "continuation" if is_bos else "reversal"))

        if not events:
            return StructureEvent()
        return max(events, key=lambda e: e.time)

    # ---------- liquidity sweep ----------
    def sweep(self, df, swings) -> Sweep:
        highs = [s for s in swings if s.kind == "HIGH"]
        lows = [s for s in swings if s.kind == "LOW"]
        minw = config.SWEEP_MIN_WICK_PIPS * config.PIP_SIZE
        found = []
        n = len(df)
        if highs:
            lv = highs[-1].price
            for i in range(highs[-1].index + 1, n):
                r = df.iloc[i]
                if r["high"] > lv + minw and r["close"] < lv:
                    found.append(Sweep(True, "BUY_SIDE", round(lv, 2),
                                       r["time"], to_pips(r["high"] - lv)))
        if lows:
            lv = lows[-1].price
            for i in range(lows[-1].index + 1, n):
                r = df.iloc[i]
                if r["low"] < lv - minw and r["close"] > lv:
                    found.append(Sweep(True, "SELL_SIDE", round(lv, 2),
                                       r["time"], to_pips(lv - r["low"])))
        if not found:
            return Sweep()
        return max(found, key=lambda s: s.time)

    # ---------- fair value gaps ----------
    @staticmethod
    def fvgs(df, limit=6) -> list[FVG]:
        out = []
        h = df["high"].values
        lo = df["low"].values
        t = df["time"]
        n = len(df)
        for i in range(1, n - 1):
            if lo[i + 1] > h[i - 1]:               # bullish gap
                out.append(FVG(State.BULLISH, round(lo[i + 1], 2),
                               round(h[i - 1], 2), t.iloc[i]))
            elif h[i + 1] < lo[i - 1]:             # bearish gap
                out.append(FVG(State.BEARISH, round(lo[i - 1], 2),
                               round(h[i + 1], 2), t.iloc[i]))
        # mark filled if later price traded back through
        for g in out:
            after = df[df["time"] > g.time]
            if not after.empty:
                g.filled = bool(((after["low"] <= g.top) &
                                 (after["high"] >= g.bottom)).any())
        return [g for g in out if not g.filled][-limit:]

    # ---------- premium / discount ----------
    @staticmethod
    def pd_zone(df, swings):
        highs = [s for s in swings if s.kind == "HIGH"]
        lows = [s for s in swings if s.kind == "LOW"]
        if not highs or not lows:
            return "—", None, None, None
        hi = max(highs[-1].price, lows[-1].price)
        lo = min(highs[-1].price, lows[-1].price)
        eq = round((hi + lo) / 2, 2)
        price = float(df["close"].iloc[-1])
        band = (hi - lo) * 0.05
        zone = "PREMIUM" if price > eq + band else \
               "DISCOUNT" if price < eq - band else "EQUILIBRIUM"
        return zone, round(hi, 2), round(lo, 2), eq

    # ---------- full read ----------
    def analyze(self, timeframe: str, df: pd.DataFrame) -> StructureMap:
        lookback = config.SWING_LOOKBACK.get(timeframe, 5)
        m = StructureMap(timeframe=timeframe, lookback=lookback, bars=len(df))
        if df.empty or len(df) < lookback * 2 + 3:
            m.note = "insufficient data"
            return m

        sw = self.label(self.swings(df, lookback))
        st, intact, recent = self.state(sw, df)
        zone, rh, rl, eq = self.pd_zone(df, sw)
        highs = [s for s in sw if s.kind == "HIGH"]
        lows = [s for s in sw if s.kind == "LOW"]

        m.state = st
        m.trend_intact = intact
        m.swings = sw
        m.recent_labels = recent
        m.last_high = highs[-1] if highs else None
        m.last_low = lows[-1] if lows else None
        m.prev_high = highs[-2] if len(highs) > 1 else None
        m.prev_low = lows[-2] if len(lows) > 1 else None
        m.event = self.event(df, sw, st)
        m.sweep = self.sweep(df, sw)
        m.fvgs = self.fvgs(df)
        m.pd_zone, m.range_high, m.range_low, m.equilibrium = zone, rh, rl, eq
        m.current_price = round(float(df["close"].iloc[-1]), 2)
        return m
