# ═══════════════════════════════════════════════════════════
# AURUM AI — Step 1 · structure_engine.py
# THE CORE. Pure, deterministic market-structure analysis:
#   • swing detection with per-timeframe lookback (Ch.3)
#   • HH / HL / LH / LL labelling (Ch.2)
#   • market state: BULLISH / BEARISH / SIDEWAYS (Ch.2)
#   • BOS / CHoCH with the 2-candle close rule (Ch.5, Ch.6)
#   • liquidity sweep — 1-candle wick + close back (Ch.7)
#   • premium / discount location
# No trading. No look-ahead. Identification only.
# ═══════════════════════════════════════════════════════════

import pandas as pd

import config
from modules.utils import get_logger, price_to_pips

log = get_logger("structure_engine")


class StructureEngine:
    """Deterministic structure mapper for one timeframe at a time."""

    # ───────────────────────────────────────────────────────
    # SWING POINTS (Chapter 3)
    # ───────────────────────────────────────────────────────
    @staticmethod
    def detect_swings(df: pd.DataFrame, lookback: int) -> list:
        """Fractal swings: a high/low that is the strict extreme of
        `lookback` candles on BOTH sides. Returns chronological list
        of {idx, kind:'HIGH'/'LOW', price, time}."""
        swings = []
        n = len(df)
        if n < lookback * 2 + 1:
            return swings
        highs = df["high"].values
        lows = df["low"].values
        for i in range(lookback, n - lookback):
            win_h = highs[i - lookback:i + lookback + 1]
            win_l = lows[i - lookback:i + lookback + 1]
            if highs[i] == win_h.max() and (win_h == highs[i]).sum() == 1:
                swings.append({"idx": i, "kind": "HIGH",
                               "price": float(highs[i]),
                               "time": df["time"].iloc[i]})
            if lows[i] == win_l.min() and (win_l == lows[i]).sum() == 1:
                swings.append({"idx": i, "kind": "LOW",
                               "price": float(lows[i]),
                               "time": df["time"].iloc[i]})
        swings.sort(key=lambda s: s["idx"])
        return swings

    # ───────────────────────────────────────────────────────
    # LABELLING (Chapter 2)
    # ───────────────────────────────────────────────────────
    @staticmethod
    def label_swings(swings: list) -> list:
        """Tag each swing HH/HL/LH/LL (first of each kind = SH/SL)."""
        last_high = None
        last_low = None
        for s in swings:
            if s["kind"] == "HIGH":
                if last_high is None:
                    s["label"] = "SH"
                else:
                    s["label"] = "HH" if s["price"] > last_high else "LH"
                last_high = s["price"]
            else:
                if last_low is None:
                    s["label"] = "SL"
                else:
                    s["label"] = "HL" if s["price"] > last_low else "LL"
                last_low = s["price"]
        return swings

    # ───────────────────────────────────────────────────────
    # MARKET STATE (Chapter 2)
    # ───────────────────────────────────────────────────────
    def determine_state(self, swings: list) -> dict:
        """BULLISH / BEARISH / SIDEWAYS from the recent label mix."""
        labelled = [s for s in swings if s.get("label")]
        if len(labelled) < 3:
            return {"state": "SIDEWAYS", "intact": False,
                    "reason": "Too few confirmed swings to define a trend."}

        recent = [s["label"] for s in labelled[-6:]]
        bull = recent.count("HH") + recent.count("HL")
        bear = recent.count("LH") + recent.count("LL")

        highs = [s for s in labelled if s["kind"] == "HIGH"][-3:]
        lows = [s for s in labelled if s["kind"] == "LOW"][-3:]

        if bull >= 3 and bull > bear:
            state = "BULLISH"
        elif bear >= 3 and bear > bull:
            state = "BEARISH"
        else:
            state = "SIDEWAYS"

        # Trend "intact" = the most recent high and low labels still
        # agree with the state (>= 2 confirming swings, Ch.2 rule).
        intact = False
        if state == "BULLISH":
            intact = (recent.count("HH") >= config.TREND_CONFIRM_SWINGS - 1
                      and any(l == "HH" for l in recent[-3:]))
        elif state == "BEARISH":
            intact = (recent.count("LL") >= config.TREND_CONFIRM_SWINGS - 1
                      and any(l == "LL" for l in recent[-3:]))

        reason = (f"Recent labels {recent} -> bull={bull} bear={bear}.")
        return {"state": state, "intact": intact, "reason": reason,
                "recent_highs": highs, "recent_lows": lows,
                "recent_labels": recent}

    # ───────────────────────────────────────────────────────
    # 2-CANDLE CLOSE HELPER (Chapter 5/6 confirmation rule)
    # ───────────────────────────────────────────────────────
    @staticmethod
    def _break_after(df, start_idx, level, direction):
        """Scan candles after start_idx for a confirmed break of `level`.

        direction 'above' / 'below'. Returns dict:
          {confirmed: bool, kind: '2CLOSE'|'1CLOSE'|'NONE',
           idx, time, price}  — the break event, or NONE.
        '1CLOSE' (single close beyond) is flagged as a potential trap.
        """
        closes = df["close"].values
        n = len(df)
        first_close = None
        for i in range(start_idx + 1, n):
            beyond = closes[i] > level if direction == "above" \
                else closes[i] < level
            if beyond:
                if first_close is None:
                    first_close = i
                # need TWO consecutive closes beyond
                if i + 1 < n:
                    nxt = closes[i + 1] > level if direction == "above" \
                        else closes[i + 1] < level
                    if nxt:
                        return {"confirmed": True, "kind": "2CLOSE",
                                "idx": i + 1, "time": df["time"].iloc[i + 1],
                                "price": level}
                # single close, check if it closed back next bar
            else:
                first_close = None  # streak broken
        if first_close is not None:
            return {"confirmed": False, "kind": "1CLOSE",
                    "idx": first_close, "time": df["time"].iloc[first_close],
                    "price": level}
        return {"confirmed": False, "kind": "NONE"}

    # ───────────────────────────────────────────────────────
    # BOS / CHoCH (Chapter 5 & 6)
    # ───────────────────────────────────────────────────────
    def detect_event(self, df, swings, state) -> dict:
        """Most recent BOS or CHoCH using the 2-candle close rule.

        Bullish break (2 closes above last swing high):
          BOS bullish if state bull/sideways, CHoCH bullish if bear.
        Bearish break (2 closes below last swing low):
          BOS bearish if state bear/sideways, CHoCH bearish if bull.
        """
        highs = [s for s in swings if s["kind"] == "HIGH"]
        lows = [s for s in swings if s["kind"] == "LOW"]
        none = {"type": "NONE", "direction": None, "level": None,
                "time": None, "confirmed": False, "implication": "—"}
        if not highs or not lows:
            return none

        events = []
        last_high = highs[-1]
        last_low = lows[-1]

        up = self._break_after(df, last_high["idx"], last_high["price"],
                               "above")
        if up["kind"] == "2CLOSE":
            is_bos = state in ("BULLISH", "SIDEWAYS")
            events.append({
                "type": "BOS" if is_bos else "CHoCH",
                "direction": "BULLISH",
                "level": last_high["price"], "time": up["time"],
                "idx": up["idx"], "confirmed": True,
                "implication": "continuation" if is_bos else "reversal"})

        dn = self._break_after(df, last_low["idx"], last_low["price"],
                               "below")
        if dn["kind"] == "2CLOSE":
            is_bos = state in ("BEARISH", "SIDEWAYS")
            events.append({
                "type": "BOS" if is_bos else "CHoCH",
                "direction": "BEARISH",
                "level": last_low["price"], "time": dn["time"],
                "idx": dn["idx"], "confirmed": True,
                "implication": "continuation" if is_bos else "reversal"})

        if not events:
            return none
        # Most recent event wins.
        return max(events, key=lambda e: e["idx"])

    # ───────────────────────────────────────────────────────
    # LIQUIDITY SWEEP (Chapter 7)
    # ───────────────────────────────────────────────────────
    def detect_sweep(self, df, swings) -> dict:
        """1-candle wick beyond a swing level, body closes back =
        a liquidity sweep (trap). Returns the most recent one."""
        none = {"detected": False, "side": None, "level": None,
                "time": None, "idx": None}
        highs = [s for s in swings if s["kind"] == "HIGH"]
        lows = [s for s in swings if s["kind"] == "LOW"]
        min_wick = config.SWEEP_MIN_WICK_PIPS * config.PIP_SIZE
        n = len(df)
        found = []

        if highs:
            lvl = highs[-1]["price"]
            for i in range(highs[-1]["idx"] + 1, n):
                r = df.iloc[i]
                if r["high"] > lvl + min_wick and r["close"] < lvl:
                    found.append({"detected": True, "side": "BUY_SIDE",
                                  "level": lvl, "time": r["time"], "idx": i,
                                  "wick_pips": price_to_pips(r["high"] - lvl)})
        if lows:
            lvl = lows[-1]["price"]
            for i in range(lows[-1]["idx"] + 1, n):
                r = df.iloc[i]
                if r["low"] < lvl - min_wick and r["close"] > lvl:
                    found.append({"detected": True, "side": "SELL_SIDE",
                                  "level": lvl, "time": r["time"], "idx": i,
                                  "wick_pips": price_to_pips(lvl - r["low"])})
        if not found:
            return none
        return max(found, key=lambda s: s["idx"])

    # ───────────────────────────────────────────────────────
    # PREMIUM / DISCOUNT
    # ───────────────────────────────────────────────────────
    @staticmethod
    def premium_discount(df, swings) -> dict:
        """Where the current price sits inside the latest swing range."""
        highs = [s for s in swings if s["kind"] == "HIGH"]
        lows = [s for s in swings if s["kind"] == "LOW"]
        if not highs or not lows:
            return {}
        hi = highs[-1]["price"]
        lo = lows[-1]["price"]
        if hi <= lo:
            hi, lo = max(hi, lo), min(hi, lo)
        eq = round((hi + lo) / 2, 2)
        price = float(df["close"].iloc[-1])
        band = (hi - lo) * 0.05
        if price > eq + band:
            zone = "PREMIUM"
        elif price < eq - band:
            zone = "DISCOUNT"
        else:
            zone = "EQUILIBRIUM"
        return {"range_high": round(hi, 2), "range_low": round(lo, 2),
                "equilibrium": eq, "zone": zone}

    # ───────────────────────────────────────────────────────
    # FULL ANALYSIS FOR ONE TIMEFRAME
    # ───────────────────────────────────────────────────────
    def analyze(self, timeframe: str, df: pd.DataFrame) -> dict:
        """Run the complete Step-1 structure read for one timeframe."""
        lookback = config.SWING_LOOKBACK.get(timeframe, 5)
        result = {"timeframe": timeframe, "lookback": lookback,
                  "bars": len(df)}
        if df.empty or len(df) < lookback * 2 + 3:
            result.update(state="UNKNOWN", swings=[], event={"type": "NONE"},
                          error="insufficient data")
            return result

        swings = self.label_swings(self.detect_swings(df, lookback))
        state_info = self.determine_state(swings)
        state = state_info["state"]
        event = self.detect_event(df, swings, state)
        sweep = self.detect_sweep(df, swings)
        pd_zone = self.premium_discount(df, swings)

        highs = [s for s in swings if s["kind"] == "HIGH"]
        lows = [s for s in swings if s["kind"] == "LOW"]
        cur_price = float(df["close"].iloc[-1])

        result.update({
            "state": state,
            "trend_intact": state_info["intact"],
            "state_reason": state_info["reason"],
            "swings": swings,
            "recent_labels": state_info.get("recent_labels", []),
            "last_swing_high": highs[-1] if highs else None,
            "last_swing_low": lows[-1] if lows else None,
            "prev_swing_high": highs[-2] if len(highs) > 1 else None,
            "prev_swing_low": lows[-2] if len(lows) > 1 else None,
            "event": event,
            "sweep": sweep,
            "premium_discount": pd_zone,
            "current_price": round(cur_price, 2),
            # liquidity rests beyond the most recent swings
            "buy_side_liquidity": round(highs[-1]["price"], 2) if highs else None,
            "sell_side_liquidity": round(lows[-1]["price"], 2) if lows else None,
        })
        log.info("%s: state=%s swings=%d event=%s sweep=%s",
                 timeframe, state, len(swings), event["type"],
                 "YES" if sweep["detected"] else "no")
        return result
