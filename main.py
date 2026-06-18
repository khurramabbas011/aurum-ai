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


def _write_snapshot(broker, feed, maps, bias, mode, last_signal, mem, pb,
                    start_balance, thoughts=None):
    """Persist live state to snapshot.json so the Streamlit dashboard
    (separate process) can render without its own MT5 connection."""
    import json
    try:
        price = feed.price()
        acct = broker.account()
        daily = mem.closed_trades()
        wins = sum(1 for t in daily if t["result"] == "WIN")
        from core.utils import silver_bullet_window
        snap = {
            "updated": gmt_now().isoformat(),
            "mode": mode, "symbol": config.SYMBOL,
            "sb_window": silver_bullet_window(),
            "bid": price.get("bid"), "ask": price.get("ask"),
            "spread_pips": price.get("spread_pips"),
            "account": acct,
            "start_balance": start_balance,
            "bias": {"direction": bias.direction.value, "score": bias.score,
                     "confidence": bias.confidence,
                     "aligned": bias.aligned_tfs,
                     "conflicting": bias.conflicting_tfs,
                     "reasoning": bias.reasoning},
            "timeframes": {tf: {
                "state": m.state.value,
                "event": f"{m.event.type.value} {m.event.direction.value}"
                         if m.event.direction else m.event.type.value,
                "sweep": bool(m.sweep.detected),
                "unicorn": bool(m.unicorn),
                "pd_zone": m.pd_zone,
                "price": m.current_price} for tf, m in maps.items()},
            "positions": [{"ticket": p.ticket, "side": p.side.value,
                           "entry": p.entry, "lots": p.lots, "sl": p.sl,
                           "tp": p.tp, "profit": round(p.profit, 2)}
                          for p in broker.open_positions()],
            "trades_total": len(daily),
            "wins": wins,
            "win_rate": round(wins / len(daily) * 100, 1) if daily else 0.0,
            "net_r": round(sum(t["pnl_r"] or 0 for t in daily), 2),
            "last_signal": last_signal,
            "playbook": pb.meta,
            "thoughts": thoughts or [],
        }
        import os as _os
        _os.makedirs(_os.path.dirname(config.SNAPSHOT_FILE), exist_ok=True)
        tmp = config.SNAPSHOT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, default=str)
        _os.replace(tmp, config.SNAPSHOT_FILE)
    except Exception as e:
        log.debug("snapshot write skipped: %s", e)


# ───────────────────────── commands ─────────────────────────
def cmd_backtest(args):
    seed = int(args[0]) if args else 7
    print(BANNER)
    log.info("Building synthetic XAUUSD market (seed=%d) ...", seed)
    frames = _synthetic_frames(seed=seed)
    mem = Memory(config.BACKTEST_DB_PATH)   # keep backtest stats out of live.db
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
    import collections
    from core.notify import Discord
    discord = Discord()
    mode = "LIVE (demo orders)" if config.ENABLE_LIVE_TRADING else "PAPER"
    start_balance = broker.account().get("balance", config.PAPER_START_BALANCE)
    discord.startup(mode, broker.account(), config.SYMBOL)
    last_signal = None
    thoughts = collections.deque(maxlen=40)   # live-thinking feed for dashboard

    def think(msg):
        thoughts.append(f"{gmt_now().strftime('%H:%M:%S')} · {msg}")

    log.info("AURUM AI live loop [%s] — scan every %ds. Ctrl+C to stop.",
             mode, config.SCAN_SECONDS)
    think(f"engine online [{mode}] — watching {config.SYMBOL}")

    while True:
        try:
            maps = {}
            for tf in config.TIMEFRAMES:
                df = feed.get_ohlcv(tf)
                if len(df) >= 30:
                    maps[tf] = struct.analyze(tf, df)
            bias = mtf.bias(maps)
            price = feed.price()
            n_open = len(broker.open_positions())
            think(f"bias {bias.direction.value} ({bias.score:+.2f}) · "
                  f"px {price.get('bid')} · pos {n_open}/{config.MAX_OPEN_POSITIONS}")

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
                        think(f"🏁 CLOSE #{closed.ticket} {closed.setup} "
                              f"{closed.result} {closed.pnl_r:+}R")
                        discord.trade_close(closed)
                        if len(mem.closed_trades()) % config.LEARN_AFTER_TRADES == 0:
                            pb.fit(mem.closed_trades())
                            think("↻ self-learning: playbook refit")

            # hunt setups — allow several concurrent (different setup/tf/side);
            # never stack duplicates of the same setup signature
            active_sigs = manager.signatures()
            for tf in config.SIGNAL_TFS:
                if len(broker.open_positions()) >= config.MAX_OPEN_POSITIONS:
                    think("at max positions — not opening more")
                    break
                if tf not in maps:
                    continue
                s = sig_eng.generate(tf, maps[tf], bias)
                if sig_eng.last_reason != "no setup":
                    think(f"{tf}: {sig_eng.last_reason}")   # the bot's reasoning
                if not s:
                    continue
                key = (tf, s.side.value, s.setup.value)
                if key in active_sigs:          # same setup already running
                    think(f"{tf}: {s.setup.value} already open — skip dup")
                    continue
                acct = broker.account()
                plan = risk.approve(s, acct["balance"], start_balance,
                                    len(broker.open_positions()), gmt_now())
                mem.log_signal(s, plan.approved)
                last_signal = {"tf": tf, "side": s.side.value,
                               "setup": s.setup.value, "entry": s.entry,
                               "sl": s.sl, "tp1": s.tp1, "rr": s.rr,
                               "edge": s.edge_score,
                               "approved": plan.approved,
                               "reason": plan.reason,
                               "time": gmt_now().isoformat()}
                if plan.approved:
                    pos = broker.market_order(s.side, plan.lots, s.sl,
                                              s.tp2, maps[tf].current_price,
                                              s.setup.value)
                    # re-anchor SL/TP to the ACTUAL fill so every trade is
                    # exactly FIXED_SL_PIPS / FIXED_TP_PIPS (kills slippage drift)
                    if config.USE_FIXED_SL_TP and pos:
                        risk = config.FIXED_SL_PIPS * config.PIP_SIZE
                        rew = config.FIXED_TP_PIPS * config.PIP_SIZE
                        if s.side.value == "BUY":
                            nsl, ntp = round(pos.entry - risk, 2), round(pos.entry + rew, 2)
                        else:
                            nsl, ntp = round(pos.entry + risk, 2), round(pos.entry - rew, 2)
                        broker.modify(pos.ticket, sl=nsl, tp=ntp)
                        pos.sl, pos.tp = nsl, ntp
                        s.sl, s.tp1, s.tp2 = nsl, ntp, ntp
                    manager.register(pos, s)
                    active_sigs.add(key)
                    think(f"⚡ OPEN {s.side.value} {s.setup.value} {tf} "
                          f"@ {pos.entry} SL {pos.sl} TP {pos.tp} ({plan.lots} lots)")
                    discord.trade_open(s.side.value, s.setup.value, tf,
                                       s.entry, s.sl, s.tp1, s.tp2, s.rr,
                                       plan.lots, s.edge_score)
                else:
                    think(f"✖ {tf} {s.setup.value} blocked: {plan.reason}")

            _write_snapshot(broker, feed, maps, bias, mode, last_signal,
                            mem, pb, start_balance, list(thoughts))
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("loop error: %s\n%s", e, traceback.format_exc())
        time.sleep(config.SCAN_SECONDS)

    mem.close()
    feed.disconnect()
    log.info("AURUM AI live loop stopped.")


def cmd_dashboard(_args):
    """Launch the Streamlit dashboard (separate process)."""
    import subprocess
    app = os.path.join(config.BASE_DIR, "dashboard", "app.py")
    log.info("Launching dashboard -> http://localhost:8501")
    subprocess.run([sys.executable, "-m", "streamlit", "run", app,
                    "--server.headless=true", "--server.port=8501"],
                   cwd=config.BASE_DIR)


import os  # noqa: E402  (used by cmd_dashboard)

COMMANDS = {"backtest": cmd_backtest, "analyze": cmd_analyze,
            "chart": cmd_chart, "live": cmd_live, "playbook": cmd_playbook,
            "dashboard": cmd_dashboard}


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
