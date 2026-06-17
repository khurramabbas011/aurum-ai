# ═══════════════════════════════════════════════════════════
# AURUM AI · trading/risk.py
# The gatekeeper. Position sizing + hard rails that the learning
# layer can NEVER widen. Every signal passes through approve()
# before any order — live or paper.
# ═══════════════════════════════════════════════════════════

import config
from core.models import Signal, TradePlan
from core.utils import get_logger

log = get_logger("risk")

PIP_VALUE_PER_LOT = 10.0    # XAUUSD: ~$10 per pip per 1.0 lot


class RiskEngine:
    def __init__(self):
        self.consecutive_losses = 0
        self.trades_today = 0
        self.day = None

    def _roll_day(self, now):
        d = now.date()
        if self.day != d:
            self.day = d
            self.trades_today = 0

    def position_size(self, balance: float, sl_pips: float,
                      size_factor: float = 1.0) -> tuple[float, float, float]:
        """Return (lots, risk_usd, risk_pct). Risk is clamped to the
        hard cap regardless of the learned size_factor."""
        risk_pct = config.RISK_PER_TRADE * max(0.5, min(1.5, size_factor))
        risk_pct = min(risk_pct, config.ABSOLUTE_MAX_RISK)   # HARD CAP
        risk_usd = balance * risk_pct
        if sl_pips <= 0:
            return 0.0, 0.0, risk_pct
        lots = risk_usd / (sl_pips * PIP_VALUE_PER_LOT)
        lots = max(0.01, round(lots, 2))
        actual = lots * sl_pips * PIP_VALUE_PER_LOT
        return lots, round(actual, 2), round(risk_pct, 4)

    def approve(self, sig: Signal, balance: float, start_balance: float,
                open_positions: int, now) -> TradePlan:
        self._roll_day(now)
        sl_pips = sig.features.get("sl_pips") or abs(sig.entry - sig.sl) / config.PIP_SIZE

        def deny(reason):
            return TradePlan(sig, 0.0, 0.0, 0.0, sl_pips, False, reason)

        # daily loss kill switch
        if start_balance and (start_balance - balance) / start_balance >= config.MAX_DAILY_LOSS:
            return deny("daily loss limit hit — trading halted for the day")
        if open_positions >= config.MAX_OPEN_POSITIONS:
            return deny(f"max {config.MAX_OPEN_POSITIONS} open position(s)")
        if self.trades_today >= config.MAX_TRADES_DAY:
            return deny(f"max {config.MAX_TRADES_DAY} trades/day reached")
        if self.consecutive_losses >= config.MAX_CONSEC_LOSSES:
            return deny(f"{self.consecutive_losses} consecutive losses — paused")
        if sl_pips <= 0:
            return deny("invalid stop distance")

        lots, risk_usd, risk_pct = self.position_size(
            balance, sl_pips, sig.size_factor)
        if lots <= 0:
            return deny("computed lot size 0")
        return TradePlan(sig, lots, risk_usd, risk_pct, round(sl_pips, 1),
                         True, "approved")

    def record_result(self, won: bool):
        self.trades_today += 1
        self.consecutive_losses = 0 if won else self.consecutive_losses + 1
