# ═══════════════════════════════════════════════════════════
# AURUM AI · trading/execution.py
# Order routing with a hard safety gate. Two backends behind one
# interface so the backtester and the live loop share code:
#
#   PaperBroker  — simulated fills, used by backtest + paper live.
#   MT5Broker    — real MT5 orders, ONLY usable when
#                  ENABLE_LIVE_TRADING is True AND (if required)
#                  the account is a demo. Otherwise it refuses.
# ═══════════════════════════════════════════════════════════

import config
from core.models import Position, Side
from core.utils import get_logger, gmt_now

log = get_logger("execution")

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


class PaperBroker:
    """Simulated broker — no real orders. Deterministic fills."""

    def __init__(self, balance: float = None):
        self.balance = balance if balance is not None else config.PAPER_START_BALANCE
        self.equity = self.balance
        self._next = 1
        self.positions: dict[int, Position] = {}

    def market_order(self, side: Side, lots, sl, tp, price, setup="") -> Position:
        tk = self._next
        self._next += 1
        p = Position(tk, side, round(price, 2), lots, sl, tp, gmt_now(), setup)
        self.positions[tk] = p
        log.info("[paper] OPEN #%d %s %.2f lots @ %.2f sl=%.2f tp=%.2f",
                 tk, side.value, lots, price, sl, tp)
        return p

    def modify(self, ticket, sl=None, tp=None):
        p = self.positions.get(ticket)
        if not p:
            return False
        if sl is not None:
            p.sl = round(sl, 2)
        if tp is not None:
            p.tp = round(tp, 2)
        return True

    def close(self, ticket, price, fraction=1.0) -> float:
        p = self.positions.get(ticket)
        if not p:
            return 0.0
        lots = round(p.lots * fraction, 2)
        sign = 1 if p.side == Side.BUY else -1
        pnl = sign * (price - p.entry) * lots * 100.0   # $100 per $1 per lot
        # model trading cost (spread/commission) so paper/backtest is honest
        pnl -= config.SPREAD_COST_PIPS * config.PIP_SIZE * lots * 100.0
        self.balance += pnl
        self.equity = self.balance
        if fraction >= 1.0 or lots >= p.lots:
            del self.positions[ticket]
        else:
            p.lots = round(p.lots - lots, 2)
        log.info("[paper] CLOSE #%d frac=%.0f%% @ %.2f pnl=%.2f bal=%.2f",
                 ticket, fraction * 100, price, pnl, self.balance)
        return round(pnl, 2)

    def open_positions(self) -> list[Position]:
        return list(self.positions.values())

    def closed_info(self, ticket):
        return None      # paper closes are manager-driven; nothing external

    def account(self) -> dict:
        return {"balance": round(self.balance, 2),
                "equity": round(self.equity, 2), "demo": True}


class MT5Broker:
    """Real MT5 order routing — gated hard by config + demo check."""

    MAGIC = 990519

    def __init__(self, feed):
        self.feed = feed                 # MT5Feed (for symbol + price)
        if not config.ENABLE_LIVE_TRADING:
            raise RuntimeError("ENABLE_LIVE_TRADING is False — refusing live broker.")
        if config.REQUIRE_DEMO_ACCOUNT and not feed.is_demo():
            raise RuntimeError("REQUIRE_DEMO_ACCOUNT is True but account is LIVE — refusing.")
        log.warning("MT5Broker LIVE on %s (demo=%s)", config.SYMBOL, feed.is_demo())

    def _filling(self):
        info = mt5.symbol_info(config.SYMBOL)
        fm = info.filling_mode if info else 0
        if fm & 1:
            return mt5.ORDER_FILLING_FOK
        if fm & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def market_order(self, side: Side, lots, sl, tp, price, setup="") -> Position:
        t = mt5.symbol_info_tick(config.SYMBOL)
        is_buy = side == Side.BUY
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": config.SYMBOL,
               "volume": float(lots),
               "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
               "price": t.ask if is_buy else t.bid,
               "sl": float(sl), "tp": float(tp), "deviation": 30,
               "magic": self.MAGIC, "comment": f"AURUM {setup}"[:31],
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling()}
        r = mt5.order_send(req)
        if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"order failed: {getattr(r,'retcode',None)} "
                               f"{getattr(r,'comment','')}")
        # use the ACTUAL deal fill price (not the requested price) so
        # post-fill SL/TP anchoring is exact
        fill = getattr(r, "price", 0) or req["price"]
        return Position(r.order, side, fill, lots, sl, tp, gmt_now(), setup)

    def modify(self, ticket, sl=None, tp=None):
        for p in mt5.positions_get(symbol=config.SYMBOL) or []:
            if p.ticket == ticket:
                req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": config.SYMBOL,
                       "position": ticket,
                       "sl": float(sl) if sl is not None else p.sl,
                       "tp": float(tp) if tp is not None else p.tp,
                       "magic": self.MAGIC}
                r = mt5.order_send(req)
                return bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)
        return False

    def close(self, ticket, price=None, fraction=1.0) -> float:
        pos = next((p for p in (mt5.positions_get(symbol=config.SYMBOL) or [])
                    if p.ticket == ticket), None)
        if not pos:
            return 0.0
        t = mt5.symbol_info_tick(config.SYMBOL)
        is_buy = pos.type == mt5.POSITION_TYPE_BUY
        vol = round(pos.volume * fraction, 2) or pos.volume
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": config.SYMBOL,
               "position": ticket, "volume": min(vol, pos.volume),
               "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
               "price": t.bid if is_buy else t.ask, "deviation": 30,
               "magic": self.MAGIC, "comment": "AURUM close",
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling()}
        r = mt5.order_send(req)
        return pos.profit if (r and r.retcode == mt5.TRADE_RETCODE_DONE) else 0.0

    def open_positions(self) -> list[Position]:
        out = []
        for p in mt5.positions_get(symbol=config.SYMBOL) or []:
            if p.magic != self.MAGIC:
                continue
            out.append(Position(
                p.ticket, Side.BUY if p.type == mt5.POSITION_TYPE_BUY else Side.SELL,
                p.price_open, p.volume, p.sl, p.tp, gmt_now(), p.comment,
                profit=p.profit))
        return out

    def closed_info(self, ticket):
        """Realized result for a position MT5 already closed (SL/TP),
        summed from its history deals. None if not found yet."""
        import datetime as dt
        deals = mt5.history_deals_get(
            dt.datetime.now() - dt.timedelta(days=3),
            dt.datetime.now() + dt.timedelta(minutes=1))
        if not deals:
            return None
        dz = [d for d in deals if getattr(d, "position_id", None) == ticket]
        if not dz:
            return None
        profit = sum(d.profit + d.swap + d.commission for d in dz)
        return {"exit": dz[-1].price, "profit": round(profit, 2)}

    def account(self) -> dict:
        return self.feed.account_info()
