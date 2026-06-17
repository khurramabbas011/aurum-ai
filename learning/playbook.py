# ═══════════════════════════════════════════════════════════
# AURUM AI · learning/playbook.py
# THE SELF-LEARNING BRAIN (honest version).
#
# It studies the agent's OWN closed trades, buckets them by
# feature combinations (setup × timeframe × session × HTF-bias
# alignment × premium/discount), and computes a recency-weighted
# expectancy (avg R) per bucket. From that it produces a
# "playbook": an edge_score (0..2) and a size_factor per bucket.
#
# The signal layer consults this playbook:
#   • edge_score < MIN_EDGE_SCORE  -> skip the trade (learned to avoid)
#   • edge_score scales conviction; size_factor scales risk
#     (always clamped so it can NEVER exceed the hard risk rails)
#
# "Self-upgrade" = re-fitting this playbook every N trades.
# It is parameter learning, not self-modifying code. Cold start:
# with too little data a bucket defaults to neutral (edge 1.0).
# ═══════════════════════════════════════════════════════════

import json
import math
import os

import config
from core.utils import get_logger

log = get_logger("playbook")

NEUTRAL_EDGE = 1.0
SKIP_EDGE = 0.0


def bucket_key(features: dict) -> str:
    """Stable bucket id from the learning features of a trade/signal."""
    return "|".join(str(features.get(k, "?")) for k in
                    ("setup", "timeframe", "session", "htf_aligned", "pd_zone"))


class Playbook:
    """Loads/saves learned weights and answers edge queries."""

    def __init__(self, path: str = None):
        self.path = path or config.PLAYBOOK_FILE
        self.buckets: dict[str, dict] = {}
        self.meta = {"trades_fit": 0, "fitted_at": None, "overall_r": 0.0}
        self.load()

    # ---------- query (used by strategy) ----------
    def edge(self, features: dict) -> tuple[float, float]:
        """Return (edge_score, size_factor) for a prospective signal.

        Falls back gracefully: unknown / thin buckets -> neutral, so a
        cold agent trades the base rules and only deviates once it has
        statistically meaningful evidence.
        """
        if not config.LEARNING_ENABLED:
            return NEUTRAL_EDGE, 1.0
        b = self.buckets.get(bucket_key(features))
        if not b or b["n"] < config.LEARN_MIN_SAMPLES:
            return NEUTRAL_EDGE, 1.0
        return b["edge_score"], b["size_factor"]

    # ---------- fit (the self-upgrade) ----------
    def fit(self, trades: list[dict]):
        """Re-learn bucket expectancies from closed-trade history."""
        if not trades:
            return
        agg: dict[str, dict] = {}
        # recency weighting: newer trades count more (decay per age)
        m = len(trades)
        overall_num = overall_den = 0.0
        for age, t in enumerate(reversed(trades)):
            w = config.LEARN_DECAY ** age
            try:
                feats = json.loads(t.get("features") or "{}")
            except Exception:
                feats = {}
            key = bucket_key(feats)
            r = float(t.get("pnl_r") or 0.0)
            a = agg.setdefault(key, {"wsum": 0.0, "wn": 0.0, "n": 0,
                                     "wins": 0})
            a["wsum"] += w * r
            a["wn"] += w
            a["n"] += 1
            a["wins"] += 1 if r > 0 else 0
            overall_num += w * r
            overall_den += w

        buckets = {}
        for key, a in agg.items():
            exp_r = a["wsum"] / a["wn"] if a["wn"] else 0.0   # expectancy (R)
            win_rate = a["wins"] / a["n"] if a["n"] else 0.0
            buckets[key] = {
                "n": a["n"],
                "expectancy_r": round(exp_r, 3),
                "win_rate": round(win_rate, 3),
                "edge_score": round(self._edge_from_expectancy(exp_r, a["n"]), 3),
                "size_factor": round(self._size_from_expectancy(exp_r, a["n"]), 3),
            }
        self.buckets = buckets
        self.meta = {
            "trades_fit": m,
            "fitted_at": _now(),
            "overall_r": round(overall_num / overall_den, 3) if overall_den else 0.0,
        }
        self.save()
        strong = sorted(buckets.items(),
                        key=lambda kv: kv[1]["expectancy_r"], reverse=True)[:3]
        weak = [k for k, v in buckets.items()
                if v["edge_score"] < config.MIN_EDGE_SCORE]
        log.info("playbook refit on %d trades; overall %.2fR; "
                 "top=%s; suppressed=%d buckets",
                 m, self.meta["overall_r"],
                 [s[0] for s in strong], len(weak))

    @staticmethod
    def _edge_from_expectancy(exp_r: float, n: int) -> float:
        """Map expectancy(R) -> edge_score in [0, 2].

        Negative expectancy collapses toward 0 (skip). Positive grows
        toward 2. Confidence scales with sample size (more trades ->
        the score is trusted more, less shrinkage toward neutral).
        """
        raw = 1.0 + math.tanh(exp_r)           # exp_r=0 -> 1.0 neutral
        confidence = min(1.0, n / 15.0)         # ~15 trades = full trust
        return max(0.0, NEUTRAL_EDGE + (raw - NEUTRAL_EDGE) * confidence)

    @staticmethod
    def _size_from_expectancy(exp_r: float, n: int) -> float:
        """Size multiplier in [0.5, 1.5], confidence-scaled."""
        confidence = min(1.0, n / 15.0)
        base = 1.0 + max(-0.5, min(0.5, exp_r * 0.4)) * confidence
        return max(0.5, min(1.5, base))

    # ---------- persistence ----------
    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as fh:
                    d = json.load(fh)
                self.buckets = d.get("buckets", {})
                self.meta = d.get("meta", self.meta)
            except Exception as e:
                log.warning("playbook load failed: %s", e)

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"buckets": self.buckets, "meta": self.meta},
                          fh, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            log.warning("playbook save failed: %s", e)

    def summary(self) -> str:
        if not self.buckets:
            return "Playbook empty — trading base rules (cold start)."
        rows = sorted(self.buckets.items(),
                      key=lambda kv: kv[1]["expectancy_r"], reverse=True)
        lines = [f"Playbook — fit on {self.meta['trades_fit']} trades, "
                 f"overall {self.meta['overall_r']:+.2f}R:"]
        for k, v in rows[:8]:
            lines.append(f"  {k}  n={v['n']:>3}  "
                         f"exp={v['expectancy_r']:+.2f}R  "
                         f"win={v['win_rate']*100:.0f}%  "
                         f"edge={v['edge_score']:.2f}  size×{v['size_factor']:.2f}")
        return "\n".join(lines)


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
