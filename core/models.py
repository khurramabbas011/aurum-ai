# ═══════════════════════════════════════════════════════════
# AURUM AI · core/models.py
# Typed data models shared across the whole system. Using
# dataclasses (not loose dicts) so every layer — analysis,
# strategy, risk, execution, learning, backtest — speaks the
# same language and the compiler catches mistakes early.
# ═══════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional


# ───────────────────────── enums ─────────────────────────
class State(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    SIDEWAYS = "SIDEWAYS"
    UNKNOWN = "UNKNOWN"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class EventType(str, Enum):
    BOS = "BOS"            # break of structure — continuation
    CHOCH = "CHoCH"        # change of character — reversal
    NONE = "NONE"


class SetupType(str, Enum):
    SWEEP_CHOCH = "SWEEP_CHOCH"      # liquidity sweep + CHoCH reversal
    BOS_CONTINUATION = "BOS_CONT"    # trend continuation on BOS retest


# ───────────────────────── market data ─────────────────────────
@dataclass(slots=True)
class Swing:
    """A confirmed fractal pivot."""
    index: int
    kind: str            # "HIGH" | "LOW"
    price: float
    time: datetime
    label: str = ""      # HH / HL / LH / LL / SH / SL


@dataclass(slots=True)
class StructureEvent:
    """A BOS or CHoCH, confirmed by the 2-close rule."""
    type: EventType = EventType.NONE
    direction: Optional[State] = None
    level: Optional[float] = None
    time: Optional[datetime] = None
    confirmed: bool = False
    implication: str = "—"            # continuation | reversal


@dataclass(slots=True)
class Sweep:
    """A single-candle liquidity grab (wick beyond, body back)."""
    detected: bool = False
    side: Optional[str] = None        # BUY_SIDE | SELL_SIDE
    level: Optional[float] = None
    time: Optional[datetime] = None
    wick_pips: float = 0.0


@dataclass(slots=True)
class FVG:
    """Fair value gap (3-candle imbalance)."""
    direction: State
    top: float
    bottom: float
    time: datetime
    filled: bool = False


@dataclass(slots=True)
class StructureMap:
    """Everything the analysis engine knows about ONE timeframe."""
    timeframe: str
    state: State = State.UNKNOWN
    trend_intact: bool = False
    lookback: int = 5
    bars: int = 0
    swings: list[Swing] = field(default_factory=list)
    recent_labels: list[str] = field(default_factory=list)
    last_high: Optional[Swing] = None
    last_low: Optional[Swing] = None
    prev_high: Optional[Swing] = None
    prev_low: Optional[Swing] = None
    event: StructureEvent = field(default_factory=StructureEvent)
    sweep: Sweep = field(default_factory=Sweep)
    fvgs: list[FVG] = field(default_factory=list)
    pd_zone: str = "—"                # PREMIUM | DISCOUNT | EQUILIBRIUM
    range_high: Optional[float] = None
    range_low: Optional[float] = None
    equilibrium: Optional[float] = None
    current_price: Optional[float] = None
    note: str = ""


@dataclass(slots=True)
class Bias:
    """Top-down multi-timeframe directional read."""
    direction: State = State.UNKNOWN
    confidence: str = "LOW"           # HIGH | MEDIUM | LOW
    score: float = 0.0                # -1.0 (bear) .. +1.0 (bull)
    aligned_tfs: list[str] = field(default_factory=list)
    conflicting_tfs: list[str] = field(default_factory=list)
    reasoning: str = ""


# ───────────────────────── strategy / trading ─────────────────────────
@dataclass(slots=True)
class Signal:
    """A tradeable setup the strategy proposes (pre-risk)."""
    side: Side
    setup: SetupType
    timeframe: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    rr: float                         # reward:risk to tp1
    reason: str = ""
    features: dict = field(default_factory=dict)   # for the learning layer
    created: Optional[datetime] = None
    # filled by the learning layer when it consults the playbook:
    edge_score: float = 0.0           # learned expectancy weight (0..2)
    size_factor: float = 1.0          # learned size multiplier


@dataclass(slots=True)
class TradePlan:
    """A Signal that passed risk — ready to send to execution."""
    signal: Signal
    lots: float
    risk_usd: float
    risk_pct: float
    sl_pips: float
    approved: bool = True
    reason: str = ""


@dataclass(slots=True)
class Position:
    """An open position (live MT5 or paper)."""
    ticket: int
    side: Side
    entry: float
    lots: float
    sl: float
    tp: float
    open_time: datetime
    setup: str = ""
    tp1_done: bool = False
    trail_anchor: Optional[float] = None
    profit: float = 0.0


@dataclass(slots=True)
class ClosedTrade:
    """A finished trade — the unit the learning layer studies."""
    ticket: int
    side: Side
    setup: str
    timeframe: str
    entry: float
    exit: float
    sl: float
    lots: float
    pnl_usd: float
    pnl_r: float                      # result in R multiples
    result: str                       # WIN | LOSS | BREAKEVEN
    open_time: datetime
    close_time: datetime
    bias: str = ""
    session: str = ""
    features: dict = field(default_factory=dict)
    reason: str = ""

    def to_row(self) -> dict:
        d = asdict(self)
        d["side"] = self.side.value if isinstance(self.side, Side) else self.side
        d["open_time"] = _iso(self.open_time)
        d["close_time"] = _iso(self.close_time)
        import json
        d["features"] = json.dumps(self.features, default=str)
        return d


def _iso(t):
    try:
        return t.isoformat()
    except Exception:
        return str(t)
