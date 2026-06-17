# ═══════════════════════════════════════════════════════════
# AURUM AI · strategy/signals.py
# Turns structure + HTF bias into tradeable Signals, then asks
# the learned playbook whether the setup has an edge.
#
# Two setups (both ICT-grounded):
#   A. SWEEP_CHOCH  — liquidity sweep on the signal TF + a CHoCH
#                     reversal in the swept direction. Fade the trap.
#   B. BOS_CONT     — BOS in the HTF-bias direction = continuation;
#                     enter on the break with structural stop.
#
# SL/TP are structural (beyond the sweep/level); R:R must clear
# MIN_RR or the signal is dropped. Every signal carries a feature
# dict so the learning layer can bucket and grade it.
# ═══════════════════════════════════════════════════════════

import config
from core.models import (EventType, Side, Signal, SetupType, State)
from core.utils import get_logger, gmt_now, session_of, to_pips, to_price

log = get_logger("signals")


class SignalEngine:
    def __init__(self, playbook=None):
        self.playbook = playbook

    def generate(self, timeframe: str, smap, bias, now=None) -> Signal | None:
        """Return the best Signal for this timeframe, or None.

        `now` lets the backtester pass simulated time so session
        tagging + timestamps match the bar, not the wall clock."""
        now = now or gmt_now()
        sig = self._sweep_choch(timeframe, smap, bias) \
            or self._bos_continuation(timeframe, smap, bias)
        if not sig:
            return None
        sig.created = now

        # HTF alignment gate
        if config.REQUIRE_HTF_ALIGNMENT and bias.direction != State.SIDEWAYS:
            want = Side.BUY if bias.direction == State.BULLISH else Side.SELL
            if sig.side != want:
                log.info("%s %s dropped — against HTF bias %s",
                         timeframe, sig.setup.value, bias.direction.value)
                return None

        # R:R gate
        if sig.rr < config.MIN_RR:
            log.info("%s %s dropped — R:R %.2f < %.1f",
                     timeframe, sig.setup.value, sig.rr, config.MIN_RR)
            return None

        # learning gate — consult the playbook
        sig.features.update({
            "setup": sig.setup.value, "timeframe": timeframe,
            "session": session_of(now),
            "htf_aligned": int(bias.direction != State.SIDEWAYS and (
                (sig.side == Side.BUY and bias.direction == State.BULLISH) or
                (sig.side == Side.SELL and bias.direction == State.BEARISH))),
            "pd_zone": smap.pd_zone,
        })
        if self.playbook:
            edge, size = self.playbook.edge(sig.features)
            sig.edge_score, sig.size_factor = edge, size
            if edge < config.MIN_EDGE_SCORE:
                log.info("%s %s SUPPRESSED by learning (edge %.2f < %.2f)",
                         timeframe, sig.setup.value, edge, config.MIN_EDGE_SCORE)
                return None
        log.info("SIGNAL %s %s %s entry=%.2f sl=%.2f tp1=%.2f rr=%.2f edge=%.2f",
                 timeframe, sig.side.value, sig.setup.value, sig.entry,
                 sig.sl, sig.tp1, sig.rr, sig.edge_score)
        return sig

    # ---------- Setup A: sweep + CHoCH reversal ----------
    def _sweep_choch(self, tf, m, bias) -> Signal | None:
        sw = m.sweep
        ev = m.event
        if not sw.detected or ev.type != EventType.CHOCH:
            return None
        # sweep side must agree with the CHoCH reversal direction
        if sw.side == "SELL_SIDE" and ev.direction == State.BULLISH:
            side = Side.BUY
        elif sw.side == "BUY_SIDE" and ev.direction == State.BEARISH:
            side = Side.SELL
        else:
            return None

        price = m.current_price
        buf = to_price(config.SL_BUFFER_PIPS)
        if side == Side.BUY:
            sl = round(sw.level - sw.wick_pips * config.PIP_SIZE - buf, 2)
            tp1, tp2 = self._targets_up(m, price, sl)
        else:
            sl = round(sw.level + sw.wick_pips * config.PIP_SIZE + buf, 2)
            tp1, tp2 = self._targets_dn(m, price, sl)
        return self._mk(side, SetupType.SWEEP_CHOCH, tf, price, sl, tp1, tp2,
                        f"Sweep {sw.side} @ {sw.level} + {ev.direction.value} CHoCH")

    # ---------- Setup B: BOS continuation ----------
    def _bos_continuation(self, tf, m, bias) -> Signal | None:
        ev = m.event
        if ev.type != EventType.BOS:
            return None
        price = m.current_price
        buf = to_price(config.SL_BUFFER_PIPS)
        if ev.direction == State.BULLISH and m.last_low:
            side = Side.BUY
            sl = round(m.last_low.price - buf, 2)
            tp1, tp2 = self._targets_up(m, price, sl)
        elif ev.direction == State.BEARISH and m.last_high:
            side = Side.SELL
            sl = round(m.last_high.price + buf, 2)
            tp1, tp2 = self._targets_dn(m, price, sl)
        else:
            return None
        return self._mk(side, SetupType.BOS_CONTINUATION, tf, price, sl,
                        tp1, tp2, f"{ev.direction.value} BOS @ {ev.level}")

    # ---------- structural targets ----------
    @staticmethod
    def _targets_up(m, price, sl):
        risk = max(price - sl, config.PIP_SIZE)
        # prefer a structural objective: range high / last swing high
        objs = [v for v in (m.range_high,
                            m.last_high.price if m.last_high else None)
                if v and v > price]
        tp1 = min(objs) if objs else round(price + 2 * risk, 2)
        if tp1 - price < 2 * risk:                 # enforce >= 2R floor
            tp1 = round(price + 2 * risk, 2)
        tp2 = round(price + 3.0 * risk, 2)
        return round(tp1, 2), tp2

    @staticmethod
    def _targets_dn(m, price, sl):
        risk = max(sl - price, config.PIP_SIZE)
        objs = [v for v in (m.range_low,
                            m.last_low.price if m.last_low else None)
                if v and v < price]
        tp1 = max(objs) if objs else round(price - 2 * risk, 2)
        if price - tp1 < 2 * risk:
            tp1 = round(price - 2 * risk, 2)
        tp2 = round(price - 3.0 * risk, 2)
        return round(tp1, 2), tp2

    @staticmethod
    def _mk(side, setup, tf, entry, sl, tp1, tp2, reason) -> Signal:
        risk = abs(entry - sl)
        rr = abs(tp1 - entry) / risk if risk > 0 else 0.0
        return Signal(side=side, setup=setup, timeframe=tf, entry=round(entry, 2),
                      sl=sl, tp1=tp1, tp2=tp2, rr=round(rr, 2), reason=reason,
                      created=gmt_now(),
                      features={"sl_pips": to_pips(risk)})
