# ═══════════════════════════════════════════════════════════
# AURUM AI · core/utils.py
# Logging (UTF-8 safe), GMT time, pip math, session tagging.
# ═══════════════════════════════════════════════════════════

import logging
import os
import sys
from datetime import datetime, time as dtime, timezone
from logging.handlers import RotatingFileHandler

import config

# Windows consoles default to cp1252 and crash on box/arrow glyphs.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_LOGGERS: dict[str, logging.Logger] = {}


def get_logger(name: str) -> logging.Logger:
    if name in _LOGGERS:
        return _LOGGERS[name]
    lg = logging.getLogger(name)
    lg.setLevel(logging.INFO)
    lg.propagate = False
    if not lg.handlers:
        os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)-20s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S")
        fh = RotatingFileHandler(config.LOG_FILE, maxBytes=5 * 1024 * 1024,
                                 backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        lg.addHandler(fh)
        ch = logging.StreamHandler(stream=sys.stdout)
        ch.setFormatter(fmt)
        lg.addHandler(ch)
    _LOGGERS[name] = lg
    return lg


def gmt_now() -> datetime:
    return datetime.now(timezone.utc)


def gmt_stamp() -> str:
    return gmt_now().strftime("%Y-%m-%d %H:%M")


def to_pips(distance: float) -> float:
    return round(abs(distance) / config.PIP_SIZE, 1)


def to_price(pips: float) -> float:
    return round(pips * config.PIP_SIZE, 2)


def fmt(v) -> str:
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "—"


def session_of(t: datetime) -> str:
    """Tag a GMT timestamp with its trading session (a learning feature)."""
    try:
        hm = t.timetz() if t.tzinfo else t.replace(tzinfo=timezone.utc).timetz()
    except Exception:
        return "UNKNOWN"
    h = hm.hour
    if 0 <= h < 7:
        return "ASIAN"
    if 7 <= h < 12:
        return "LONDON"
    if 12 <= h < 16:
        return "NY"
    if 16 <= h < 21:
        return "NY_PM"
    return "OFF"
