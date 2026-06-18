# ═══════════════════════════════════════════════════════════
# AURUM AI · trading/manager.py
# Open-trade management, broker-agnostic (paper or MT5):
#   • TP1 hit  -> close TP1_CLOSE_PCT, move SL to breakeven
#   • after TP1 -> trail SL behind new structure (never backward)
#   • SL / TP2 hit -> realise the rest
# Returns a ClosedTrade when a position fully closes so the
# learning layer can study it.
# ═══════════════════════════════════════════════════════════

import config
from core.models import ClosedTrade, Position, Side
from core.utils import get_logger, gmt_now, session_of, to_price

log = get_logger("manager")


class TradeManager:
    def __init__(self, broker):
        self.broker = broker
        self._meta: dict[int, dict] = {}    # ticket -> {tp1, tp2, sl0, ...}

    def register(self, pos: Position, sig):
        self._meta[pos.ticket] = {
            "tp1": sig.tp1, "tp2": sig.tp2, "entry": pos.entry,
            "side": pos.side, "setup": sig.setup.value,
            "timeframe": sig.timeframe, "sl0": pos.sl,
            "features": dict(sig.features), "reason": sig.reason,
            "bias_feat": sig.features.get("htf_aligned"),
            "realised": 0.0, "tp1_done": False, "lots0": pos.lots,
        }

    def signatures(self) -> set:
        """(timeframe, side, setup) of every tracked open trade — used to
        avoid stacking duplicates of the SAME setup while still allowing
        different setups/timeframes to run concurrently."""
        out = set()
        for meta in self._meta.values():
            side = meta["side"].value if hasattr(meta["side"], "value") else meta["side"]
            out.add((meta["timeframe"], side, meta["setup"]))
        return out

    def on_bar(self, ticket: int, high: float, low: float, close: float,
               new_swing_low=None, new_swing_high=None) -> ClosedTrade | None:
        """Advance one position against a new bar. Returns ClosedTrade
        if the position fully closes on this bar."""
        meta = self._meta.get(ticket)
        pos = next((p for p in self.broker.open_positions()
                    if p.ticket == ticket), None)
        if not meta or not pos:
            return None
        buy = pos.side == Side.BUY

        # ---- stop loss hit ----
        if (buy and low <= pos.sl) or (not buy and high >= pos.sl):
            pnl = self.broker.close(ticket, pos.sl, 1.0)
            return self._finalise(ticket, pos, pos.sl, meta, pnl)

        # ---- TP1 ----
        if not meta["tp1_done"]:
            hit = (buy and high >= meta["tp1"]) or (not buy and low <= meta["tp1"])
            if hit:
                frac = config.TP1_CLOSE_PCT / 100.0
                pnl = self.broker.close(ticket, meta["tp1"], frac)
                meta["realised"] += pnl
                be = round(meta["entry"] + (to_price(2) if buy else -to_price(2)), 2)
                self.broker.modify(ticket, sl=be)
                meta["tp1_done"] = True
                log.info("#%d TP1 hit -> closed %.0f%%, SL->BE %.2f",
                         ticket, frac * 100, be)
                return None

        # ---- TP2 (full out) ----
        if (buy and high >= meta["tp2"]) or (not buy and low <= meta["tp2"]):
            pnl = self.broker.close(ticket, meta["tp2"], 1.0)
            return self._finalise(ticket, pos, meta["tp2"], meta, pnl)

        # ---- structural trail after TP1 ----
        if meta["tp1_done"]:
            if buy and new_swing_low:
                anchor = round(new_swing_low - to_price(2), 2)
                cur = next((p.sl for p in self.broker.open_positions()
                            if p.ticket == ticket), pos.sl)
                if anchor > cur:
                    self.broker.modify(ticket, sl=anchor)
            elif (not buy) and new_swing_high:
                anchor = round(new_swing_high + to_price(2), 2)
                cur = next((p.sl for p in self.broker.open_positions()
                            if p.ticket == ticket), pos.sl)
                if anchor < cur:
                    self.broker.modify(ticket, sl=anchor)
        return None

    def _finalise(self, ticket, pos, exit_price, meta, last_pnl) -> ClosedTrade:
        total = round(meta["realised"] + last_pnl, 2)
        risk_usd = abs(meta["entry"] - meta["sl0"]) * meta["lots0"] * 100.0
        pnl_r = round(total / risk_usd, 2) if risk_usd > 0 else 0.0
        result = "WIN" if total > 0 else "LOSS" if total < 0 else "BREAKEVEN"
        ct = ClosedTrade(
            ticket=ticket, side=meta["side"], setup=meta["setup"],
            timeframe=meta["timeframe"], entry=meta["entry"],
            exit=round(exit_price, 2), sl=meta["sl0"], lots=meta["lots0"],
            pnl_usd=total, pnl_r=pnl_r, result=result,
            open_time=pos.open_time, close_time=gmt_now(),
            bias="aligned" if meta.get("bias_feat") else "—",
            session=session_of(gmt_now()), features=meta["features"],
            reason=meta["reason"])
        self._meta.pop(ticket, None)
        log.info("#%d CLOSED %s %.2f$ (%.2fR)", ticket, result, total, pnl_r)
        return ct
