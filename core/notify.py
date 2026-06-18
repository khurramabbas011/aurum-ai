# ═══════════════════════════════════════════════════════════
# AURUM AI · core/notify.py
# Discord webhook alerts. Outbound only, fully non-blocking —
# a failed post is logged and swallowed so it can never stall
# or crash the trading loop. The webhook URL is a secret and
# lives in config_local.py (gitignored).
# ═══════════════════════════════════════════════════════════

import requests

import config
from core.utils import get_logger, fmt

log = get_logger("notify")


class Discord:
    def __init__(self):
        self.url = (getattr(config, "DISCORD_WEBHOOK_URL", "") or "").strip()
        self.enabled = (self.url.startswith("https://")
                        and "discord.com/api/webhooks/" in self.url)
        if self.enabled:
            log.info("Discord alerts ENABLED.")
        else:
            log.info("Discord alerts off (no webhook in config_local.py).")

    # ---------- raw send ----------
    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            r = requests.post(self.url,
                              json={"username": "AURUM AI", "content": text[:1900]},
                              timeout=10)
            if r.status_code not in (200, 204):
                log.warning("discord http %s: %s", r.status_code, r.text[:120])
                return False
            return True
        except Exception as e:
            log.warning("discord send failed: %s", e)
            return False

    # ---------- formatted events ----------
    def startup(self, mode: str, acct: dict, symbol: str):
        self.send(
            "🟢 **AURUM AI — ONLINE**\n"
            f"Mode: **{mode}**  ·  {symbol}\n"
            f"Balance: ${acct.get('balance')}  ·  Equity: ${acct.get('equity')}\n"
            "Setups: Unicorn · Silver Bullet · Venom · Sweep+CHoCH · BOS\n"
            "Scanning M15 / M5 / M1 …")

    def trade_open(self, side, setup, tf, entry, sl, tp1, tp2, rr, lots,
                   edge):
        arrow = "🟢" if side == "BUY" else "🔴"
        self.send(
            f"⚡ **OPEN {side} {arrow} {config_symbol()}**  ·  {setup} ({tf})\n"
            f"Entry `{fmt(entry)}`  SL `{fmt(sl)}`  "
            f"TP1 `{fmt(tp1)}`  TP2 `{fmt(tp2)}`\n"
            f"R:R 1:{rr}  ·  {lots} lots  ·  edge {edge:.2f}")

    def trade_close(self, closed):
        icon = "✅" if closed.result == "WIN" else \
               "❌" if closed.result == "LOSS" else "➖"
        self.send(
            f"{icon} **CLOSE {closed.result}**  ·  {closed.setup} "
            f"({closed.timeframe})\n"
            f"{closed.side.value if hasattr(closed.side,'value') else closed.side} "
            f"`{fmt(closed.entry)}` → `{fmt(closed.exit)}`  ·  "
            f"**{closed.pnl_r:+}R**  (${closed.pnl_usd})")

    def alert(self, text: str):
        self.send(f"⚠️ **AURUM AI** — {text}")


def config_symbol():
    return getattr(config, "SYMBOL", "XAUUSD")
