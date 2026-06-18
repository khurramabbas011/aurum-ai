@echo off
REM ═══════════════════════════════════════════════════════════
REM AURUM AI — 24/7 launcher for Windows (VPS or local PC)
REM Double-click to run, or point Windows Task Scheduler at it
REM with trigger "At log on" / "At startup" for auto-start.
REM ═══════════════════════════════════════════════════════════
cd /d "%~dp0"
:loop
echo [AURUM] starting supervisor %date% %time%
python supervisor.py
echo [AURUM] supervisor exited — restarting in 10s
timeout /t 10 /nobreak >nul
goto loop
