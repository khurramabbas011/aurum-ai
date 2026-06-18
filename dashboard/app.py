# ═══════════════════════════════════════════════════════════
# AURUM AI · dashboard/app.py
# Streamlit control dashboard. Reads the live snapshot.json the
# trading loop writes + the SQLite memory — so it never opens a
# second MT5 connection. Run it:
#     streamlit run dashboard/app.py
# (or:  python main.py dashboard)
# ═══════════════════════════════════════════════════════════

import json
import os
import sqlite3
import sys
import time
from html import escape as html_escape

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

st.set_page_config(page_title="AURUM AI", page_icon="🥇",
                   layout="wide", initial_sidebar_state="collapsed")

REFRESH = 10
CYAN, MAG, GRN, RED, AMB, DIM = ("#00e5ff", "#ff2bd1", "#1bff9c",
                                 "#ff3b6b", "#ffb300", "#5b6b8c")

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800&family=Share+Tech+Mono&display=swap');
.stApp {{ background:
  radial-gradient(circle at 15% 0%, rgba(0,229,255,.07), transparent 42%),
  radial-gradient(circle at 85% 10%, rgba(255,43,209,.06), transparent 42%),
  #06080f; }}
.block-container {{ padding-top: 1rem; max-width: 1500px; }}
* {{ font-family:'Share Tech Mono', monospace; }}
h1,h2,h3 {{ font-family:'Orbitron', sans-serif !important; letter-spacing:1px; }}
#MainMenu, footer, header {{ visibility:hidden; }}
.title {{ font-family:'Orbitron'; font-weight:800; font-size:2rem;
  background:linear-gradient(90deg,{CYAN},{MAG}); -webkit-background-clip:text;
  -webkit-text-fill-color:transparent; letter-spacing:4px; }}
.card {{ background:linear-gradient(150deg,rgba(13,20,38,.9),rgba(7,11,22,.9));
  border:1px solid rgba(0,229,255,.22); border-radius:12px; padding:12px 14px;
  box-shadow:0 0 18px rgba(0,229,255,.05); }}
.lab {{ color:{DIM}; font-size:.68rem; letter-spacing:2px; text-transform:uppercase; }}
.val {{ font-family:'Orbitron'; font-size:1.5rem; font-weight:700; color:#eafcff; }}
.sub {{ color:{DIM}; font-size:.72rem; }}
.pill {{ display:inline-block; padding:3px 12px; border-radius:16px;
  font-family:'Orbitron'; font-weight:700; font-size:.78rem; border:1px solid; }}
.sec {{ font-family:'Orbitron'; color:{CYAN}; letter-spacing:3px; font-size:.95rem;
  margin:18px 0 6px; border-left:3px solid {MAG}; padding-left:9px; }}
</style>""", unsafe_allow_html=True)


def load_snapshot():
    try:
        with open(config.SNAPSHOT_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def q(sql, params=()):
    try:
        c = sqlite3.connect(config.DB_PATH)
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(sql, params).fetchall()]
        c.close()
        return rows
    except Exception:
        return []


def card(lab, val, color="#eafcff", sub=""):
    return (f"<div class='card'><div class='lab'>{lab}</div>"
            f"<div class='val' style='color:{color}'>{val}</div>"
            f"<div class='sub'>{sub}</div></div>")


def gl(v):
    try:
        return GRN if float(v) >= 0 else RED
    except (TypeError, ValueError):
        return "#eafcff"


snap = load_snapshot()
acct = snap.get("account", {}) or {}
fresh = bool(snap)
stale = False
if snap.get("updated"):
    try:
        age = time.time() - pd.Timestamp(snap["updated"]).timestamp()
        stale = age > 60
    except Exception:
        pass

# ---------------- header ----------------
hL, hR = st.columns([2.4, 1.6])
with hL:
    st.markdown("<div class='title'>◆ AURUM AI</div>"
                "<div class='sub'>Adaptive XAUUSD · analysis → execution → learning</div>",
                unsafe_allow_html=True)
with hR:
    mode = snap.get("mode", "—")
    live = "LIVE" in str(mode)
    online = fresh and not stale
    c = GRN if online else RED
    mc = MAG if live else CYAN
    st.markdown(
        f"<div style='text-align:right;margin-top:6px'>"
        f"<span class='pill' style='color:{c};border-color:{c}'>"
        f"{'● ONLINE' if online else '● OFFLINE'}</span> "
        f"<span class='pill' style='color:{mc};border-color:{mc}'>{mode}</span>"
        + (f" <span class='pill' style='color:{AMB};border-color:{AMB}'>🔫 "
           f"{snap.get('sb_window')}</span>" if snap.get('sb_window') else "")
        + "<br>"
        f"<span class='sub'>GMT {time.strftime('%H:%M:%S', time.gmtime())} · "
        f"snap {str(snap.get('updated','—'))[11:19]}</span></div>",
        unsafe_allow_html=True)

if not fresh:
    st.warning("No live snapshot yet. Start the engine:  python main.py live")
elif stale:
    st.warning("Snapshot is stale (>60s). Is the live loop running?")

# ---------------- price + account ----------------
c1, c2, c3, c4, c5 = st.columns(5)
c1.markdown(card("XAUUSD BID", f"${snap.get('bid','—')}", CYAN,
                 f"ask ${snap.get('ask','—')}"), unsafe_allow_html=True)
c2.markdown(card("SPREAD", f"{snap.get('spread_pips','—')}p", AMB),
            unsafe_allow_html=True)
c3.markdown(card("BALANCE", f"${acct.get('balance','—')}"), unsafe_allow_html=True)
c4.markdown(card("EQUITY", f"${acct.get('equity','—')}"), unsafe_allow_html=True)
dd = 0.0
if acct.get("equity") and snap.get("start_balance"):
    dd = round(acct["equity"] - snap["start_balance"], 2)
c5.markdown(card("P&L (session)", f"${dd}", gl(dd)), unsafe_allow_html=True)

# ---------------- bias ----------------
st.markdown("<div class='sec'>MULTI-TIMEFRAME BIAS</div>", unsafe_allow_html=True)
bias = snap.get("bias", {}) or {}
bdir = bias.get("direction", "—")
bcol = {"BULLISH": GRN, "BEARISH": RED}.get(bdir, AMB)
b1, b2 = st.columns([1, 2.4])
with b1:
    st.markdown(card("BIAS", bdir, bcol,
                     f"{bias.get('confidence','—')} · score {bias.get('score','—')}"),
                unsafe_allow_html=True)
with b2:
    tfs = snap.get("timeframes", {}) or {}
    if tfs:
        rows = []
        for tf in config.TIMEFRAMES:
            m = tfs.get(tf)
            if not m:
                continue
            sc = {"BULLISH": GRN, "BEARISH": RED}.get(m["state"], DIM)
            rows.append(f"<tr><td style='color:{DIM}'>{tf}</td>"
                        f"<td style='color:{sc};font-weight:700'>{m['state']}</td>"
                        f"<td style='color:#9fd9e6'>{m['event']}</td>"
                        f"<td style='color:{AMB}'>{'sweep' if m['sweep'] else ''}</td>"
                        f"<td style='color:{DIM}'>{m['pd_zone']}</td></tr>")
        st.markdown(f"<div class='card'><table style='width:100%;font-size:.8rem'>"
                    f"<tr style='color:{DIM}'><th align=left>TF</th><th align=left>STATE</th>"
                    f"<th align=left>EVENT</th><th align=left>LIQ</th>"
                    f"<th align=left>ZONE</th></tr>{''.join(rows)}</table></div>",
                    unsafe_allow_html=True)

# ---------------- open positions ----------------
st.markdown("<div class='sec'>OPEN POSITIONS</div>", unsafe_allow_html=True)
pos = snap.get("positions", []) or []
if pos:
    for p in pos:
        col = st.columns(6)
        dcol = GRN if p["side"] == "BUY" else RED
        col[0].markdown(card("SIDE", f"{p['side']} #{p['ticket']}", dcol),
                        unsafe_allow_html=True)
        col[1].markdown(card("ENTRY", f"${p['entry']}"), unsafe_allow_html=True)
        col[2].markdown(card("LOTS", p["lots"]), unsafe_allow_html=True)
        col[3].markdown(card("SL", f"${p['sl']}", RED), unsafe_allow_html=True)
        col[4].markdown(card("TP", f"${p['tp']}", GRN), unsafe_allow_html=True)
        col[5].markdown(card("P&L", f"${p['profit']}", gl(p["profit"])),
                        unsafe_allow_html=True)
else:
    st.markdown(f"<div class='card' style='text-align:center;color:{DIM}'>"
                f"◇ flat — no open position ◇</div>", unsafe_allow_html=True)

# ---------------- last signal ----------------
ls = snap.get("last_signal")
if ls:
    st.markdown("<div class='sec'>LAST SIGNAL</div>", unsafe_allow_html=True)
    ap = GRN if ls.get("approved") else AMB
    st.markdown(
        f"<div class='card'><b style='color:{GRN if ls['side']=='BUY' else RED}'>"
        f"{ls['side']} {ls['setup']}</b> on {ls['tf']} — entry {ls['entry']}, "
        f"SL {ls['sl']}, TP1 {ls['tp1']} (R:R {ls['rr']}, edge {ls['edge']}) · "
        f"<span style='color:{ap}'>{'TAKEN' if ls.get('approved') else 'skipped: ' + str(ls.get('reason',''))}</span>"
        f"</div>", unsafe_allow_html=True)

# ---------------- live thinking feed ----------------
st.markdown("<div class='sec'>LIVE THINKING</div>", unsafe_allow_html=True)
thoughts = snap.get("thoughts", []) or []
if thoughts:
    feed = "<br>".join(html_escape(t) for t in reversed(thoughts[-30:]))
    st.markdown(
        f"<div class='card' style='max-height:280px;overflow-y:auto;"
        f"font-size:.8rem;line-height:1.7;color:#bfe9ff'>{feed}</div>",
        unsafe_allow_html=True)
else:
    st.markdown(f"<div class='card' style='color:{DIM}'>Waiting for the "
                f"engine's first scan…</div>", unsafe_allow_html=True)

# ---------------- stats + learning ----------------
st.markdown("<div class='sec'>PERFORMANCE & LEARNING</div>", unsafe_allow_html=True)
s1, s2, s3, s4 = st.columns(4)
s1.markdown(card("TRADES", snap.get("trades_total", 0)), unsafe_allow_html=True)
s2.markdown(card("WIN RATE", f"{snap.get('win_rate', 0)}%"), unsafe_allow_html=True)
s3.markdown(card("NET R", f"{snap.get('net_r', 0):+}", gl(snap.get("net_r", 0))),
            unsafe_allow_html=True)
pbm = snap.get("playbook", {}) or {}
s4.markdown(card("PLAYBOOK", f"{pbm.get('trades_fit', 0)} fit",
                 sub=f"overall {pbm.get('overall_r', 0)}R"), unsafe_allow_html=True)

# learned playbook table
try:
    with open(config.PLAYBOOK_FILE, encoding="utf-8") as fh:
        buckets = json.load(fh).get("buckets", {})
except Exception:
    buckets = {}
if buckets:
    rows = sorted(buckets.items(), key=lambda kv: kv[1]["expectancy_r"],
                  reverse=True)
    body = []
    for k, v in rows[:10]:
        ec = GRN if v["edge_score"] >= 1 else RED if v["edge_score"] < config.MIN_EDGE_SCORE else AMB
        body.append(f"<tr><td style='color:#9fd9e6'>{k}</td>"
                    f"<td>{v['n']}</td>"
                    f"<td style='color:{gl(v['expectancy_r'])}'>{v['expectancy_r']:+}R</td>"
                    f"<td>{v['win_rate']*100:.0f}%</td>"
                    f"<td style='color:{ec};font-weight:700'>{v['edge_score']}</td>"
                    f"<td>×{v['size_factor']}</td></tr>")
    st.markdown(f"<div class='card'><table style='width:100%;font-size:.78rem'>"
                f"<tr style='color:{DIM}'><th align=left>BUCKET (setup|tf|session|aligned|zone)</th>"
                f"<th align=left>N</th><th align=left>EXP</th><th align=left>WIN</th>"
                f"<th align=left>EDGE</th><th align=left>SIZE</th></tr>"
                f"{''.join(body)}</table></div>", unsafe_allow_html=True)
else:
    st.markdown(f"<div class='card' style='color:{DIM}'>Playbook empty — "
                f"trading base rules (cold start). Learns after "
                f"{config.LEARN_AFTER_TRADES} trades.</div>",
                unsafe_allow_html=True)

# ---------------- recent trades ----------------
st.markdown("<div class='sec'>RECENT TRADES</div>", unsafe_allow_html=True)
tr = q("SELECT close_time,side,setup,timeframe,entry,exit,pnl_r,result "
       "FROM trades ORDER BY id DESC LIMIT 15")
if tr:
    st.dataframe(pd.DataFrame(tr), use_container_width=True, hide_index=True)
else:
    st.markdown(f"<div class='card' style='color:{DIM}'>No closed trades yet.</div>",
                unsafe_allow_html=True)

st.markdown(f"<div style='text-align:center;color:{DIM};font-size:.72rem;"
            f"margin-top:18px;letter-spacing:2px'>AURUM AI · refresh {REFRESH}s · "
            f"PRECISION · PATIENCE · PROTECTION</div>", unsafe_allow_html=True)

time.sleep(REFRESH)
st.rerun()
