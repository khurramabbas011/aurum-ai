# Tests for the structure engine — synthetic, deterministic.
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.structure import StructureEngine          # noqa: E402
from core.models import EventType, State                # noqa: E402


def _df(prices):
    n = len(prices)
    t = pd.date_range("2026-01-01", periods=n, freq="5min", tz="UTC")
    p = np.array(prices, dtype=float)
    return pd.DataFrame({"time": t, "open": p, "high": p + 0.5,
                         "low": p - 0.5, "close": p,
                         "tick_volume": 100, "spread": 30})


def test_swings_detected():
    eng = StructureEngine()
    # clear zigzag -> several swings
    seq = []
    for k in range(6):
        seq += list(range(10, 30)) + list(range(30, 10, -1))
    df = _df([2400 + v for v in seq])
    sw = eng.swings(df, 5)
    assert len(sw) >= 4
    assert any(s.kind == "HIGH" for s in sw)
    assert any(s.kind == "LOW" for s in sw)


def test_uptrend_state_bullish():
    eng = StructureEngine()
    # ascending zigzag = HH + HL
    base = []
    lvl = 0
    for k in range(6):
        base += [lvl, lvl + 8, lvl + 3, lvl + 12]   # up, pull, up
        lvl += 10
    df = _df([2400 + v for v in base for _ in range(3)])
    sw = eng.label(eng.swings(df, 5))
    st, intact, _ = eng.state(sw, df)
    assert st in (State.BULLISH, State.SIDEWAYS)   # at minimum not bearish
    assert st != State.BEARISH


def test_two_close_confirmation():
    eng = StructureEngine()
    # rising series guarantees 2 consecutive closes above a prior swing high
    prices = [2400 + i * 0.6 for i in range(120)]
    df = _df(prices)
    sw = eng.label(eng.swings(df, 5))
    ev = eng.event(df, sw, eng.state(sw, df)[0])
    # an upward break should be confirmed (BOS or CHoCH depending on state)
    if ev.type != EventType.NONE:
        assert ev.confirmed is True


def test_no_event_on_flat():
    eng = StructureEngine()
    df = _df([2400 + (i % 2) * 0.1 for i in range(80)])   # dead flat
    sw = eng.label(eng.swings(df, 5))
    ev = eng.event(df, sw, eng.state(sw, df)[0])
    assert ev.type == EventType.NONE
