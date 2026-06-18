# ═══════════════════════════════════════════════════════════
# AURUM AI · supervisor.py
# 24/7 watchdog. Keeps `main.py live` (and optionally the
# dashboard) running forever — restarts them if they crash,
# with exponential backoff. Use this for unattended hosting.
#
#   python supervisor.py            # live engine + dashboard
#   python supervisor.py --no-dash  # live engine only
# ═══════════════════════════════════════════════════════════

import subprocess
import sys
import time

import config
from core.utils import get_logger

log = get_logger("supervisor")


def _spawn(args):
    return subprocess.Popen([sys.executable] + args, cwd=config.BASE_DIR)


def main():
    run_dash = "--no-dash" not in sys.argv
    log.info("AURUM AI supervisor starting (dashboard=%s)", run_dash)

    dash = None
    if run_dash:
        dash = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run",
             "dashboard/app.py", "--server.headless=true",
             "--server.port=8501"], cwd=config.BASE_DIR)
        log.info("dashboard launched -> http://localhost:8501")

    backoff = 5
    try:
        while True:
            log.info("launching live engine ...")
            started = time.time()
            proc = _spawn(["main.py", "live"])
            proc.wait()
            ran = time.time() - started
            # if it survived a while, reset backoff; else grow it
            backoff = 5 if ran > 120 else min(backoff * 2, 300)
            log.warning("live engine exited after %.0fs (code %s) — "
                        "restarting in %ds", ran, proc.returncode, backoff)
            # keep dashboard alive across engine restarts
            if dash and dash.poll() is not None:
                dash = subprocess.Popen(
                    [sys.executable, "-m", "streamlit", "run",
                     "dashboard/app.py", "--server.headless=true",
                     "--server.port=8501"], cwd=config.BASE_DIR)
            time.sleep(backoff)
    except KeyboardInterrupt:
        log.info("supervisor stopping ...")
        if dash:
            dash.terminate()


if __name__ == "__main__":
    main()
