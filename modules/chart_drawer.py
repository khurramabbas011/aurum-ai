# ═══════════════════════════════════════════════════════════
# AURUM AI — Step 1 · chart_drawer.py
# The six MT5 drawing tools (Chapter 10). They accumulate
# MS_{TF}_{TYPE}_{INDEX} objects and write the overlay CSV that
# the AURUM_HUD.mq5 indicator reads + renders on the chart.
#
# CSV schema (one object per line):
#   kind,name,t1,p1,t2,p2,color,style,width,anchor,text
#   kind   : LABEL | TREND | HLINE | RECT | TEXT
#   t1/t2  : unix seconds (0 = unused)   p1/p2 : price (0 = unused)
#   color  : GREEN RED BLUE YELLOW GRAY WHITE
#   style  : SOLID DASH DOT          width : int
#   anchor : UP | DOWN | MID         text  : last field, sanitized
#
# Written atomically (temp + os.replace) so the indicator never
# reads a half-written file.
# ═══════════════════════════════════════════════════════════

import os

import config
from modules.utils import get_logger

log = get_logger("chart_drawer")

COLOR = {"GREEN", "RED", "BLUE", "YELLOW", "GRAY", "WHITE"}


def _ts(t) -> int:
    """pandas/py datetime -> unix seconds (int)."""
    try:
        return int(t.timestamp())
    except Exception:
        return 0


def _san(text) -> str:
    """Object text must not contain the CSV delimiter or newlines."""
    return str(text).replace(",", " ").replace("\n", " ").replace("\r", " ")[:60]


class ChartDrawer:
    """Holds the structure objects for all timeframes + writes them."""

    def __init__(self):
        self.objects = {}   # name -> record dict

    # ───────────────────────────────────────────────────────
    # TOOL 6 — clear_structure(timeframe)
    # ───────────────────────────────────────────────────────
    def clear_structure(self, timeframe: str):
        """Drop every MS_{timeframe}_* object before a redraw."""
        prefix = f"{config.OBJ_PREFIX}_{timeframe}_"
        dead = [n for n in self.objects if n.startswith(prefix)]
        for n in dead:
            del self.objects[n]
        log.info("clear_structure(%s) — removed %d objects",
                 timeframe, len(dead))

    def _name(self, tf, otype, idx) -> str:
        return f"{config.OBJ_PREFIX}_{tf}_{otype}_{idx}"

    def _put(self, kind, name, t1, p1, t2, p2, color, style, width,
             anchor, text):
        self.objects[name] = {
            "kind": kind, "name": name,
            "t1": _ts(t1) if t1 else 0, "p1": round(float(p1), 2) if p1 else 0,
            "t2": _ts(t2) if t2 else 0, "p2": round(float(p2), 2) if p2 else 0,
            "color": color if color in COLOR else "GRAY",
            "style": style, "width": int(width),
            "anchor": anchor, "text": _san(text),
        }

    # ───────────────────────────────────────────────────────
    # TOOL 1 — draw_label  (swing point: HH/HL/LH/LL/SH/SL)
    # ───────────────────────────────────────────────────────
    def draw_label(self, tf, idx, time, price, text, color, anchor="UP"):
        self._put("LABEL", self._name(tf, text, idx), time, price,
                  None, None, color, "SOLID", 1, anchor, text)

    # ───────────────────────────────────────────────────────
    # TOOL 2 — draw_trendline (connect swing points)
    # ───────────────────────────────────────────────────────
    def draw_trendline(self, tf, idx, t1, p1, t2, p2, color,
                       style="SOLID", width=1):
        self._put("TREND", self._name(tf, "Trend", idx), t1, p1, t2, p2,
                  color, style, width, "MID", "")

    # ───────────────────────────────────────────────────────
    # TOOL 3 — draw_hline (horizontal structural level)
    # ───────────────────────────────────────────────────────
    def draw_hline(self, tf, otype, idx, price, color, style="DOT",
                   label=""):
        self._put("HLINE", self._name(tf, otype, idx), None, price,
                  None, None, color, style, 1, "MID", label)

    # ───────────────────────────────────────────────────────
    # TOOL 4 — draw_rectangle (sweep zone / range box)
    # ───────────────────────────────────────────────────────
    def draw_rectangle(self, tf, otype, idx, t1, p1, t2, p2, color):
        self._put("RECT", self._name(tf, otype, idx), t1, p1, t2, p2,
                  color, "SOLID", 1, "MID", "")

    # ───────────────────────────────────────────────────────
    # TOOL 5 — draw_text_note (short structural note)
    # ───────────────────────────────────────────────────────
    def draw_text_note(self, tf, idx, time, price, text, color):
        self._put("TEXT", self._name(tf, "Note", idx), time, price,
                  None, None, color, "SOLID", 1, "UP", text)

    # ───────────────────────────────────────────────────────
    # HIGH-LEVEL — draw a full structure analysis (drawing
    # discipline of Chapter 10 applied here, in one place)
    # ───────────────────────────────────────────────────────
    def draw_structure(self, analysis: dict) -> dict:
        """Render one timeframe's analyze() result. Returns counts."""
        tf = analysis["timeframe"]
        self.clear_structure(tf)
        counts = {"labels": 0, "trendlines": 0, "lines": 0, "boxes": 0,
                  "notes": 0}
        swings = analysis.get("swings", [])
        if not swings:
            return counts

        state = analysis.get("state", "SIDEWAYS")
        # Only the most recent significant pivots — never over-mark.
        recent = [s for s in swings if s.get("label")][-8:]

        # TOOL 1 — swing labels
        for i, s in enumerate(recent):
            lbl = s["label"]
            if lbl in ("HH", "HL", "SH", "SL") and lbl not in ("LH", "LL"):
                color = "GREEN" if lbl in ("HH", "HL") else "GRAY"
            else:
                color = "RED" if lbl in ("LH", "LL") else "GRAY"
            anchor = "UP" if s["kind"] == "HIGH" else "DOWN"
            self.draw_label(tf, i, s["time"], s["price"], lbl, color, anchor)
            counts["labels"] += 1

        # TOOL 2 — trendlines connecting consecutive swings
        for i in range(len(recent) - 1):
            a, b = recent[i], recent[i + 1]
            up = b["price"] > a["price"]
            color = "GREEN" if up else "RED"
            # impulse (with the trend) = bold; correction = thin
            with_trend = (up and state == "BULLISH") or \
                         (not up and state == "BEARISH")
            width = 2 if with_trend else 1
            self.draw_trendline(tf, i, a["time"], a["price"],
                                b["time"], b["price"], color, "SOLID", width)
            counts["trendlines"] += 1

        # TOOL 3 — last swing high / low levels (gray dotted)
        lsh = analysis.get("last_swing_high")
        lsl = analysis.get("last_swing_low")
        if lsh:
            self.draw_hline(tf, "SwingHigh", 1, lsh["price"], "GRAY", "DOT",
                            "swing high")
            counts["lines"] += 1
        if lsl:
            self.draw_hline(tf, "SwingLow", 1, lsl["price"], "GRAY", "DOT",
                            "swing low")
            counts["lines"] += 1

        # TOOL 3 — BOS / CHoCH level
        ev = analysis.get("event", {})
        if ev.get("type") in ("BOS", "CHoCH") and ev.get("level"):
            if ev["type"] == "BOS":
                self.draw_hline(tf, "BOS", 1, ev["level"], "BLUE", "DASH",
                                "BOS")
            else:
                self.draw_hline(tf, "CHoCH", 1, ev["level"], "RED", "DASH",
                                "CHoCH")
            counts["lines"] += 1
            # short note at the event
            if ev.get("time"):
                self.draw_text_note(
                    tf, 1, ev["time"], ev["level"],
                    f"{ev['direction']} {ev['type']} ({ev['implication']})",
                    "BLUE" if ev["type"] == "BOS" else "RED")
                counts["notes"] += 1

        # TOOL 4 — liquidity sweep zone (yellow box)
        sw = analysis.get("sweep", {})
        if sw.get("detected") and sw.get("time") and sw.get("level"):
            span = analysis.get("current_price", sw["level"])
            pad = abs(span - sw["level"]) * 0.0 + (config.PIP_SIZE * 6)
            if sw["side"] == "BUY_SIDE":
                p_top, p_bot = sw["level"] + pad * 2, sw["level"]
            else:
                p_top, p_bot = sw["level"], sw["level"] - pad * 2
            # box spans from the sweep candle ~12 bars forward
            t2 = sw["time"] + (sw["time"] - swings[0]["time"]) * 0
            self.draw_rectangle(tf, "Sweep", 1, sw["time"], p_top,
                                sw["time"], p_bot, "YELLOW")
            counts["boxes"] += 1
            self.draw_text_note(tf, 2, sw["time"], p_top,
                                f"Sweep {sw['side']}", "YELLOW")
            counts["notes"] += 1

        # TOOL 4 — range box if sideways
        if state == "SIDEWAYS":
            pdz = analysis.get("premium_discount", {})
            if pdz.get("range_high") and pdz.get("range_low") and recent:
                self.draw_rectangle(tf, "Range", 1, recent[0]["time"],
                                    pdz["range_high"], recent[-1]["time"],
                                    pdz["range_low"], "GRAY")
                counts["boxes"] += 1

        return counts

    # ───────────────────────────────────────────────────────
    # WRITE THE OVERLAY FILE (atomic)
    # ───────────────────────────────────────────────────────
    def commit(self) -> bool:
        """Write every accumulated object to the MQL5 bridge file."""
        path = config.OVERLAY_FILE
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            lines = []
            for o in self.objects.values():
                lines.append(",".join(str(x) for x in (
                    o["kind"], o["name"], o["t1"], o["p1"], o["t2"], o["p2"],
                    o["color"], o["style"], o["width"], o["anchor"],
                    o["text"])))
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="ascii", errors="replace") as fh:
                fh.write("\n".join(lines) + "\n")
            os.replace(tmp, path)
            log.info("Overlay committed — %d objects -> %s",
                     len(self.objects), path)
            return True
        except Exception as e:
            log.error("Overlay commit failed: %s", e)
            return False
