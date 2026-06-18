# Tests for risk rails and the self-learning playbook.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config                                            # noqa: E402
from core.models import Side, Signal, SetupType          # noqa: E402
from core.utils import gmt_now                           # noqa: E402
from trading.risk import RiskEngine                      # noqa: E402
from learning.playbook import Playbook, bucket_key       # noqa: E402


def _sig(sl_pips=20.0, size=1.0):
    s = Signal(Side.BUY, SetupType.SWEEP_CHOCH, "M15", 2400.0, 2398.0,
               2404.0, 2406.0, 2.0, "test", created=gmt_now())
    s.features = {"sl_pips": sl_pips, "setup": "SWEEP_CHOCH",
                  "timeframe": "M15", "session": "LONDON",
                  "htf_aligned": 1, "pd_zone": "DISCOUNT"}
    s.size_factor = size
    return s


def test_risk_hard_cap_never_exceeded():
    r = RiskEngine()
    # even with a huge learned size_factor, risk% must clamp to the cap
    lots, risk_usd, risk_pct = r.position_size(10000, 20.0, size_factor=99)
    assert risk_pct <= config.ABSOLUTE_MAX_RISK + 1e-9


def test_daily_loss_kill_switch():
    r = RiskEngine()
    # drawdown beyond the configured MAX_DAILY_LOSS must halt trading
    bal = 10000 * (1 - config.MAX_DAILY_LOSS) - 1   # just past the limit
    plan = r.approve(_sig(), balance=bal, start_balance=10000,
                     open_positions=0, now=gmt_now())
    assert plan.approved is False
    assert "daily loss" in plan.reason


def test_max_positions_enforced():
    r = RiskEngine()
    plan = r.approve(_sig(), 10000, 10000,
                     open_positions=config.MAX_OPEN_POSITIONS, now=gmt_now())
    assert plan.approved is False


def test_playbook_suppresses_losing_bucket():
    pb = Playbook(path=os.path.join(config.BASE_DIR, "data_store",
                                    "test_playbook.json"))
    # synth: one bucket with consistently negative R, enough samples
    feats = {"setup": "SWEEP_CHOCH", "timeframe": "M15", "session": "ASIAN",
             "htf_aligned": 0, "pd_zone": "PREMIUM"}
    import json
    trades = [{"pnl_r": -1.0, "features": json.dumps(feats)} for _ in range(20)]
    pb.fit(trades)
    edge, size = pb.edge(feats)
    assert edge < config.MIN_EDGE_SCORE         # learned to avoid it
    # a never-seen bucket stays neutral (cold start safe)
    edge2, size2 = pb.edge({"setup": "BOS_CONT", "timeframe": "H1",
                            "session": "NY", "htf_aligned": 1,
                            "pd_zone": "DISCOUNT"})
    assert edge2 == 1.0 and size2 == 1.0
    os.remove(pb.path)


def test_bos_continuation_waits_for_retest():
    from core.models import (StructureMap, State, Swing, StructureEvent,
                             EventType, Bias, SetupType)
    from core.utils import gmt_now
    from strategy.signals import SignalEngine
    eng = SignalEngine(None)
    bias = Bias(direction=State.BEARISH, confidence="HIGH", score=-0.6)

    def mk(price):
        m = StructureMap(timeframe="M5")
        m.state = State.BEARISH
        m.current_price = price
        m.last_high = Swing(10, "HIGH", 2410.0, gmt_now())
        m.range_low = 2350.0
        # bearish BOS: broke below the old swing low at 2400
        m.event = StructureEvent(EventType.BOS, State.BEARISH, 2400.0,
                                 gmt_now(), True, "continuation")
        return m

    # price extended far below the broken level (2380) -> NO entry (chasing)
    assert eng.generate("M5", mk(2380.0), bias) is None
    # price retraced back UP to the broken level (~2400) -> retest entry fires
    sig = eng.generate("M5", mk(2400.5), bias)
    assert sig is not None and sig.setup == SetupType.BOS_CONTINUATION
    assert sig.side == Side.SELL


def test_unicorn_signal_fires_in_zone():
    from core.models import StructureMap, State, Swing, Zone, Bias, SetupType
    from core.utils import gmt_now
    from strategy.signals import SignalEngine
    m = StructureMap(timeframe="M15")
    m.state = State.BULLISH
    m.current_price = 2400.0
    m.last_high = Swing(10, "HIGH", 2410.0, gmt_now())
    m.range_high = 2410.0
    m.breaker = Zone(State.BULLISH, 2402.0, 2396.0, "breaker", gmt_now())
    m.unicorn = Zone(State.BULLISH, 2401.0, 2398.0, "unicorn", gmt_now())
    bias = Bias(direction=State.BULLISH, confidence="HIGH", score=0.7)
    sig = SignalEngine(None).generate("M15", m, bias)
    assert sig is not None
    assert sig.setup == SetupType.UNICORN
    assert sig.side == Side.BUY
    assert sig.rr >= 2.0


def test_unicorn_skipped_when_price_outside_zone():
    from core.models import StructureMap, State, Swing, Zone, Bias
    from core.utils import gmt_now
    from strategy.signals import SignalEngine
    m = StructureMap(timeframe="M15")
    m.state = State.BULLISH
    m.current_price = 2450.0          # far above the zone
    m.last_high = Swing(10, "HIGH", 2460.0, gmt_now())
    m.range_high = 2460.0
    m.breaker = Zone(State.BULLISH, 2402.0, 2396.0, "breaker", gmt_now())
    m.unicorn = Zone(State.BULLISH, 2401.0, 2398.0, "unicorn", gmt_now())
    bias = Bias(direction=State.BULLISH, confidence="HIGH", score=0.7)
    sig = SignalEngine(None).generate("M15", m, bias)
    # no unicorn (price away) and no sweep/BOS data -> no signal
    assert sig is None


def test_venom_fires_on_aggressive_strike():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from core.models import (StructureMap, State, Swing, FVG, Sweep,
                             StructureEvent, EventType, Bias, SetupType)
    from strategy.signals import SignalEngine
    now = datetime(2026, 6, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))  # no SB
    m = StructureMap(timeframe="M5")
    m.state = State.BULLISH
    m.current_price = 2400.0
    m.last_high = Swing(10, "HIGH", 2412.0, now)
    m.range_high = 2412.0
    m.sweep = Sweep(True, "SELL_SIDE", 2395.0, now, wick_pips=10.0)   # big strike
    m.event = StructureEvent(EventType.CHOCH, State.BULLISH, 2398.0, now,
                             True, "reversal")
    m.fvgs = [FVG(State.BULLISH, 2402.0, 2398.0, now, filled=False)]
    bias = Bias(direction=State.BULLISH, confidence="HIGH", score=0.7)
    sig = SignalEngine(None).generate("M5", m, bias, now=now)
    assert sig is not None and sig.setup == SetupType.VENOM
    assert sig.side == Side.BUY and sig.rr >= 2.0


def test_venom_skipped_on_small_strike():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from core.models import (StructureMap, State, Swing, FVG, Sweep,
                             StructureEvent, EventType, Bias, SetupType)
    from strategy.signals import SignalEngine
    now = datetime(2026, 6, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    m = StructureMap(timeframe="M5")
    m.state = State.BULLISH
    m.current_price = 2400.0
    m.last_high = Swing(10, "HIGH", 2412.0, now)
    m.range_high = 2412.0
    m.sweep = Sweep(True, "SELL_SIDE", 2399.0, now, wick_pips=3.0)    # too small
    m.event = StructureEvent(EventType.CHOCH, State.BULLISH, 2398.0, now,
                             True, "reversal")
    m.fvgs = [FVG(State.BULLISH, 2402.0, 2398.0, now, filled=False)]
    bias = Bias(direction=State.BULLISH, confidence="HIGH", score=0.7)
    sig = SignalEngine(None).generate("M5", m, bias, now=now)
    # small strike -> not Venom; falls through to sweep+CHoCH instead
    assert sig is not None and sig.setup != SetupType.VENOM


def test_silver_bullet_fires_in_window():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from core.models import StructureMap, State, Swing, FVG, Bias, SetupType
    from strategy.signals import SignalEngine
    # 10:30 New York = inside the AM Silver Bullet window
    now = datetime(2026, 6, 18, 10, 30, tzinfo=ZoneInfo("America/New_York"))
    m = StructureMap(timeframe="M5")
    m.state = State.BULLISH
    m.current_price = 2400.0
    m.last_high = Swing(10, "HIGH", 2412.0, now)
    m.range_high = 2412.0
    m.fvgs = [FVG(State.BULLISH, 2402.0, 2398.0, now, filled=False)]
    bias = Bias(direction=State.BULLISH, confidence="HIGH", score=0.7)
    sig = SignalEngine(None).generate("M5", m, bias, now=now)
    assert sig is not None and sig.setup == SetupType.SILVER_BULLET
    assert sig.side == Side.BUY and sig.rr >= 2.0


def test_silver_bullet_skipped_outside_window():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from core.models import StructureMap, State, Swing, FVG, Bias
    from strategy.signals import SignalEngine
    # 08:00 New York = NOT a Silver Bullet window
    now = datetime(2026, 6, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    m = StructureMap(timeframe="M5")
    m.state = State.BULLISH
    m.current_price = 2400.0
    m.last_high = Swing(10, "HIGH", 2412.0, now)
    m.range_high = 2412.0
    m.fvgs = [FVG(State.BULLISH, 2402.0, 2398.0, now, filled=False)]
    bias = Bias(direction=State.BULLISH, confidence="HIGH", score=0.7)
    sig = SignalEngine(None).generate("M5", m, bias, now=now)
    assert sig is None        # no SB outside window, no other setup data


def test_playbook_favours_winning_bucket():
    pb = Playbook(path=os.path.join(config.BASE_DIR, "data_store",
                                    "test_playbook2.json"))
    feats = {"setup": "BOS_CONT", "timeframe": "M15", "session": "LONDON",
             "htf_aligned": 1, "pd_zone": "DISCOUNT"}
    import json
    trades = [{"pnl_r": 2.0, "features": json.dumps(feats)} for _ in range(20)]
    pb.fit(trades)
    edge, size = pb.edge(feats)
    assert edge > 1.0 and size >= 1.0
    os.remove(pb.path)
