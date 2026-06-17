# AURUM AI — Adaptive XAUUSD Trading System

A modular Gold (XAUUSD) trading system built on Smart-Money / ICT market
structure. It runs the full pipeline — **market analysis → signals → risk →
execution** — and includes a **self-learning layer** that studies its own
trade history and adapts. It runs fully offline (synthetic/replay backtest)
or live against MetaTrader 5.

> **Safety first.** Live order placement is **OFF by default**. The system
> trades on paper until you deliberately set `ENABLE_LIVE_TRADING = True`
> (and, by default, only on a **demo** account). Hard risk rails are always
> enforced and the learning layer can only tune *within* them — never widen
> them. This is software for research/education on your own account; it is
> not financial advice.

---

## What it does

```
data feed ─┐
           ├─► structure engine ─► multi-TF bias ─► signals ─► risk ─► execution
MT5 / replay┘        │                                 ▲                   │
                     └──────────── HTML chart           │              trade manager
                                                         │                   │
                                       learning playbook ◄── memory (SQLite) ◄┘
                                       (adapts from outcomes)
```

- **Structure engine** (`analysis/structure.py`) — swings with per-timeframe
  lookback, HH/HL/LH/LL, market state, **BOS / CHoCH** (strict 2-close rule),
  **liquidity sweeps**, fair-value gaps, premium/discount.
- **Multi-timeframe bias** (`analysis/multi_tf.py`) — weighted top-down vote
  (D1 heaviest) → a continuous bias score in [-1, +1].
- **Signals** (`strategy/signals.py`) — two ICT setups: *sweep + CHoCH
  reversal* and *BOS continuation*; structural SL/TP; min 1:2 R:R; must align
  with HTF bias.
- **Risk** (`trading/risk.py`) — position sizing + hard rails: 1% max risk,
  2% daily-loss kill switch, max 1 position, max trades/day, consecutive-loss
  pause.
- **Execution** (`trading/execution.py`) — one interface, two backends:
  `PaperBroker` (sim) and `MT5Broker` (real, gated by the safety flags).
- **Trade manager** (`trading/manager.py`) — TP1 partial close, move to
  breakeven, structural trailing stop, full exit.
- **Self-learning** (`learning/`) — every trade is recorded with feature
  context (setup × timeframe × session × HTF-alignment × premium/discount).
  Every N trades the **playbook** re-fits a recency-weighted expectancy per
  bucket and emits an `edge_score` + `size_factor`. The signal layer consults
  it: losing buckets get suppressed, winning buckets get scaled up. Cold start
  is safe — thin/unknown buckets stay neutral and trade the base rules.
- **Backtest** (`backtest/engine.py`) — event-driven, walks the data bar by
  bar (no look-ahead) and re-fits the playbook as it goes.
- **HTML chart** (`reporting/chart.py`) — candles + structure in a browser, no
  MQL5 needed. Optional live drawing on the MT5 chart via `mt5/AURUM_HUD.mq5`.

## Quick start

```bash
pip install -r requirements.txt          # MetaTrader5, pandas, numpy, pytz

python main.py backtest                  # full pipeline + self-learning, no MT5
python main.py chart M15                 # write an HTML structure chart
python main.py playbook                  # show what it has learned
python main.py analyze                   # live MT5 structure + bias + signal (needs MT5)
python main.py live                      # 24/5 loop (PAPER unless you enable live)

python -m pytest -q                      # run the test suite
```

No MT5? `backtest`, `chart`, `playbook` all run on built-in synthetic data.

## Going live (only when you mean it)

1. Copy `config_local.example.py` → `config_local.py`, fill in your **demo**
   MT5 login / password / server / path.
2. Open MT5, log in, enable algo trading, add XAUUSD to Market Watch.
3. In `config_local.py` set `ENABLE_LIVE_TRADING = True` (kept off by default).
   `REQUIRE_DEMO_ACCOUNT = True` blocks live orders on a real account.
4. `python main.py live`

`config_local.py` is git-ignored — your credentials never reach the repo.

## Layout

```
config.py              settings + safety rails (+ local override)
main.py                CLI: backtest | analyze | chart | live | playbook
core/                  models (dataclasses) + utils
data/                  mt5_feed (live) · replay_feed (offline + synthetic)
analysis/              structure · multi_tf
strategy/              signals (consult the learned playbook)
trading/               risk · execution (paper/MT5) · manager
learning/              memory (SQLite) · playbook (adaptive weights)
backtest/              event-driven engine
reporting/             text reports · HTML chart
mt5/AURUM_HUD.mq5      optional MT5 chart overlay indicator
tests/                 structure + risk + learning tests
```

## Honest notes on "self-learning"

It is **statistical parameter learning from its own outcomes**, not magic and
not self-modifying code. It needs data: on a fresh account it trades the base
rules and only deviates once a bucket has enough samples to be trusted. It
cannot escape the risk rails. Past performance — especially on synthetic data —
does not predict the future. **Demo first, for a long time.**
