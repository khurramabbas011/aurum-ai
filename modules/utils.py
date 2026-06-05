# ═══════════════════════════════════════════════════════════
# AURUM AI — Step 1 · utils.py
# Shared helpers: UTF-8-safe logging, GMT time, pip math.
# ═══════════════════════════════════════════════════════════

import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

import config

# Windows consoles default to cp1252 and crash on box-drawing /
# arrow characters used in reports — force UTF-8 once, up front.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_LOGGERS = {}


def get_logger(name: str) -> logging.Logger:
    """Singleton logger — console + rotating file, both UTF-8."""
    if name in _LOGGERS:
        return _LOGGERS[name]
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S")
        fh = RotatingFileHandler(config.LOG_FILE, maxBytes=5 * 1024 * 1024,
                                 backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        ch = logging.StreamHandler(stream=sys.stdout)
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    _LOGGERS[name] = logger
    return logger


def gmt_now() -> datetime:
    """Timezone-aware current time in GMT/UTC."""
    return datetime.now(timezone.utc)


def gmt_stamp() -> str:
    """'YYYY-MM-DD HH:MM' in GMT — used in report headers."""
    return gmt_now().strftime("%Y-%m-%d %H:%M")


def price_to_pips(distance: float) -> float:
    """Absolute Gold price distance -> pips (1 pip = 0.10)."""
    return round(abs(distance) / config.PIP_SIZE, 1)


def pips_to_price(pips: float) -> float:
    """Pip distance -> absolute Gold price distance."""
    return round(pips * config.PIP_SIZE, 2)


def fmt_price(p) -> str:
    """Consistent 2-decimal price formatting for reports."""
    try:
        return f"{float(p):.2f}"
    except (TypeError, ValueError):
        return "—"


def fmt_time(t) -> str:
    """Format a pandas/py datetime for reports (UTC, HH:MM)."""
    try:
        return t.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(t)
