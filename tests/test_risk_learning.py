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
    plan = r.approve(_sig(), balance=9700, start_balance=10000,
                     open_positions=0, now=gmt_now())   # -3% > 2% limit
    assert plan.approved is False
    assert "daily loss" in plan.reason


def test_max_one_position():
    r = RiskEngine()
    plan = r.approve(_sig(), 10000, 10000, open_positions=1, now=gmt_now())
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
