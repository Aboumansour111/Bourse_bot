import sys
import sqlite3
from pathlib import Path
from collections import defaultdict

ROOT = Path("/opt/bourse-bot")
sys.path.insert(0, str(ROOT))

from app.analysis import oos_v5b
from app.analysis import backtest_final_v5b_2026 as v5b

DB_PATH = "/opt/bourse-bot/data/bourse.db"

START = 20260101
END = 20260921

PARAM_A = (0.42, 2.0, 3.5, 10)
PARAM_B = (0.46, 2.0, 3.5, 10)


def run_case(data, breadth, params):
    completed, curve, final, dd = oos_v5b.run_one(
        data, breadth, params, START, END
    )
    return completed, final, dd


def key(t):
    return (
        t.get("inscode"),
        t.get("entry_date"),
    )


def pnl(t):
    return float(t.get("pnl", 0.0))


def show_trade(t):
    print(
        f"{t.get('entry_date')} | "
        f"{t.get('symbol','')} | "
        f"entry={t.get('entry_price',0):.0f} | "
        f"exit={t.get('exit_price',0):.0f} | "
        f"{t.get('reason','')} | "
        f"PnL={pnl(t):,.0f}"
    )


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading data...")
    data = v5b.load_data(conn)
    breadth = v5b.build_breadth(data)

    oos_v5b.BASE = oos_v5b.prepare_base(data)

    print("\n===== BREADTH COMPARISON =====")
    print("A = B=0.42 / S=2 / T=3.5 / H=10")
    print("B = B=0.46 / S=2 / T=3.5 / H=10")

    a, final_a, dd_a = run_case(data, breadth, PARAM_A)
    b, final_b, dd_b = run_case(data, breadth, PARAM_B)

    ka = {key(t): t for t in a}
    kb = {key(t): t for t in b}

    common_keys = sorted(set(ka) & set(kb))
    only_a_keys = sorted(set(ka) - set(kb))
    only_b_keys = sorted(set(kb) - set(ka))

    common_a = [ka[k] for k in common_keys]
    only_a = [ka[k] for k in only_a_keys]
    only_b = [kb[k] for k in only_b_keys]

    print("\n===== SUMMARY =====")
    print(f"A trades       : {len(a)}")
    print(f"B trades       : {len(b)}")
    print(f"Common trades  : {len(common_keys)}")
    print(f"Only A (0.42)  : {len(only_a)}")
    print(f"Only B (0.46)  : {len(only_b)}")

    print("\n===== PERFORMANCE =====")
    print(f"A final        : {final_a:,.0f}")
    print(f"A return       : {(final_a/100_000_000-1)*100:.2f}%")
    print(f"A max DD       : {dd_a*100:.2f}%")
    print(f"A PnL          : {sum(map(pnl,a)):,.0f}")

    print(f"\nB final        : {final_b:,.0f}")
    print(f"B return       : {(final_b/100_000_000-1)*100:.2f}%")
    print(f"B max DD       : {dd_b*100:.2f}%")
    print(f"B PnL          : {sum(map(pnl,b)):,.0f}")

    print("\n===== PNL OF DIFFERENCES =====")
    print(f"Common PnL     : {sum(map(pnl,common_a)):,.0f}")
    print(f"Only A PnL     : {sum(map(pnl,only_a)):,.0f}")
    print(f"Only B PnL     : {sum(map(pnl,only_b)):,.0f}")

    print("\n===== ONLY B=0.42 =====")
    if only_a:
        for t in sorted(only_a, key=lambda x: (x.get("entry_date"), x.get("symbol",""))):
            show_trade(t)
    else:
        print("NONE")

    print("\n===== ONLY B=0.46 =====")
    if only_b:
        for t in sorted(only_b, key=lambda x: (x.get("entry_date"), x.get("symbol",""))):
            show_trade(t)
    else:
        print("NONE")

    print("\n===== COMMON TRADES: A vs B =====")
    for k in common_keys:
        ta = ka[k]
        tb = kb[k]
        print(
            f"{ta.get('entry_date')} | {ta.get('symbol','')} | "
            f"A={pnl(ta):,.0f} | B={pnl(tb):,.0f}"
        )


if __name__ == "__main__":
    main()
