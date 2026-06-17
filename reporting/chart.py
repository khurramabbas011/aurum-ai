# ═══════════════════════════════════════════════════════════
# AURUM AI · reporting/chart.py
# Self-contained HTML/SVG candlestick viewer with the structure
# drawn on top — swing labels, BOS/CHoCH lines, sweep boxes,
# FVGs and (optionally) the active signal's entry/SL/TP. Lets
# you SEE the structure mapping in a browser, no MQL5 needed.
# ═══════════════════════════════════════════════════════════

import html

import config
from core.utils import gmt_stamp


def _scale(v, vmin, vmax, lo, hi):
    if vmax <= vmin:
        return (lo + hi) / 2
    return hi - (v - vmin) / (vmax - vmin) * (hi - lo)


def render(df, smap, signal=None, bias=None, out_path=None) -> str:
    """Render the last ~140 candles of `df` + structure to an HTML file."""
    out_path = out_path or config.CHART_FILE
    d = df.tail(140).reset_index(drop=True)
    n = len(d)
    W, H = 1180, 560
    padL, padR, padT, padB = 8, 70, 40, 26
    plotW, plotH = W - padL - padR, H - padT - padB
    vmin = float(d["low"].min())
    vmax = float(d["high"].max())
    pad = (vmax - vmin) * 0.08
    vmin -= pad
    vmax += pad
    cw = plotW / max(n, 1)

    def x(i):
        return padL + i * cw + cw / 2

    def y(v):
        return padT + _scale(v, vmin, vmax, 0, plotH)

    # time -> index map for placing structure objects
    tindex = {t: i for i, t in enumerate(d["time"])}

    svg = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
           f'font-family="monospace" font-size="10">']
    svg.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#0b0f1a"/>')
    # price gridlines
    for k in range(5):
        gv = vmin + (vmax - vmin) * k / 4
        gy = y(gv)
        svg.append(f'<line x1="{padL}" y1="{gy:.1f}" x2="{padL+plotW}" '
                   f'y2="{gy:.1f}" stroke="#1c2536" stroke-width="0.5"/>')
        svg.append(f'<text x="{padL+plotW+4}" y="{gy+3:.1f}" fill="#5b6b8c">'
                   f'{gv:.2f}</text>')

    # candles
    for i, r in d.iterrows():
        up = r["close"] >= r["open"]
        col = "#1bd97b" if up else "#ff4d6d"
        xc = x(i)
        svg.append(f'<line x1="{xc:.1f}" y1="{y(r["high"]):.1f}" x2="{xc:.1f}" '
                   f'y2="{y(r["low"]):.1f}" stroke="{col}" stroke-width="0.8"/>')
        yo, yc = y(r["open"]), y(r["close"])
        top = min(yo, yc)
        hgt = max(abs(yc - yo), 0.8)
        bw = max(cw * 0.6, 1.2)
        svg.append(f'<rect x="{xc-bw/2:.1f}" y="{top:.1f}" width="{bw:.1f}" '
                   f'height="{hgt:.1f}" fill="{col}"/>')

    def hline(price, color, label, dash=""):
        yy = y(price)
        ds = f'stroke-dasharray="{dash}"' if dash else ""
        svg.append(f'<line x1="{padL}" y1="{yy:.1f}" x2="{padL+plotW}" '
                   f'y2="{yy:.1f}" stroke="{color}" stroke-width="1" {ds}/>')
        svg.append(f'<text x="{padL+4}" y="{yy-3:.1f}" fill="{color}">'
                   f'{html.escape(label)}</text>')

    # FVGs (faint zones)
    for g in (smap.fvgs or []):
        if g.time in tindex:
            gx = x(tindex[g.time])
            col = "rgba(27,217,123,0.10)" if g.direction.value == "BULLISH" \
                else "rgba(255,77,109,0.10)"
            yt, yb = y(g.top), y(g.bottom)
            svg.append(f'<rect x="{gx:.1f}" y="{min(yt,yb):.1f}" '
                       f'width="{padL+plotW-gx:.1f}" height="{abs(yb-yt):.1f}" '
                       f'fill="{col}"/>')

    # swing labels
    for s in [s for s in smap.swings if s.label][-10:]:
        if s.time not in tindex:
            continue
        sx = x(tindex[s.time])
        col = "#1bd97b" if s.label in ("HH", "HL") else \
              "#ff4d6d" if s.label in ("LH", "LL") else "#8aa0c6"
        sy = y(s.price) + (-6 if s.kind == "HIGH" else 12)
        svg.append(f'<circle cx="{sx:.1f}" cy="{y(s.price):.1f}" r="2.2" '
                   f'fill="{col}"/>')
        svg.append(f'<text x="{sx:.1f}" y="{sy:.1f}" fill="{col}" '
                   f'text-anchor="middle">{s.label}</text>')

    # BOS / CHoCH level
    ev = smap.event
    if ev.level:
        if ev.type.value == "BOS":
            hline(ev.level, "#3d9bff", f"BOS {ev.direction.value}", "5 3")
        elif ev.type.value == "CHoCH":
            hline(ev.level, "#ff7ad9", f"CHoCH {ev.direction.value}", "5 3")

    # sweep box
    sw = smap.sweep
    if sw.detected and sw.time in tindex:
        sx = x(tindex[sw.time])
        yy = y(sw.level)
        svg.append(f'<rect x="{sx-cw:.1f}" y="{yy-14:.1f}" width="{cw*3:.1f}" '
                   f'height="28" fill="rgba(255,201,64,0.18)" '
                   f'stroke="#ffc940" stroke-width="0.6"/>')
        svg.append(f'<text x="{sx:.1f}" y="{yy-18:.1f}" fill="#ffc940" '
                   f'text-anchor="middle">SWEEP {sw.side}</text>')

    # active signal
    if signal:
        hline(signal.entry, "#ffffff", f"{signal.side.value} ENTRY")
        hline(signal.sl, "#ff4d6d", "SL", "2 2")
        hline(signal.tp1, "#1bd97b", "TP1", "2 2")
        hline(signal.tp2, "#1bd97b", "TP2", "2 2")

    svg.append('</svg>')

    biasline = ""
    if bias:
        biasline = (f"Bias: <b>{bias.direction.value}</b> "
                    f"({bias.confidence}, {bias.score:+.2f})")
    page = f"""<!doctype html><html><head><meta charset="utf-8">
<title>AURUM AI — {smap.timeframe}</title>
<style>body{{background:#070a12;color:#cfe3ff;font-family:monospace;margin:0;padding:16px}}
h1{{font-size:18px;margin:0 0 2px;color:#7fd9ff}} .sub{{color:#5b6b8c;font-size:12px;margin-bottom:10px}}
.wrap{{max-width:1200px;margin:auto}} b{{color:#fff}}</style></head>
<body><div class="wrap">
<h1>◆ AURUM AI — Structure · XAUUSD {smap.timeframe}</h1>
<div class="sub">{gmt_stamp()} GMT · state <b>{smap.state.value}</b> · zone {smap.pd_zone} · {biasline}</div>
{''.join(svg)}
</div></body></html>"""
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return out_path
