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
from core.utils import (get_logger, gmt_now, session_of, silver_bullet_window,
                        to_pips, to_price)

log = get_logger("signals")


class SignalEngine:
    def __init__(self, playbook=None):
        self.playbook = playbook
        self.last_reason = ""          # why the last generate() decided as it did

    def generate(self, timeframe: str, smap, bias, now=None) -> Signal | None:
        """Return the best Signal for this timeframe, or None.

        `now` lets the backtester pass simulated time so session
        tagging + timestamps match the bar, not the wall clock.
        Sets self.last_reason for the dashboard's live-thinking feed."""
        now = now or gmt_now()
        self.last_reason = "no setup"
        # Priority: Unicorn -> Silver Bullet -> Venom -> sweep+CHoCH -> BOS.
        sig = self._unicorn(timeframe, smap, bias) \
            or self._silver_bullet(timeframe, smap, bias, now) \
            or self._venom(timeframe, smap, bias) \
            or self._sweep_choch(timeframe, smap, bias) \
            or self._bos_continuation(timeframe, smap, bias)
        if not sig:
            return None
        sig.created = now

        # FIXED scalp targets — every setup uses the same 50p SL / 100p TP
        if config.USE_FIXED_SL_TP:
            risk = config.FIXED_SL_PIPS * config.PIP_SIZE
            rew = config.FIXED_TP_PIPS * config.PIP_SIZE
            if sig.side == Side.BUY:
                sig.sl = round(sig.entry - risk, 2)
                sig.tp1 = round(sig.entry + rew, 2)
                sig.tp2 = round(sig.entry + rew, 2)
            else:
                sig.sl = round(sig.entry + risk, 2)
                sig.tp1 = round(sig.entry - rew, 2)
                sig.tp2 = round(sig.entry - rew, 2)
            sig.rr = round(config.FIXED_TP_PIPS / config.FIXED_SL_PIPS, 2)
            sig.features["sl_pips"] = config.FIXED_SL_PIPS

        # HTF alignment gate
        if config.REQUIRE_HTF_ALIGNMENT and bias.direction != State.SIDEWAYS:
            want = Side.BUY if bias.direction == State.BULLISH else Side.SELL
            if sig.side != want:
                self.last_reason = (f"{sig.setup.value} {sig.side.value} vs "
                                    f"{bias.direction.value} bias — skip")
                log.info("%s %s dropped — against HTF bias %s",
                         timeframe, sig.setup.value, bias.direction.value)
                return None

        # R:R gate
        if sig.rr < config.MIN_RR:
            self.last_reason = (f"{sig.setup.value} {sig.side.value} "
                                f"R:R {sig.rr}<{config.MIN_RR} — skip")
            log.info("%s %s dropped — R:R %.2f < %.1f",
                     timeframe, sig.setup.value, sig.rr, config.MIN_RR)
            return None

        # scalp guard — CAP a too-wide structural stop to scalp size and
        # rebuild TP from the capped risk (instead of rejecting). This
        # keeps SL/TP scalp-sized even when the raw structure is far.
        sl_pips = to_pips(abs(sig.entry - sig.sl))
        if sl_pips > config.MAX_SL_PIPS:
            risk = config.MAX_SL_PIPS * config.PIP_SIZE
            if sig.side == Side.BUY:
                sig.sl = round(sig.entry - risk, 2)
                sig.tp1 = round(sig.entry + 2 * risk, 2)
                sig.tp2 = round(sig.entry + 3 * risk, 2)
            else:
                sig.sl = round(sig.entry + risk, 2)
                sig.tp1 = round(sig.entry - 2 * risk, 2)
                sig.tp2 = round(sig.entry - 3 * risk, 2)
            sig.rr = 2.0
            sig.features["sl_pips"] = config.MAX_SL_PIPS
            sig.reason += " [SL capped to scalp size]"
            sl_pips = config.MAX_SL_PIPS
        if sl_pips < config.MIN_SL_PIPS:
            self.last_reason = (f"{sig.setup.value} {sig.side.value} "
                                f"SL {sl_pips}p < min {config.MIN_SL_PIPS}p — skip")
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
                self.last_reason = (f"{sig.setup.value} {sig.side.value} "
                                    f"edge {edge:.2f} — learning skip")
                log.info("%s %s SUPPRESSED by learning (edge %.2f < %.2f)",
                         timeframe, sig.setup.value, edge, config.MIN_EDGE_SCORE)
                return None
        self.last_reason = (f"{sig.setup.value} {sig.side.value} @ {sig.entry} "
                            f"R:R {sig.rr} — SIGNAL")
        log.info("SIGNAL %s %s %s entry=%.2f sl=%.2f tp1=%.2f rr=%.2f edge=%.2f",
                 timeframe, sig.side.value, sig.setup.value, sig.entry,
                 sig.sl, sig.tp1, sig.rr, sig.edge_score)
        return sig

    # ---------- ICT Unicorn: breaker + FVG overlap on MSS ----------
    def _unicorn(self, tf, m, bias) -> Signal | None:
        z = m.unicorn
        if not z:
            return None
        price = m.current_price
        tol = config.PIP_SIZE * 5
        # only fire while price is retracing INTO the overlap zone
        if not (z.bottom - tol <= price <= z.top + tol):
            return None
        buf = to_price(config.SL_BUFFER_PIPS)
        if z.direction == State.BULLISH:
            side = Side.BUY
            sl = round((m.breaker.bottom if m.breaker else z.bottom) - buf, 2)
            tp1, tp2 = self._targets_up(m, price, sl)
        else:
            side = Side.SELL
            sl = round((m.breaker.top if m.breaker else z.top) + buf, 2)
            tp1, tp2 = self._targets_dn(m, price, sl)
        return self._mk(side, SetupType.UNICORN, tf, price, sl, tp1, tp2,
                        f"Unicorn {z.direction.value}: breaker+FVG overlap "
                        f"{z.bottom}-{z.top}")

    # ---------- ICT Venom: aggressive strike + MSS + displacement FVG ----------
    def _venom(self, tf, m, bias) -> Signal | None:
        sw = m.sweep
        if not sw.detected or sw.wick_pips < config.VENOM_MIN_STRIKE_PIPS:
            return None                       # need an AGGRESSIVE strike
        ev = m.event
        if sw.side == "SELL_SIDE":            # struck sell-side liq -> long
            want, side = State.BULLISH, Side.BUY
        elif sw.side == "BUY_SIDE":           # struck buy-side liq -> short
            want, side = State.BEARISH, Side.SELL
        else:
            return None
        # require a market-structure shift in the reversal direction
        if ev.type == EventType.NONE or ev.direction != want:
            return None
        price = m.current_price
        tol = config.PIP_SIZE * 6
        cand = [g for g in m.fvgs if g.direction == want and not g.filled
                and g.bottom - tol <= price <= g.top + tol]
        if not cand:
            return None
        g = cand[-1]
        buf = to_price(config.SL_BUFFER_PIPS)
        strike = sw.wick_pips * config.PIP_SIZE
        if want == State.BULLISH:
            sl = round(min(sw.level - strike, g.bottom) - buf, 2)
            tp1, tp2 = self._targets_up(m, price, sl)
        else:
            sl = round(max(sw.level + strike, g.top) + buf, 2)
            tp1, tp2 = self._targets_dn(m, price, sl)
        return self._mk(side, SetupType.VENOM, tf, price, sl, tp1, tp2,
                        f"Venom: {sw.wick_pips}p strike of {sw.side} + "
                        f"{want.value} MSS + FVG entry")

    # ---------- ICT Silver Bullet: time-window FVG entry ----------
    def _silver_bullet(self, tf, m, bias, now) -> Signal | None:
        window = silver_bullet_window(now)
        if not window:
            return None                       # outside the SB time windows
        if bias.direction == State.SIDEWAYS:
            return None                       # SB trades toward a directional draw
        want = State.BULLISH if bias.direction == State.BULLISH else State.BEARISH
        price = m.current_price
        tol = config.PIP_SIZE * 5
        # most recent unfilled FVG in the bias direction that price is
        # retracing into — the displacement gap left inside the window
        cand = [g for g in m.fvgs if g.direction == want and not g.filled
                and g.bottom - tol <= price <= g.top + tol]
        if not cand:
            return None
        g = cand[-1]
        buf = to_price(config.SL_BUFFER_PIPS)
        if want == State.BULLISH:
            side = Side.BUY
            sl = round(g.bottom - buf, 2)
            tp1, tp2 = self._targets_up(m, price, sl)
        else:
            side = Side.SELL
            sl = round(g.top + buf, 2)
            tp1, tp2 = self._targets_dn(m, price, sl)
        return self._mk(side, SetupType.SILVER_BULLET, tf, price, sl, tp1, tp2,
                        f"Silver Bullet ({window}): FVG {g.bottom}-{g.top} "
                        f"toward liquidity")

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

    # ---------- Setup B: BOS continuation (RETEST entry) ----------
    def _bos_continuation(self, tf, m, bias) -> Signal | None:
        """Proper BOS continuation: after a confirmed Break of Structure,
        DON'T chase the breakout — wait for price to PULL BACK to the
        broken level (old swing high/low, now flipped to support/
        resistance) and enter the retest in the trend direction."""
        ev = m.event
        if ev.type != EventType.BOS or ev.level is None:
            return None
        price = m.current_price
        tol = config.BOS_RETEST_TOL_PIPS * config.PIP_SIZE
        buf = to_price(config.SL_BUFFER_PIPS)

        if ev.direction == State.BULLISH:
            # broke above the old swing high -> it's now support.
            # only enter once price has retraced back DOWN to that level.
            if price > ev.level + tol:
                self.last_reason = "BOS_CONT BUY — extended, waiting for retest"
                return None                      # still extended, no pullback yet
            if price < ev.level - tol:
                return None                      # broke back through — retest failed
            side = Side.BUY
            sl = round((m.last_low.price if m.last_low else ev.level) - buf, 2)
            tp1, tp2 = self._targets_up(m, price, sl)
        elif ev.direction == State.BEARISH:
            # broke below the old swing low -> it's now resistance.
            if price < ev.level - tol:
                self.last_reason = "BOS_CONT SELL — extended, waiting for retest"
                return None
            if price > ev.level + tol:
                return None
            side = Side.SELL
            sl = round((m.last_high.price if m.last_high else ev.level) + buf, 2)
            tp1, tp2 = self._targets_dn(m, price, sl)
        else:
            return None
        return self._mk(side, SetupType.BOS_CONTINUATION, tf, price, sl,
                        tp1, tp2, f"{ev.direction.value} BOS retest @ {ev.level}")

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
