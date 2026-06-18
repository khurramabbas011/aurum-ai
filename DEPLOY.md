# AURUM AI — 24/7 Deployment Guide

The system logs every trade to SQLite and surfaces win-rate / R / the
learning playbook on the dashboard. To accumulate that data continuously
it must run **non-stop on a Windows host** (the MetaTrader5 Python library
is Windows-only — it cannot run on Linux cloud servers).

## ⚠️ Why not a free Linux server?
`MetaTrader5` (pip) talks to a local MT5 **terminal** over Windows IPC.
Render / Railway / Fly.io / Replit / Oracle-AWS-GCP free tiers are Linux →
**MT5 will not connect there.** Don't waste time on them for this stack.

## Hosting options (ranked)

1. **Your own PC, 24/7 (free).**
   Keep it on, internet up, power plan = "never sleep". Simplest.

2. **Broker free VPS (Exness offers one).**
   Many brokers give a free Windows VPS if you keep a minimum balance or
   trade volume. RDP into it, install Python + MT5, copy this folder, run.
   Best free always-on option.

3. **Cheap Windows VPS (~$4–6/mo).**
   Contabo / Cheap-Windows-VPS / ForexVPS etc. Set-and-forget reliability.

> MT5's built-in "Virtual Server" hosts MQL5 EAs only — it cannot run this
> Python system.

## One-time setup on the host (Windows)

1. Install **MetaTrader 5**, log into your **demo** account, enable
   *Algo Trading*, add XAUUSD to Market Watch.
2. Install **Python 3.11+**.
3. Copy this `aurum_ai` folder onto the host.
4. `pip install -r requirements.txt`
5. Create `config_local.py` (copy `config_local.example.py`) with your MT5
   login / password / server / path. To place real demo orders, set
   `ENABLE_LIVE_TRADING = True` (keeps `REQUIRE_DEMO_ACCOUNT = True`).

## Run it 24/7

```
python supervisor.py            # live engine + dashboard, auto-restart on crash
python supervisor.py --no-dash  # engine only
```

Or just double-click **`start_aurum.bat`** (also relaunches the supervisor
itself if it ever dies).

### Auto-start on boot (so it survives a reboot)
Windows **Task Scheduler** → Create Task →
- Trigger: *At log on* (or *At startup*)
- Action: Start a program → `start_aurum.bat`
- Check *Run whether user is logged on or not*

Keep the MT5 terminal running (put it in Startup too, or enable
auto-login).

## Where the data lives
- `data_store/live.db`     — live trades (clean; backtest uses `backtest.db`)
- `data_store/playbook.json` — what the learning layer has learned
- `data_store/snapshot.json` — live state for the dashboard
- Dashboard: **http://localhost:8501** (win rate, net R, open positions,
  per-TF bias, the learned playbook)
- `logs/aurum_ai.log` — full activity log

## Reminder
Demo first, for weeks. The risk rails (1% max/trade, 2% daily kill switch,
max 1 position) are always enforced; the learning layer tunes only within
them.
