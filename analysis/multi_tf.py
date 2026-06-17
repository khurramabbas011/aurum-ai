# ═══════════════════════════════════════════════════════════
# AURUM AI · analysis/multi_tf.py
# Top-down multi-timeframe bias. Higher timeframes always win:
# each TF contributes a weighted vote (D1 heaviest), producing
# a continuous bias score in [-1, +1] and a directional read.
# This replaces v1's flat "aligned/conflict" tags with a real
# weighted conflict-scoring model.
# ═══════════════════════════════════════════════════════════

import config
from core.models import Bias, State
from core.utils import get_logger

log = get_logger("multi_tf")

# Heavier weight = more authority over the bias.
_TF_WEIGHT = {"D1": 1.0, "H4": 0.8, "H1": 0.6, "M30": 0.4,
              "M15": 0.3, "M5": 0.2, "M1": 0.1}


class MultiTF:
    def bias(self, maps: dict) -> Bias:
        """Weighted directional bias from the HTF maps."""
        num = 0.0
        den = 0.0
        aligned, conflicting = [], []
        votes = {}
        for tf in config.HTF_BIAS_TFS:
            m = maps.get(tf)
            if not m:
                continue
            w = _TF_WEIGHT.get(tf, 0.2)
            v = {State.BULLISH: 1.0, State.BEARISH: -1.0}.get(m.state, 0.0)
            # trend that is "intact" carries full weight; else half.
            if v != 0.0 and not m.trend_intact:
                v *= 0.5
            votes[tf] = v
            num += w * v
            den += w
        score = round(num / den, 3) if den else 0.0

        if score > 0.25:
            direction = State.BULLISH
        elif score < -0.25:
            direction = State.BEARISH
        else:
            direction = State.SIDEWAYS

        for tf, v in votes.items():
            if direction == State.BULLISH and v > 0:
                aligned.append(tf)
            elif direction == State.BEARISH and v < 0:
                aligned.append(tf)
            elif v != 0:
                conflicting.append(tf)

        mag = abs(score)
        conf = "HIGH" if mag >= 0.6 else "MEDIUM" if mag >= 0.35 else "LOW"
        reason = (f"HTF score {score:+.2f} ({direction.value}); "
                  f"aligned {aligned or '—'}; conflict {conflicting or '—'}.")
        b = Bias(direction, conf, score, aligned, conflicting, reason)
        log.info(b.reasoning)
        return b
