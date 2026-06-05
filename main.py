# ═══════════════════════════════════════════════════════════
# AURUM AI — STEP 1: MARKET STRUCTURE MAPPING
# main.py — entry point.  Run with:  python main.py
#
# Connects to MT5, maps XAUUSD structure top-down on every
# timeframe (D1 → H4 → H1 → M30 → M15 → M5 → M1), draws it on
# the chart via the AURUM_HUD indicator, and reports.
# NO trading. Identification, drawing, and reporting only.
# ═══════════════════════════════════════════════════════════

import sys
import time
import traceback

import config
from modules.utils import get_logger, gmt_stamp
from modules.mt5_connector import MT5Connector, MT5ConnectionError
from modules.structure_engine import StructureEngine
from modules.chart_drawer import ChartDrawer
from modules import reporter

log = get_logger("main")

BANNER = r"""
╔══════════════════════════════════════════════════════════╗
║                      A U R U M   A I                     ║
║              STEP 1 — MARKET STRUCTURE MAPPING            ║
║                  XAUUSD · M1 → D1 · MT5                  ║
╠══════════════════════════════════════════════════════════╣
║  Identify the structure. Draw it. Report it.             ║
║  No trading. No entries. Observation only.               ║
╚══════════════════════════════════════════════════════════╝
"""


class AurumStructureAgent:
    """Step 1 orchestrator — multi-timeframe structure mapper."""

    def __init__(self):
        self.mt5 = MT5Connector()
        self.engine = StructureEngine()
        self.drawer = ChartDrawer()
        self.running = True

    # ───────────────────────────────────────────────────────
    def startup(self):
        print(BANNER)
        problems = config.validate()
        if problems:
            log.error("CONFIG PROBLEMS — fix config.py first:")
            for p in problems:
                log.error("  - %s", p)
            sys.exit(1)
        self.mt5.connect()
        log.info("AURUM AI Step 1 ready — mapping order: %s",
                 " -> ".join(config.TIMEFRAMES))

    # ───────────────────────────────────────────────────────
    # ONE FULL TOP-DOWN MAPPING PASS
    # ───────────────────────────────────────────────────────
    def run_pass(self):
        """Map every timeframe, draw, and produce all reports."""
        results = []
        reports = []
        higher_tf = None
        higher_state = None

        for tf in config.TIMEFRAMES:
            try:
                df = self.mt5.get_ohlcv(tf, config.BAR_COUNT[tf])
                analysis = self.engine.analyze(tf, df)
                counts = self.drawer.draw_structure(analysis)
                rpt = reporter.timeframe_report(analysis, counts,
                                                higher_tf, higher_state)
                print(rpt)
                reports.append(rpt)
                results.append(analysis)
                # this timeframe becomes the "higher TF" for the next
                higher_tf = tf
                higher_state = analysis.get("state")
            except Exception as e:
                log.error("%s analysis failed: %s\n%s", tf, e,
                          traceback.format_exc())

        # write all structure objects to the MT5 bridge file (once)
        self.drawer.commit()

        # master multi-timeframe summary
        master = reporter.master_summary(results)
        print(master)
        reports.append(master)

        # persist the full report set
        try:
            with open(config.REPORT_FILE, "w", encoding="utf-8") as fh:
                fh.write(f"AURUM AI — Structure Mapping — {gmt_stamp()} GMT\n")
                fh.write("\n".join(reports))
            log.info("Report written -> %s", config.REPORT_FILE)
        except Exception as e:
            log.error("Report file write failed: %s", e)

        return results

    # ───────────────────────────────────────────────────────
    def run(self):
        self.startup()
        while self.running:
            try:
                if not self.mt5.is_connected():
                    raise MT5ConnectionError("MT5 link lost.")
                log.info("─── Structure mapping pass starting ───")
                self.run_pass()
                log.info("─── Pass complete ───")
            except MT5ConnectionError as e:
                log.error("MT5 error: %s — retrying in 30s", e)
                time.sleep(30)
                try:
                    self.mt5.connect()
                except Exception as ce:
                    log.error("Reconnect failed: %s", ce)
                continue
            except KeyboardInterrupt:
                log.info("KeyboardInterrupt — shutting down.")
                break
            except Exception as e:
                log.error("Unhandled error: %s\n%s", e, traceback.format_exc())

            if not config.RUN_CONTINUOUS:
                log.info("Single-pass mode — exiting.")
                break
            log.info("Next pass in %ds. Ctrl+C to stop.",
                     config.REFRESH_SECONDS)
            time.sleep(config.REFRESH_SECONDS)
        self.shutdown()

    def shutdown(self):
        self.mt5.disconnect()
        log.info("AURUM AI Step 1 offline.")


if __name__ == "__main__":
    agent = AurumStructureAgent()
    try:
        agent.run()
    except Exception as exc:
        log.critical("FATAL: %s\n%s", exc, traceback.format_exc())
        sys.exit(1)
