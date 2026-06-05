# ═══════════════════════════════════════════════════════════
# AURUM AI — Step 1 · reporter.py
# Builds the per-timeframe structure report (Chapter 13) and
# the master multi-timeframe summary (Chapter 14).
# ═══════════════════════════════════════════════════════════

import config
from modules.utils import fmt_price, fmt_time, gmt_stamp

LINE = "═" * 55


def _swing_str(s):
    if not s:
        return "—"
    return f"{s.get('label','?')} {fmt_price(s['price'])} at {fmt_time(s['time'])}"


def _conflict(state, higher_state):
    """A timeframe conflicts if its state opposes the higher TF."""
    if higher_state in (None, "UNKNOWN", "SIDEWAYS") or \
       state in ("UNKNOWN", "SIDEWAYS"):
        return False
    return state != higher_state


def timeframe_report(a: dict, counts: dict, higher_tf: str,
                     higher_state: str) -> str:
    """One per-timeframe structure report in the Chapter 13 format."""
    tf = a["timeframe"]
    if a.get("state") == "UNKNOWN":
        return (f"\n{LINE}\nAURUM AI — STRUCTURE MAPPING REPORT\n"
                f"XAUUSD | {tf} | {gmt_stamp()} GMT\n{LINE}\n"
                f"MARKET STATE: UNKNOWN — {a.get('error','no data')}\n{LINE}")

    state = a["state"]
    ev = a.get("event", {})
    sw = a.get("sweep", {})
    pdz = a.get("premium_discount", {})
    lsh = a.get("last_swing_high")
    lsl = a.get("last_swing_low")
    psh = a.get("prev_swing_high")
    psl = a.get("prev_swing_low")

    seq = " → ".join(a.get("recent_labels", [])) or "—"
    conflict = _conflict(state, higher_state)

    # structure summary sentence
    if ev.get("type") in ("BOS", "CHoCH"):
        ev_txt = (f"Most recent event is a {ev['direction'].lower()} "
                  f"{ev['type']} at {fmt_price(ev['level'])} "
                  f"({ev['implication']}).")
    else:
        ev_txt = "No confirmed BOS/CHoCH on the visible structure."
    summary = (f"XAUUSD {tf} is {state}. {ev_txt} "
               f"Trend intact: {'yes' if a.get('trend_intact') else 'no'}. "
               f"Price {fmt_price(a.get('current_price'))} is in the "
               f"{pdz.get('zone','—')} zone of the current swing range.")

    return f"""
{LINE}
AURUM AI — STRUCTURE MAPPING REPORT
XAUUSD | {tf} | {gmt_stamp()} GMT
{LINE}

MARKET STATE: {state}

SWING POINTS IDENTIFIED:
  Most recent swing high: {_swing_str(lsh)}
  Most recent swing low : {_swing_str(lsl)}
  Previous swing high   : {_swing_str(psh)}
  Previous swing low    : {_swing_str(psl)}

TREND SEQUENCE:
  {seq}
  Trend intact: {'YES' if a.get('trend_intact') else 'NO'}

MOST RECENT STRUCTURAL EVENT:
  Event type : {ev.get('type','NONE')}
  Direction  : {ev.get('direction') or '—'}
  At price   : {fmt_price(ev.get('level'))}
  Confirmed  : {'YES (2-candle rule)' if ev.get('confirmed') else 'NO'}
  Implication: {ev.get('implication','—')}

ACTIVE STRUCTURAL LEVELS:
  Key resistance : {fmt_price(lsh['price']) if lsh else '—'}
  Key support    : {fmt_price(lsl['price']) if lsl else '—'}
  Last swing high: {fmt_price(lsh['price']) if lsh else '—'}
  Last swing low : {fmt_price(lsl['price']) if lsl else '—'}

LIQUIDITY ZONES:
  Buy-side liquidity resting at : {fmt_price(a.get('buy_side_liquidity'))}
  Sell-side liquidity resting at: {fmt_price(a.get('sell_side_liquidity'))}
  Recent sweep: {'YES at ' + fmt_price(sw['level']) + ' (' + str(sw.get('side')) + ')' if sw.get('detected') else 'NO'}

OBJECTS DRAWN ON CHART:
  Swing labels    : {counts.get('labels',0)}
  Trendlines      : {counts.get('trendlines',0)}
  BOS/CHoCH+swing lines: {counts.get('lines',0)}
  Sweep/range boxes: {counts.get('boxes',0)}
  Notes           : {counts.get('notes',0)}
  All tagged: {config.OBJ_PREFIX}_{tf}_*

CURRENT PRICE: {fmt_price(a.get('current_price'))}
PRICE LOCATION: {pdz.get('zone','—')}

STRUCTURE SUMMARY:
  {summary}

CONFLICTS WITH HIGHER TF ({higher_tf or 'none'}): {'YES' if conflict else 'NO'}
  {('This ' + tf + ' ' + state + ' read opposes the higher ' + higher_tf + ' ' + str(higher_state) + ' structure — treat it as a retracement, not a reversal.') if conflict else '—'}
{LINE}"""


def master_summary(results: list) -> str:
    """The Chapter 14 master multi-timeframe overview."""
    by_tf = {r["timeframe"]: r for r in results}
    d1 = by_tf.get("D1", {})
    master = d1.get("state", "UNKNOWN")

    align_lines = []
    agree, conflict = [], []
    for tf in config.TIMEFRAMES:
        r = by_tf.get(tf, {})
        st = r.get("state", "UNKNOWN")
        if tf == "D1":
            tag = "(master bias)"
        elif _conflict(st, master):
            tag = "[conflict]"
            conflict.append(tf)
        else:
            tag = "[aligned]"
            if st == master and master not in ("SIDEWAYS", "UNKNOWN"):
                agree.append(tf)
        align_lines.append(f"  {tf:<4}: {st:<9} {tag}")

    # dominant bias
    states = [by_tf.get(tf, {}).get("state") for tf in config.TIMEFRAMES]
    bull = states.count("BULLISH")
    bear = states.count("BEARISH")
    if bull > bear and master in ("BULLISH", "SIDEWAYS"):
        dominant = "bullish"
    elif bear > bull and master in ("BEARISH", "SIDEWAYS"):
        dominant = "bearish"
    else:
        dominant = "mixed"

    # key levels from D1 / H4
    h4 = by_tf.get("H4", {})
    res = (d1.get("last_swing_high") or h4.get("last_swing_high") or {})
    sup = (d1.get("last_swing_low") or h4.get("last_swing_low") or {})

    one_line = (f"XAUUSD master bias is {master} from D1; "
                f"{len(agree)} timeframe(s) aligned, "
                f"{len(conflict)} retracing/conflicting "
                f"({', '.join(conflict) if conflict else 'none'}).")

    return f"""
{LINE}
AURUM AI — MASTER STRUCTURE OVERVIEW
XAUUSD | ALL TIMEFRAMES | {gmt_stamp()} GMT
{LINE}

TIMEFRAME ALIGNMENT:
{chr(10).join(align_lines)}

DOMINANT BIAS (from D1 down): {dominant}

WHERE THE TIMEFRAMES AGREE:
  {', '.join(agree) if agree else 'No timeframes strongly confirm the master bias.'}

WHERE THEY CONFLICT:
  {', '.join(conflict) if conflict else 'No conflicts — structure is coherent top-down.'}

KEY LEVELS ACROSS TIMEFRAMES:
  Major D1/H4 resistance: {fmt_price(res.get('price'))}
  Major D1/H4 support   : {fmt_price(sup.get('price'))}
  Most significant untapped liquidity: {fmt_price(d1.get('buy_side_liquidity') if master == 'BULLISH' else d1.get('sell_side_liquidity'))}

ONE-LINE STRUCTURAL READ:
  {one_line}
{LINE}"""
