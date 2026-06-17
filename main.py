# ═══════════════════════════════════════════════════════════
# AURUM AI — FULL SYSTEM ENTRY POINT
#   python main.py backtest   — run the full pipeline on synthetic
#                               data with self-learning (no MT5)
#   python main.py analyze    — live MT5 structure + bias + signal
#   python main.py chart [TF] — write an HTML structure chart
#   python main.py live       — 24/5 loop (PAPER unless live enabled)
#   python main.py playbook   — print what the agent has learned
#
# Live order placement is OFF unless ENABLE_LIVE_TRADING=True
# (config_local.py) on a demo account. Risk rails always enforced.
# ═══════════════════════════════════════════════════════════

import sys
import time
import traceback

import config
from core.utils import get_logger, gmt_now
from analysis.structure import StructureEngine
from analysis.multi_tf import MultiTF
from strategy.signals import SignalEngine
from trading.risk import RiskEngine
from trading.manager import TradeManager
from learning.memory import Memory
from learning.playbook import Playbook
from reporting import reporter, chart

log = get_logger("main")

BANNER = r"""
╔══════════════════════════════════════════════════════════╗
║                     A U R U M   A I                      ║
║      Adaptive XAUUSD system · analysis → execution        ║
║        structure · signals · risk · self-learning         ║
╚══════════════════════════════════════════════════════════╝
"""


# ───────────────────────── helpers ─────────────────────────
def _synthetic_frames(seed=7, days=90):
    from data.replay_feed import SyntheticMarket
    return SyntheticMarket(seed=seed, minutes=60 * 24 * days).build()


def _live_feed():
    from data.mt5_feed import MT5Feed
    feed = MT5Feed()
    feed.connect()
    return feed


# ───────────────────────── commands ─────────────────────────
def cmd_backtest(args):
    seed = int(args[0]) if args else 7
    print(BANNER)
    log.info("Building synthetic XAUUSD market (seed=%d) ...", seed)
    frames = _synthetic_frames(seed=seed)
    mem = Memory()
    pb = Playbook()
    from backtest.engine import Backtester
    bt = Backtester(frames, base_tf="M5", playbook=pb, memory=mem, learn=True)
    stats = bt.run()
    print(reporter.backtest_report(stats, pb))
    mem.close()


def cmd_playbook(_args):
    print(BANNER)
    pb = Playbook()
    print(pb.summary())


def cmd_analyze(_args):
    print(BANNER)
    feed = _live_feed()
    struct, mtf = StructureEngine(), MultiTF()
    maps = {}
    for tf in config.TIMEFRAMES:
        df = feed.get_ohlcv(tf)
        if len(df) >= 30:
            maps[tf] = struct.analyze(tf, df)
    bias = mtf.bias(maps)
    for tf in config.TIMEFRAMES:
        if tf in maps:
            print(reporter.structure_report(maps[tf],
                                             bias if tf in config.HTF_BIAS_TFS else None))
    print(reporter.master_report(maps, bias))

    sig_eng = SignalEngine(Playbook())
    for tf in config.SIGNAL_TFS:
        if tf in maps:
            s = sig_eng.generate(tf, maps[tf], bias)
            if s:
                print(f"SIGNAL {tf}: {s.side.value} {s.setup.value} "
                      f"entry {s.entry} sl {s.sl} tp1 {s.tp1} "
                      f"(R:R {s.rr}, edge {s.edge_score:.2f})")
    feed.disconnect()


def cmd_chart(args):
    tf = args[0] if args else "M15"
    print(BANNER)
    struct, mtf = StructureEngine(), MultiTF()
    if config.needs_mt5():
        feed = _live_feed()
        frames = {t: feed.get_ohlcv(t) for t in config.TIMEFRAMES}
        feed.disconnect()
    else:
        log.info("No MT5 creds — charting synthetic data.")
        frames = _synthetic_frames()
    maps = {t: struct.analyze(t, frames[t]) for t in config.TIMEFRAMES
            if len(frames.get(t, [])) >= 30}
    bias = mtf.bias(maps)
    sig = SignalEngine(Playbook()).generate(tf, maps[tf], bias) if tf in maps else None
    path = chart.render(frames[tf], maps[tf], sig, bias)
    print(f"Chart written: {path}")
    print(f"Open it in a browser: file:///{path.replace(chr(92), '/')}")


def cmd_live(_args):
    print(BANNER)
    problems = config.validate()
    if problems:
        for p in problems:
            log.error("CONFIG: %s", p)
        sys.exit(1)
    feed = _live_feed()
    struct, mtf = StructureEngine(), MultiTF()
    pb = Playbook()
    mem = Memory()
    sig_eng = SignalEngine(pb)
    risk = RiskEngine()

    # choose broker
    if config.ENABLE_LIVE_TRADING:
        from trading.execution import MT5Broker
        broker = MT5Broker(feed)
        log.warning("LIVE TRADING ENABLED — real orders on demo=%s", feed.is_demo())
    else:
        from trading.execution import PaperBroker
        acct = feed.account_info()
        broker = PaperBroker(acct.get("balance", config.PAPER_START_BALANCE))
        log.info("PAPER mode — no real orders (set ENABLE_LIVE_TRADING to trade).")

    manager = TradeManager(broker)
    start_balance = broker.account().get("balance", config.PAPER_START_BALANCE)
    log.info("AURUM AI live loop — scan every %ds. Ctrl+C to stop.",
             config.SCAN_SECONDS)

    while True:
        try:
            maps = {}
            for tf in config.TIMEFRAMES:
                df = feed.get_ohlcv(tf)
                if len(df) >= 30:
                    maps[tf] = struct.analyze(tf, df)
            bias = mtf.bias(maps)

            # manage existing trades on the latest base bar
            base = feed.get_ohlcv(config.SIGNAL_TFS[0])
            if not base.empty:
                bar = base.iloc[-1]
                swl = float(base["low"].tail(10).min())
                swh = float(base["high"].tail(10).max())
                for pos in list(broker.open_positions()):
                    closed = manager.on_bar(pos.ticket, bar["high"], bar["low"],
                                            bar["close"], swl, swh)
                    if closed:
                        mem.log_trade(closed)
                        risk.record_result(closed.result == "WIN")
                        if len(mem.closed_trades()) % config.LEARN_AFTER_TRADES == 0:
                            pb.fit(mem.closed_trades())

            # hunt a new signal when flat
            if not broker.open_positions():
                for tf in config.SIGNAL_TFS:
                    if tf not in maps:
                        continue
                    s = sig_eng.generate(tf, maps[tf], bias)
                    if not s:
                        continue
                    acct = broker.account()
                    plan = risk.approve(s, acct["balance"], start_balance,
                                        len(broker.open_positions()), gmt_now())
                    mem.log_signal(s, plan.approved)
                    if plan.approved:
                        pos = broker.market_order(s.side, plan.lots, s.sl,
                                                  s.tp2, maps[tf].current_price,
                                                  s.setup.value)
                        manager.register(pos, s)
                        break
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("loop error: %s\n%s", e, traceback.format_exc())
        time.sleep(config.SCAN_SECONDS)

    mem.close()
    feed.disconnect()
    log.info("AURUM AI live loop stopped.")


COMMANDS = {"backtest": cmd_backtest, "analyze": cmd_analyze,
            "chart": cmd_chart, "live": cmd_live, "playbook": cmd_playbook}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "backtest"
    fn = COMMANDS.get(cmd)
    if not fn:
        print(f"Unknown command '{cmd}'. Use: {', '.join(COMMANDS)}")
        sys.exit(1)
    try:
        fn(sys.argv[2:])
    except Exception as exc:
        log.critical("FATAL: %s\n%s", exc, traceback.format_exc())
        sys.exit(1)
