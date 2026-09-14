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

LOG_FILE = "/opt/bourse-bot/artifacts/v7a_yearly_report.txt"

def log(msg=""):
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")

def year_from_date(d):
    return d // 10000

def analyze_yearly(trades, equity_curve):
    if not trades:
        log("No trades.")
        return

    by_year = defaultdict(list)
    for t in trades:
        y = year_from_date(t["exit_date"])
        by_year[y].append(t)

    equity_by_year = defaultdict(list)
    for e in equity_curve:
        y = year_from_date(e["date"])
        equity_by_year[y].append(e["equity"])

    log("\n" + "="*100)
    log(f"{'Year':<6} {'Trades':>7} {'WinRate':>9} {'PF':>8} {'TotalPnL':>15} {'AvgRet%':>9} {'MaxDD%':>9} {'EndEquity':>15} {'% of PnL':>10}")
    log("="*100)

    total_pnl_all = sum(t["pnl"] for t in trades)
    years = sorted(by_year.keys())

    running_equity = INITIAL_CAPITAL
    yearly_results = []

    for y in years:
        year_trades = by_year[y]
        n = len(year_trades)
        winners = [t for t in year_trades if t["pnl"] > 0]
        losers  = [t for t in year_trades if t["pnl"] <= 0]

        win_rate = (len(winners) / n * 100) if n else 0.0
        avg_ret  = mean([t["return_pct"] for t in year_trades]) if year_trades else 0.0

        gp = sum(t["pnl"] for t in winners)
        gl = abs(sum(t["pnl"] for t in losers))
        pf = (gp / gl) if gl > 0 else float("inf")

        total_pnl = sum(t["pnl"] for t in year_trades)

        # Approximate intra-year max drawdown
        eqs = equity_by_year.get(y, [])
        max_dd = 0.0
        if eqs:
            peak = eqs[0]
            for eq in eqs:
                peak = max(peak, eq)
                dd = (eq - peak) / peak * 100.0
                max_dd = min(max_dd, dd)

        end_eq = eqs[-1] if eqs else running_equity + total_pnl
        running_equity = end_eq

        pct_of_total = (total_pnl / total_pnl_all * 100) if total_pnl_all != 0 else 0.0

        log(f"{y:<6} {n:>7} {win_rate:>8.1f}% {pf:>8.2f} {total_pnl:>15,.0f} {avg_ret:>8.2f}% {max_dd:>8.2f}% {end_eq:>15,.0f} {pct_of_total:>+9.1f}%")

        yearly_results.append({
            "year": y,
            "trades": n,
            "win_rate": win_rate,
            "pf": pf,
            "pnl": total_pnl,
            "avg_ret": avg_ret,
            "max_dd": max_dd,
            "end_equity": end_eq,
            "pct_total": pct_of_total
        })

    log("="*100)
    log(f"Total PnL all years : {total_pnl_all:,.0f}")
    log(f"Final equity        : {running_equity:,.0f}")

    log("\n--- Contribution of each year to total profit ---")
    for r in yearly_results:
        log(f"{r['year']}: {r['pct_total']:+.1f}%")

def main():
    # Clear previous log
    open(LOG_FILE, "w", encoding="utf-8").close()

    try:
        conn = sqlite3.connect(DB_PATH)
        log("Loading data...")
        data = load_data(conn)
        conn.close()
        log(f"Valid symbols: {len(data)}")

        log("Building breadth...")
        breadth = build_breadth(data)
        log(f"Breadth dates: {len(breadth)}")

        log("Generating candidates...")
        candidates = generate_candidates(data, breadth)
        log(f"Candidates: {len(candidates)}")

        log("Simulating portfolio...")
        trades, equity_curve, final_equity, max_dd = simulate_portfolio(candidates, data)

        log(f"\nAccepted trades : {len(trades)}")
        log(f"Final equity    : {final_equity:,.0f}")
        log(f"Overall Max DD  : {max_dd:.2f}%")

        analyze_yearly(trades, equity_curve)

        log("\n[DONE] Report finished successfully.")
        log(f"Full report saved to: {LOG_FILE}")

    except Exception as e:
        log("\n[ERROR] " + str(e))
        log(traceback.format_exc())

if __name__ == "__main__":
    main()
