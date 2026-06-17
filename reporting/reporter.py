# ═══════════════════════════════════════════════════════════
# AURUM AI · reporting/reporter.py
# Human-readable text reports: per-timeframe structure, the
# master multi-TF bias, and a backtest summary.
# ═══════════════════════════════════════════════════════════

import config
from core.utils import fmt, gmt_stamp

LINE = "═" * 56


def structure_report(m, bias=None) -> str:
    ev = m.event
    sw = m.sweep
    seq = " → ".join(m.recent_labels) or "—"
    lh = f"{m.last_high.label} {fmt(m.last_high.price)}" if m.last_high else "—"
    ll = f"{m.last_low.label} {fmt(m.last_low.price)}" if m.last_low else "—"
    return f"""{LINE}
AURUM AI — STRUCTURE | XAUUSD {m.timeframe} | {gmt_stamp()} GMT
{LINE}
STATE         : {m.state.value}   (trend intact: {'yes' if m.trend_intact else 'no'})
SEQUENCE      : {seq}
LAST SWINGS   : high {lh} | low {ll}
EVENT         : {ev.type.value} {ev.direction.value if ev.direction else ''} @ {fmt(ev.level)} ({ev.implication})
SWEEP         : {('YES ' + str(sw.side) + ' @ ' + fmt(sw.level)) if sw.detected else 'no'}
FVGs (open)   : {len(m.fvgs)}
PRICE / ZONE  : {fmt(m.current_price)} / {m.pd_zone}
{('BIAS         : ' + bias.direction.value + ' (' + bias.confidence + ', ' + f'{bias.score:+.2f}' + ')') if bias else ''}
{LINE}"""


def master_report(maps: dict, bias) -> str:
    rows = []
    for tf in config.TIMEFRAMES:
        m = maps.get(tf)
        if not m:
            continue
        tag = ("master" if tf in config.HTF_BIAS_TFS[:1] else
               "aligned" if tf in bias.aligned_tfs else
               "conflict" if tf in bias.conflicting_tfs else "—")
        rows.append(f"  {tf:<4}: {m.state.value:<9} {tag}")
    return f"""{LINE}
AURUM AI — MASTER BIAS | XAUUSD | {gmt_stamp()} GMT
{LINE}
{chr(10).join(rows)}

DIRECTION : {bias.direction.value}   CONFIDENCE: {bias.confidence}   SCORE: {bias.score:+.2f}
{bias.reasoning}
{LINE}"""


def backtest_report(stats: dict, playbook=None) -> str:
    s = stats
    out = f"""{LINE}
AURUM AI — BACKTEST RESULT
{LINE}
Trades         : {s['trades']}   (W {s['wins']} / L {s['losses']})
Win rate       : {s['win_rate']}%
Net            : ${s['net_usd']}   ({s['net_r']:+}R, avg {s['avg_r']:+}R/trade)
Profit factor  : {s['profit_factor']}
Max drawdown   : ${s['max_drawdown_usd']}
Balance        : ${s['start_balance']} → ${s['end_balance']}
{LINE}"""
    if playbook:
        out += "\n" + playbook.summary() + "\n" + LINE
    return out
