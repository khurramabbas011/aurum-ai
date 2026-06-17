# ═══════════════════════════════════════════════════════════
# AURUM AI — FULL SYSTEM CONFIG
# Analysis → signals → risk → execution → self-learning.
# XAUUSD. MT5. Runs live OR fully offline (replay/backtest).
#
# SAFETY: live order placement is OFF by default. The system
# runs in PAPER mode until you deliberately flip
# ENABLE_LIVE_TRADING = True in config_local.py. Risk rails
# below are always enforced and the learning layer can only
# tune WITHIN them — never widen them.
# ═══════════════════════════════════════════════════════════

import os

# ───────────────────────── MT5 (placeholders; real creds in config_local.py)
MT5_LOGIN = 0
MT5_PASSWORD = "your MT5 password"
MT5_SERVER = "your broker server name"
MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

# ───────────────────────── identity
AGENT_NAME = "AURUM AI"
SYMBOL = "XAUUSD"                      # auto-resolved (XAUUSDm etc.) at connect
TIMEFRAMES = ["D1", "H4", "H1", "M30", "M15", "M5", "M1"]   # top-down order
SIGNAL_TFS = ["M15", "M5"]            # timeframes the strategy hunts entries on
HTF_BIAS_TFS = ["D1", "H4", "H1"]    # timeframes that set directional bias

# ───────────────────────── execution mode (SAFETY)
ENABLE_LIVE_TRADING = False           # False = paper only (no MT5 orders)
PAPER_START_BALANCE = 5000.0          # paper/backtest starting equity (USD)
REQUIRE_DEMO_ACCOUNT = True           # block live orders on a real/live account

# ───────────────────────── swing detection (per-TF lookback)
SWING_LOOKBACK = {"M1": 5, "M5": 5, "M15": 7, "M30": 8,
                  "H1": 10, "H4": 10, "D1": 10}
BAR_COUNT = {"D1": 200, "H4": 300, "H1": 400, "M30": 400,
             "M15": 500, "M5": 600, "M1": 600}

# ───────────────────────── structure rules
CONFIRM_CLOSES = 2                    # BOS/CHoCH need 2 consecutive closes
SWEEP_MIN_WICK_PIPS = 3
RANGE_TOLERANCE_PIPS = 25
PIP_SIZE = 0.10                       # 1 pip = 0.10 price units for XAUUSD
POINT_SIZE = 0.01

# ───────────────────────── strategy
MIN_RR = 2.0                          # minimum reward:risk to TP1
SL_BUFFER_PIPS = 3                    # structural SL buffer beyond the wick
TP1_CLOSE_PCT = 40                    # % closed at TP1 (rest trails)
REQUIRE_HTF_ALIGNMENT = True          # only take signals with HTF bias
MIN_EDGE_SCORE = 0.35                 # learning gate: skip buckets below this

# ───────────────────────── risk rails (NEVER widened by learning)
RISK_PER_TRADE = 0.005                # 0.5% base risk
ABSOLUTE_MAX_RISK = 0.01              # 1% hard cap
MAX_DAILY_LOSS = 0.02                 # 2% daily drawdown -> kill switch
MAX_OPEN_POSITIONS = 1
MAX_TRADES_DAY = 6
MAX_CONSEC_LOSSES = 3                 # pause after 3 losses in a row

# ───────────────────────── self-learning
LEARNING_ENABLED = True
LEARN_AFTER_TRADES = 20               # re-fit the playbook every N closed trades
LEARN_MIN_SAMPLES = 8                 # min trades in a bucket before trusting it
LEARN_DECAY = 0.97                    # recency weight per trade age
PLAYBOOK_FILE = None                  # set below (path)

# ───────────────────────── timing
SCAN_SECONDS = 15                     # live loop scan cadence
TRADE_MONITOR_SECONDS = 20

# ───────────────────────── paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "logs", "aurum_ai.log")
DB_PATH = os.path.join(BASE_DIR, "data_store", "aurum.db")
REPORT_FILE = os.path.join(BASE_DIR, "logs", "structure_report.txt")
CHART_FILE = os.path.join(BASE_DIR, "logs", "chart.html")
PLAYBOOK_FILE = os.path.join(BASE_DIR, "data_store", "playbook.json")

# MQL5 chart bridge (optional live drawing on the MT5 chart)
_MT5_COMMON = os.path.join(os.environ.get("APPDATA", BASE_DIR),
                           "MetaQuotes", "Terminal", "Common", "Files")
OVERLAY_FILE = os.path.join(_MT5_COMMON, "aurum_structure.csv")

OBJ_PREFIX = "MS"


def validate() -> list[str]:
    problems = []
    if RISK_PER_TRADE > ABSOLUTE_MAX_RISK:
        problems.append("RISK_PER_TRADE exceeds ABSOLUTE_MAX_RISK.")
    if ENABLE_LIVE_TRADING and (not isinstance(MT5_LOGIN, int) or MT5_LOGIN <= 0):
        problems.append("Live trading on but MT5_LOGIN not set (config_local.py).")
    return problems


def needs_mt5() -> bool:
    """MT5 creds present? (else only replay/backtest is available)."""
    return isinstance(MT5_LOGIN, int) and MT5_LOGIN > 0 \
        and "your MT5 password" not in MT5_PASSWORD


# ───────────────────────── local override (untracked)
try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass
