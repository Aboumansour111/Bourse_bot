import sqlite3
from collections import defaultdict
from statistics import mean, median, stdev
import sys
import traceback

sys.path.insert(0, "/opt/bourse-bot")

from app.analysis.backtest_final_v7a import (
    load_data, build_breadth, generate_candidates,
    simulate_portfolio, INITIAL_CAPITAL, DB_PATH
)

LOG_FILE = "/opt/bourse-bot/artifacts/v7a_trade_distribution.txt"

def log(msg=""):
    print(msg)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")

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

        log("Simulating portfolio...")
        trades, equity_curve, final_equity, max_dd = simulate_portfolio(candidates, data)

        log(f"Accepted trades: {len(trades)}")
        log(f"Final equity: {final_equity:,.0f}")
        log(f"Overall Max DD: {max_dd:.2f}%\n")

        if not trades:
            log("No trades.")
            return

        # Sort by PnL descending
        sorted_by_pnl = sorted(trades, key=lambda x: x["pnl"], reverse=True)
        returns = [t["return_pct"] for t in trades]
        pnls = [t["pnl"] for t in trades]

        total_pnl = sum(pnls)
        total_profit = sum(p for p in pnls if p > 0)
        total_loss = abs(sum(p for p in pnls if p <= 0))

        log("="*70)
        log("TRADE DISTRIBUTION ANALYSIS")
        log("="*70)

        log(f"\nTotal trades          : {len(trades)}")
        log(f"Total PnL             : {total_pnl:,.0f}")
        log(f"Gross Profit          : {total_profit:,.0f}")
        log(f"Gross Loss            : {total_loss:,.0f}")
        log(f"Profit Factor         : {total_profit/total_loss:.2f}" if total_loss > 0 else "inf")

        log(f"\nAverage return/trade  : {mean(returns):.2f}%")
        log(f"Median return/trade   : {median(returns):.2f}%")
        log(f"Std Dev of returns    : {stdev(returns):.2f}%" if len(returns) > 1 else "N/A")

        # Contribution of top trades
        log("\n--- Contribution of best trades ---")
        for k in [1, 3, 5, 10]:
            top_k_pnl = sum(t["pnl"] for t in sorted_by_pnl[:k])
            pct = (top_k_pnl / total_pnl * 100) if total_pnl != 0 else 0
            log(f"Top {k:2d} trades contribute : {top_k_pnl:>12,.0f}  ({pct:+.1f}% of total PnL)")

        # What if we remove top 5 and top 10
        log("\n--- Result after removing best trades ---")
        for k in [5, 10]:
            remaining = sorted_by_pnl[k:]
            if not remaining:
                log(f"After removing top {k}: no trades left")
                continue
            rem_pnl = sum(t["pnl"] for t in remaining)
            rem_rets = [t["return_pct"] for t in remaining]
            rem_win = sum(1 for t in remaining if t["pnl"] > 0) / len(remaining) * 100
            log(f"After removing top {k}:")
            log(f"  Trades left     : {len(remaining)}")
            log(f"  Remaining PnL   : {rem_pnl:,.0f}")
            log(f"  Win rate        : {rem_win:.1f}%")
            log(f"  Avg return      : {mean(rem_rets):.2f}%")
            log(f"  Final equity approx: {INITIAL_CAPITAL + rem_pnl:,.0f}")

        # Best and worst lists (already known, but for completeness)
        log("\n--- Best 10 trades (by PnL) ---")
        for i, t in enumerate(sorted_by_pnl[:10], 1):
            log(f"{i:2d}. {t['symbol']:<10} {t['entry_date']} → {t['exit_date']}  "
                f"PnL={t['pnl']:>10,.0f}  Ret={t['return_pct']:>6.2f}%  {t['reason']}")

        log("\n--- Worst 10 trades (by PnL) ---")
        for i, t in enumerate(sorted_by_pnl[-10:][::-1], 1):
            log(f"{i:2d}. {t['symbol']:<10} {t['entry_date']} → {t['exit_date']}  "
                f"PnL={t['pnl']:>10,.0f}  Ret={t['return_pct']:>6.2f}%  {t['reason']}")

        log("\n[DONE]")
        log(f"Report saved to: {LOG_FILE}")

    except Exception as e:
        log("[ERROR] " + str(e))
        log(traceback.format_exc())

if __name__ == "__main__":
    main()
