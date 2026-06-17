# ═══════════════════════════════════════════════════════════
# AURUM AI · backtest/engine.py
# Event-driven backtest that exercises the WHOLE pipeline on
# replay data: analysis → multi-TF bias → signal → risk →
# paper fill → trade management → learning. Walks the base
# timeframe bar by bar (no look-ahead) and periodically re-fits
# the playbook so you can SEE the self-learning take effect.
# ═══════════════════════════════════════════════════════════

import config
from analysis.multi_tf import MultiTF
from analysis.structure import StructureEngine
from core.utils import get_logger
from data.replay_feed import ReplayFeed
from strategy.signals import SignalEngine
from trading.execution import PaperBroker
from trading.manager import TradeManager
from trading.risk import RiskEngine

log = get_logger("backtest")


class Backtester:
    def __init__(self, frames, base_tf="M5", playbook=None, memory=None,
                 learn=True):
        self.feed = ReplayFeed(frames, base_tf)
        self.base_tf = base_tf
        self.struct = StructureEngine()
        self.mtf = MultiTF()
        self.signals = SignalEngine(playbook)
        self.risk = RiskEngine()
        self.broker = PaperBroker(config.PAPER_START_BALANCE)
        self.manager = TradeManager(self.broker)
        self.playbook = playbook
        self.memory = memory
        self.learn = learn and config.LEARNING_ENABLED
        self.start_balance = self.broker.balance
        self.trades: list = []
        self.equity_curve: list[float] = []
        # only analyze the timeframes the system actually consumes
        self._used_tfs = [tf for tf in config.TIMEFRAMES
                          if tf in set(config.HTF_BIAS_TFS) | set(config.SIGNAL_TFS)]
        self._htf_cache = {}
        self._htf_age = 10 ** 9

    def _maps(self):
        """Signal TFs every call; HTF maps cached + refreshed hourly
        (they barely move bar-to-bar — a big speedup with no real
        loss of fidelity)."""
        maps = {}
        self._htf_age += 1
        refresh_htf = self._htf_age >= 12        # ~hourly on M5 base
        if refresh_htf:
            self._htf_cache = {}
            self._htf_age = 0
        for tf in self._used_tfs:
            if tf in config.HTF_BIAS_TFS and not refresh_htf and tf in self._htf_cache:
                maps[tf] = self._htf_cache[tf]
                continue
            df = self.feed.get_ohlcv(tf, config.BAR_COUNT.get(tf))
            if len(df) >= 30:
                m = self.struct.analyze(tf, df)
                maps[tf] = m
                if tf in config.HTF_BIAS_TFS:
                    self._htf_cache[tf] = m
        return maps

    def run(self, warmup: int = 400, signal_every: int = 3) -> dict:
        n = len(self.feed)
        log.info("Backtest: %d base bars (%s), warmup %d", n, self.base_tf, warmup)
        self.feed.seek(warmup)
        i = warmup
        while i < n:
            base = self.feed.get_ohlcv(self.base_tf)
            if base.empty:
                if not self.feed.step():
                    break
                i += 1
                continue
            bar = base.iloc[-1]

            # 1) manage open trades against this bar
            for pos in list(self.broker.open_positions()):
                swl = float(base["low"].tail(10).min())
                swh = float(base["high"].tail(10).max())
                closed = self.manager.on_bar(pos.ticket, bar["high"], bar["low"],
                                             bar["close"], swl, swh)
                if closed:
                    self._record(closed)

            # 2) look for a new signal (throttled, only when flat)
            if i % signal_every == 0 and not self.broker.open_positions():
                # pass SIMULATED bar time so daily caps key off backtest
                # time, not wall clock
                self._maybe_enter(bar["time"])

            self.equity_curve.append(round(self.broker.equity, 2))
            if not self.feed.step():
                break
            i += 1

        return self._stats()

    def _maybe_enter(self, now):
        maps = self._maps()
        if self.base_tf not in maps:
            return
        bias = self.mtf.bias(maps)
        for tf in config.SIGNAL_TFS:
            m = maps.get(tf)
            if not m:
                continue
            sig = self.signals.generate(tf, m, bias, now=now)
            if not sig:
                continue
            plan = self.risk.approve(sig, self.broker.balance,
                                     self.start_balance,
                                     len(self.broker.open_positions()),
                                     now)
            if self.memory:
                self.memory.log_signal(sig, plan.approved)
            if not plan.approved:
                continue
            price = m.current_price
            pos = self.broker.market_order(sig.side, plan.lots, sig.sl,
                                           sig.tp2, price, sig.setup.value)
            self.manager.register(pos, sig)
            return

    def _record(self, closed):
        self.trades.append(closed)
        self.risk.record_result(closed.result == "WIN")
        if self.memory:
            self.memory.log_trade(closed)
        # self-learning: re-fit the playbook every N trades
        if self.learn and self.playbook and \
                len(self.trades) % config.LEARN_AFTER_TRADES == 0:
            rows = [t.to_row() for t in self.trades]
            self.playbook.fit(rows)
            log.info("↻ self-learning refit after %d trades", len(self.trades))

    def _stats(self) -> dict:
        t = self.trades
        wins = [x for x in t if x.result == "WIN"]
        losses = [x for x in t if x.result == "LOSS"]
        gross_w = sum(x.pnl_usd for x in wins)
        gross_l = abs(sum(x.pnl_usd for x in losses))
        peak = self.start_balance
        max_dd = 0.0
        for e in self.equity_curve:
            peak = max(peak, e)
            max_dd = max(max_dd, peak - e)
        return {
            "trades": len(t),
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / len(t) * 100, 1) if t else 0.0,
            "net_usd": round(self.broker.balance - self.start_balance, 2),
            "net_r": round(sum(x.pnl_r for x in t), 2),
            "avg_r": round(sum(x.pnl_r for x in t) / len(t), 3) if t else 0.0,
            "profit_factor": round(gross_w / gross_l, 2) if gross_l else 0.0,
            "max_drawdown_usd": round(max_dd, 2),
            "start_balance": round(self.start_balance, 2),
            "end_balance": round(self.broker.balance, 2),
        }
