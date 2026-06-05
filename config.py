# ═══════════════════════════════════════════════════════════
# AURUM AI — STEP 1: MARKET STRUCTURE MAPPING
# config.py — credentials + settings
# ═══════════════════════════════════════════════════════════
# Instrument: XAUUSD only.  Task: identify, draw, report
# market structure on every timeframe. NO trading.
# ═══════════════════════════════════════════════════════════

import os

# ───────────────────────────────────────────────────────────
# MT5 CONNECTION (local Windows terminal — must be open)
# ───────────────────────────────────────────────────────────
# Placeholders only — put your REAL credentials in config_local.py
# (gitignored), they will override the values below at import time.
MT5_LOGIN = 0
MT5_PASSWORD = "your MT5 password"
MT5_SERVER = "your broker server name"
MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

# ───────────────────────────────────────────────────────────
# AGENT IDENTITY
# ───────────────────────────────────────────────────────────
AGENT_NAME = "AURUM AI"
AGENT_STEP = "STEP 1 — MARKET STRUCTURE MAPPING"
SYMBOL = "XAUUSD"   # auto-resolved at connect if broker uses a suffix

# Top-down analysis order — never skip, never reorder.
TIMEFRAMES = ["D1", "H4", "H1", "M30", "M15", "M5", "M1"]

# ───────────────────────────────────────────────────────────
# SWING DETECTION — per-timeframe lookback (Chapter 3)
# candles on EACH side that must be lower (SH) / higher (SL)
# ───────────────────────────────────────────────────────────
SWING_LOOKBACK = {
    "M1": 5,
    "M5": 5,
    "M15": 7,
    "M30": 8,
    "H1": 10,
    "H4": 10,
    "D1": 10,
}

# ───────────────────────────────────────────────────────────
# DATA — bars to pull per timeframe (Chapter 12)
# ───────────────────────────────────────────────────────────
BAR_COUNT = {
    "D1": 100,
    "H4": 200,
    "H1": 300,
    "M30": 300,
    "M15": 300,
    "M5": 300,
    "M1": 300,
}

# ───────────────────────────────────────────────────────────
# STRUCTURE RULES
# ───────────────────────────────────────────────────────────
CONFIRM_CLOSES = 2          # BOS/CHoCH need 2 consecutive closes beyond level
TREND_CONFIRM_SWINGS = 2    # >= 2 consecutive HH+HL (or LH+LL) = confirmed trend
SWEEP_MIN_WICK_PIPS = 3     # wick must exceed the level by this to count as sweep
RANGE_TOLERANCE_PIPS = 25   # highs/lows within this band => sideways/range

# Gold price units
PIP_SIZE = 0.10             # 1 pip = 0.10 price units for XAUUSD
POINT_SIZE = 0.01

# ───────────────────────────────────────────────────────────
# CONTINUOUS OPERATION
# ───────────────────────────────────────────────────────────
# Seconds between full multi-timeframe re-mapping passes.
REFRESH_SECONDS = 300       # re-map every 5 minutes
RUN_CONTINUOUS = True       # False = single pass then exit

# ───────────────────────────────────────────────────────────
# PATHS
# ───────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "logs", "aurum_ai.log")
REPORT_FILE = os.path.join(BASE_DIR, "logs", "structure_report.txt")

# MQL5 chart-drawing bridge. The agent writes objects here; the
# AURUM_HUD.mq5 indicator (attached to an XAUUSD chart) reads it
# and renders the structure for that chart's timeframe.
_MT5_COMMON_FILES = os.path.join(
    os.environ.get("APPDATA", BASE_DIR),
    "MetaQuotes", "Terminal", "Common", "Files")
OVERLAY_FILE = os.path.join(_MT5_COMMON_FILES, "aurum_structure.csv")

# ───────────────────────────────────────────────────────────
# CHART OBJECT NAMING + COLOR LEGEND (Chapter 10 — never deviate)
# ───────────────────────────────────────────────────────────
OBJ_PREFIX = "MS"           # MS_{TIMEFRAME}_{TYPE}_{INDEX}

COLOR = {
    "GREEN": "GREEN",       # bullish structure (HH, HL, up trendline)
    "RED": "RED",           # bearish structure (LH, LL, down line, CHoCH)
    "BLUE": "BLUE",         # BOS (continuation)
    "YELLOW": "YELLOW",     # liquidity sweep zone
    "GRAY": "GRAY",         # swing levels / range boxes
}


def validate():
    """Return a list of human-readable config problems (empty == OK)."""
    problems = []
    if not isinstance(MT5_LOGIN, int) or MT5_LOGIN <= 0:
        problems.append(
            "MT5_LOGIN must be a positive integer. "
            "Create config_local.py with your real credentials "
            "(see config_local.example.py).")
    if "your MT5 password" in MT5_PASSWORD:
        problems.append("MT5_PASSWORD is still a placeholder.")
    if "your broker server" in MT5_SERVER:
        problems.append("MT5_SERVER is still a placeholder.")
    return problems


# ───────────────────────────────────────────────────────────
# LOCAL OVERRIDE (untracked, optional)
# ───────────────────────────────────────────────────────────
# If you create config_local.py next to this file, any names
# defined there (MT5_LOGIN, MT5_PASSWORD, ...) override the
# placeholders above at import time. The local file is in
# .gitignore so your real credentials never reach GitHub.
try:
    from config_local import *  # noqa: F401, F403
except ImportError:
    pass
