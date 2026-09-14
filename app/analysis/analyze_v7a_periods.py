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

LOG_FILE = "/opt/bourse-bot/artifacts/v7a_periods_report.txt"

PERIODS = [
    (2007, 2010),
    (2011, 2014),
    (2015, 2017),
    (2018, 2020),
    (2021, 2023),
    (2024, 2026),
]

def log(msg=""):
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")

def year_from_date(d):
    return d // 10000

def filter_trades_by_period(trades, start_year, end_year):
    return [t for t in trades if start_year <= year_from_date(t["exit_date"]) <= end_year]

def analyze_period(name, trades, equity_curve, start_year, end_year):
    period_trades = filter_trades_by_period(trades, start_year, end_year)
    n = len(period_trades)

    log(f"\n{'='*70}")
    log(f"PERIOD: {name} ({start_year}-{end_year})")
    log(f"{'='*70}")
    log(f"Trades: {n}")

    if n == 0:
        log("No trades in this period.")
        return

    winners = [t for t in period_trades if t["pnl"] > 0]
    losers  = [t for t in period_trades if t["pnl"] <= 0]

    win_rate = len(winners) / n * 100
    avg_ret  = mean([t["return_pct"] for t in period_trades])
    total_pnl = sum(t["pnl"] for t in period_trades)

    gp = sum(t["pnl"] for t in winners)
    gl = abs(sum(t["pnl"] for t in losers))
    pf = (gp / gl) if gl > 0 else float("inf")

    expectancy = (win_rate/100 * mean([t["return_pct"] for t in winners]) if winners else 0) + \
                 ((1 - win_rate/100) * mean([t["return_pct"] for t in losers]) if losers else 0)

    # Approximate max DD in period from equity curve
    eqs = [e["equity"] for e in equity_curve if start_year <= year_from_date(e["date"]) <= end_year]
    max_dd = 0.0
    if eqs:
        peak = eqs[0]
        for eq in eqs:
            peak = max(peak, eq)
            dd = (eq - peak) / peak * 100
            max_dd = min(max_dd, dd)

    log(f"Win rate       : {win_rate:.1f}%")
    log(f"Profit Factor  : {pf:.2f}")
    log(f"Total PnL      : {total_pnl:,.0f}")
    log(f"Avg return     : {avg_ret:.2f}%")
    log(f"Expectancy     : {expectancy:.2f}%")
    log(f"Max DD (approx): {max_dd:.2f}%")

def main():
    open(LOG_FILE, "w", encoding="utf-8").close()

    try:
        conn = sqlite3.connect(DB_PATH)
        log("Loading data...")
        data = load_data(conn)
        conn.close()

        log("Building breadth...")
        breadth = build_breadth(data)

        log("Generating candidates...")
        candidates = generate_candidates(data, breadth)

        log("Simulating full portfolio...")
        trades, equity_curve, final_equity, max_dd = simulate_portfolio(candidates, data)

        log(f"Total accepted trades: {len(trades)}")
        log(f"Final equity: {final_equity:,.0f}")
        log(f"Overall Max DD: {max_dd:.2f}%")

        for start, end in PERIODS:
            name = f"{start}-{end}"
            analyze_period(name, trades, equity_curve, start, end)

        log("\n[DONE]")
        log(f"Report saved to: {LOG_FILE}")

    except Exception as e:
        log("[ERROR] " + str(e))
        log(traceback.format_exc())

if __name__ == "__main__":
    main()
