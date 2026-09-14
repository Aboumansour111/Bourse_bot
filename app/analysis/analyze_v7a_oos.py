import sqlite3
from collections import defaultdict
from statistics import mean
import sys
import traceback

sys.path.insert(0, "/opt/bourse-bot")

from app.analysis.backtest_final_v7a import (
    load_data, build_breadth, generate_candidates,
    simulate_portfolio, INITIAL_CAPITAL, DB_PATH
)

LOG_FILE = "/opt/bourse-bot/artifacts/v7a_oos_report.txt"

def log(msg=""):
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")

def year_from_date(d):
    return d // 10000

def filter_candidates_by_entry_year(candidates, max_year):
    """Keep only candidates whose entry_date year <= max_year"""
    return [c for c in candidates if year_from_date(c["entry_date"]) <= max_year]

def run_simulation_on_candidates(candidates, data, label):
    log(f"\n{'='*70}")
    log(f"{label}")
    log(f"{'='*70}")
    log(f"Candidates: {len(candidates)}")

    if not candidates:
        log("No candidates.")
        return

    trades, equity_curve, final_equity, max_dd = simulate_portfolio(candidates, data)

    n = len(trades)
    log(f"Accepted trades: {n}")

    if n == 0:
        log("No accepted trades.")
        return

    winners = [t for t in trades if t["pnl"] > 0]
    losers  = [t for t in trades if t["pnl"] <= 0]

    win_rate = len(winners) / n * 100
    avg_ret  = mean([t["return_pct"] for t in trades])
    total_pnl = sum(t["pnl"] for t in trades)

    gp = sum(t["pnl"] for t in winners)
    gl = abs(sum(t["pnl"] for t in losers))
    pf = (gp / gl) if gl > 0 else float("inf")

    total_return = (final_equity / INITIAL_CAPITAL - 1) * 100

    log(f"Final equity     : {final_equity:,.0f}")
    log(f"Total return     : {total_return:.2f}%")
    log(f"Win rate         : {win_rate:.1f}%")
    log(f"Profit Factor    : {pf:.2f}")
    log(f"Avg return/trade : {avg_ret:.2f}%")
    log(f"Max Drawdown     : {max_dd:.2f}%")
    log(f"Total PnL        : {total_pnl:,.0f}")

def main():
    open(LOG_FILE, "w", encoding="utf-8").close()

    try:
        conn = sqlite3.connect(DB_PATH)
        log("Loading data...")
        data = load_data(conn)
        conn.close()

        log("Building breadth...")
        breadth = build_breadth(data)

        log("Generating ALL candidates...")
        all_candidates = generate_candidates(data, breadth)
        log(f"Total candidates: {len(all_candidates)}")

        # In-Sample: entry up to 2022
        is_candidates = filter_candidates_by_entry_year(all_candidates, 2022)
        run_simulation_on_candidates(is_candidates, data, "IN-SAMPLE (entry <= 2022)")

        # Out-of-Sample: entry 2023+
        oos_candidates = [c for c in all_candidates if year_from_date(c["entry_date"]) >= 2023]
        run_simulation_on_candidates(oos_candidates, data, "OUT-OF-SAMPLE (entry >= 2023)")

        # Extra: only 2024-2026 for clarity
        recent = [c for c in all_candidates if year_from_date(c["entry_date"]) >= 2024]
        run_simulation_on_candidates(recent, data, "RECENT ONLY (entry >= 2024)")

        log("\n[DONE]")
        log(f"Report saved to: {LOG_FILE}")

    except Exception as e:
        log("[ERROR] " + str(e))
        log(traceback.format_exc())

if __name__ == "__main__":
    main()
