import sys
import sqlite3
from pathlib import Path

ROOT = Path("/opt/bourse-bot")
sys.path.insert(0, str(ROOT))

from app.analysis import oos_v5b
from app.analysis import backtest_final_v5b_2026 as v5b

DB_PATH = "/opt/bourse-bot/data/bourse.db"

START = 20260101
END = 20260921

PARAM_A = (0.42, 2.0, 3.5, 10)
PARAM_B = (0.46, 2.0, 3.5, 10)

INITIAL_CAPITAL = 100_000_000.0


def run_case(data, breadth, params):
    b, s, t, h = params

    candidates = oos_v5b.make_candidates(
        oos_v5b.BASE,
        data,
        breadth,
        b,
        s,
        t,
        h,
        START,
        END,
    )

    completed, curve, final, dd = oos_v5b.simulate(
        candidates,
        data,
        START,
        END,
    )

    metrics = oos_v5b.metrics(completed)

    return {
        "completed": completed,
        "curve": curve,
        "final": final,
        "dd": dd,
        "metrics": metrics,
    }


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
        f"{t.get('symbol', '')} | "
        f"entry={t.get('entry_price', 0):.0f} | "
        f"exit={t.get('exit_price', 0):.0f} | "
        f"{t.get('reason', '')} | "
        f"PnL={pnl(t):,.0f}"
    )


def print_performance(name, result):
    m = result["metrics"]
    final = result["final"]
    dd = result["dd"]

    print(f"\n{name}")
    print("-" * 60)
    print(f"Trades         : {m.get('trades', 0)}")
    print(f"Win rate       : {m.get('win_rate', 0) * 100:.2f}%")
    print(f"Profit factor  : {m.get('pf', 0):.2f}")
    print(f"Return         : {(final / INITIAL_CAPITAL - 1) * 100:.2f}%")
    print(f"Max DD         : {dd * 100:.2f}%")
    print(f"Final capital  : {final:,.0f}")
    print(f"Net PnL        : {sum(map(pnl, result['completed'])):,.0f}")


def main():
    conn = sqlite3.connect(DB_PATH)

    print("Loading data...", flush=True)

    data = v5b.load_data(conn)
    breadth = v5b.build_breadth(data)

    print("Caching technical signals...", flush=True)
    oos_v5b.BASE = oos_v5b.prepare_base(data)

    print("\n===== BREADTH COMPARISON =====")
    print("A = B=0.42 / S=2 / T=3.5 / H=10")
    print("B = B=0.46 / S=2 / T=3.5 / H=10")

    print("\nRunning A...", flush=True)
    a = run_case(data, breadth, PARAM_A)

    print("Running B...", flush=True)
    b = run_case(data, breadth, PARAM_B)

    trades_a = a["completed"]
    trades_b = b["completed"]

    ka = {key(t): t for t in trades_a}
    kb = {key(t): t for t in trades_b}

    common_keys = sorted(set(ka) & set(kb))
    only_a_keys = sorted(set(ka) - set(kb))
    only_b_keys = sorted(set(kb) - set(ka))

    common_a = [ka[k] for k in common_keys]
    only_a = [ka[k] for k in only_a_keys]
    only_b = [kb[k] for k in only_b_keys]

    print_performance("===== A: BREADTH 0.42 =====", a)
    print_performance("===== B: BREADTH 0.46 =====", b)

    print("\n===== TRADE OVERLAP =====")
    print(f"A trades       : {len(trades_a)}")
    print(f"B trades       : {len(trades_b)}")
    print(f"Common trades  : {len(common_keys)}")
    print(f"Only A (0.42)  : {len(only_a)}")
    print(f"Only B (0.46)  : {len(only_b)}")

    print("\n===== PNL OF DIFFERENCES =====")
    print(f"Common PnL     : {sum(map(pnl, common_a)):,.0f}")
    print(f"Only A PnL     : {sum(map(pnl, only_a)):,.0f}")
    print(f"Only B PnL     : {sum(map(pnl, only_b)):,.0f}")

    print("\n===== ONLY BREADTH 0.42 =====")
    if only_a:
        for t in sorted(
            only_a,
            key=lambda x: (x.get("entry_date"), x.get("symbol", "")),
        ):
            show_trade(t)
    else:
        print("NONE")

    print("\n===== ONLY BREADTH 0.46 =====")
    if only_b:
        for t in sorted(
            only_b,
            key=lambda x: (x.get("entry_date"), x.get("symbol", "")),
        ):
            show_trade(t)
    else:
        print("NONE")

    print("\n===== COMMON TRADES: 0.42 vs 0.46 =====")
    for k in common_keys:
        ta = ka[k]
        tb = kb[k]

        print(
            f"{ta.get('entry_date')} | "
            f"{ta.get('symbol', '')} | "
            f"A={pnl(ta):,.0f} | "
            f"B={pnl(tb):,.0f}"
        )

    print("\n===== DIFFERENCE =====")
    ret_a = a["final"] / INITIAL_CAPITAL - 1
    ret_b = b["final"] / INITIAL_CAPITAL - 1

    print(f"Return difference : {(ret_b - ret_a) * 100:+.2f} pp")
    print(f"Final difference  : {b['final'] - a['final']:+,.0f}")
    print(f"DD difference     : {(b['dd'] - a['dd']) * 100:+.2f} pp")
    print(f"Trade difference  : {len(trades_b) - len(trades_a):+d}")


if __name__ == "__main__":
    main()
