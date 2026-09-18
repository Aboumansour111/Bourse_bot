import os
import subprocess
import sys
import re

BASE = "/opt/bourse-bot"
SCRIPT = os.path.join(BASE, "app/analysis/backtest_atr_test.py")

TESTS = [
    ("1.0", "3.0"),
    ("1.0", "3.5"),
    ("1.0", "4.0"),
    ("1.2", "3.5"),
    ("1.8", "3.0"),
    ("2.0", "3.0"),
]

def run(label, start, end, stop_atr, target_atr):
    env = os.environ.copy()
    env["STOP_ATR"] = stop_atr
    env["TARGET_ATR"] = target_atr
    env["BACKTEST_START"] = start + "0101"
    env["BACKTEST_END"] = end + "1231"

    result = subprocess.run(
        [sys.executable, SCRIPT],
        cwd=BASE,
        env=env,
        capture_output=True,
        text=True,
    )

    output = result.stdout + "\n" + result.stderr

    lines = []
    for line in output.splitlines():
        if any(key in line for key in [
            "Candidate trades:",
            "Accepted trades:",
            "Total return:",
            "Win rate:",
            "Average return/trade:",
            "Profit factor:",
            "Max drawdown:",
            "First date:",
            "Last date:",
        ]):
            lines.append(line.strip())

    print(f"\n===== {label} | {start}-{end} | STOP={stop_atr} TARGET={target_atr} =====")
    for line in lines:
        print(line)

    if result.returncode != 0:
        print("RETURN CODE:", result.returncode)

for stop_atr, target_atr in TESTS:
    label = f"{stop_atr}/{target_atr}"

    # Train
    run(label, "2025", "2025", stop_atr, target_atr)

    # OOS
    run(label, "2026", "2026", stop_atr, target_atr)
