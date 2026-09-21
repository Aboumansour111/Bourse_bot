import csv
import sqlite3
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, "/opt/bourse-bot")

from app.analysis import oos_v5b as oos
from app.analysis import backtest_final_v5b_2026 as v5b

DB_PATH = "/opt/bourse-bot/data/bourse.db"
OUT = Path("/opt/bourse-bot/data/v5b1_robustness.csv")

BREADTHS = [0.42, 0.46, 0.50]
STOPS = [1.75, 2.00, 2.25]
TARGETS = [3.00, 3.50, 4.00]
HOLDS = [10, 12]

PARAMS = list(product(BREADTHS, STOPS, TARGETS, HOLDS))


def run_period(data, breadth, params, start_date, end_date):
    b, s, t, h = params

    candidates = oos.make_candidates(
        oos.BASE,
        data,
        breadth,
        b, s, t, h,
        start_date,
        end_date,
    )

    completed, curve, final, dd = oos.simulate(
        candidates,
        data,
        start_date,
        end_date,
    )

    m = oos.metrics(completed)

    ret = final / v5b.INITIAL_CAPITAL - 1

    return {
        "trades": m["trades"],
        "win_rate": m["win_rate"],
        "pf": m["pf"],
        "return": ret,
        "dd": dd,
        "final": final,
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    data = v5b.load_data(conn)
    conn.close()

    breadth = v5b.build_breadth(data)
    oos.BASE = oos.prepare_base(data)

    rows = []

    print(f"\n===== V5B.1 ROBUSTNESS =====")
    print(f"Combinations: {len(PARAMS)}")
    print()

    for i, params in enumerate(PARAMS, 1):
        train = run_period(
            data,
            breadth,
            params,
            20260101,
            20260630,
        )

        oos_result = run_period(
            data,
            breadth,
            params,
            20260701,
            20260921,
        )

        b, s, t, h = params

        row = {
            "breadth": b,
            "stop_atr": s,
            "target_atr": t,
            "hold_days": h,

            "train_trades": train["trades"],
            "train_return": train["return"],
            "train_win_rate": train["win_rate"],
            "train_pf": train["pf"],
            "train_dd": train["dd"],

            "oos_trades": oos_result["trades"],
            "oos_return": oos_result["return"],
            "oos_win_rate": oos_result["win_rate"],
            "oos_pf": oos_result["pf"],
            "oos_dd": oos_result["dd"],
        }

        rows.append(row)

        print(
            f"[{i:02d}/{len(PARAMS)}] "
            f"B={b:.2f} S={s:.2f} T={t:.2f} H={h:2d} | "
            f"OOS R={oos_result['return']*100:6.2f}% "
            f"PF={oos_result['pf']:5.2f} "
            f"WR={oos_result['win_rate']*100:5.1f}% "
            f"DD={oos_result['dd']*100:6.2f}% "
            f"N={oos_result['trades']:2d}"
        )

    fields = list(rows[0].keys())

    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print("\n===== TOP OOS RETURN =====")
    for r in sorted(rows, key=lambda x: x["oos_return"], reverse=True)[:15]:
        print(
            f"B={r['breadth']:.2f} "
            f"S={r['stop_atr']:.2f} "
            f"T={r['target_atr']:.2f} "
            f"H={r['hold_days']:2d} | "
            f"N={r['oos_trades']:2d} "
            f"R={r['oos_return']*100:6.2f}% "
            f"WR={r['oos_win_rate']*100:5.1f}% "
            f"PF={r['oos_pf']:5.2f} "
            f"DD={r['oos_dd']*100:6.2f}%"
        )

    print("\n===== TOP OOS PF =====")
    valid = [r for r in rows if r["oos_trades"] >= 20]

    for r in sorted(valid, key=lambda x: x["oos_pf"], reverse=True)[:15]:
        print(
            f"B={r['breadth']:.2f} "
            f"S={r['stop_atr']:.2f} "
            f"T={r['target_atr']:.2f} "
            f"H={r['hold_days']:2d} | "
            f"N={r['oos_trades']:2d} "
            f"R={r['oos_return']*100:6.2f}% "
            f"WR={r['oos_win_rate']*100:5.1f}% "
            f"PF={r['oos_pf']:5.2f} "
            f"DD={r['oos_dd']*100:6.2f}%"
        )

    print("\n===== ROBUST OOS =====")

    robust = [
        r for r in rows
        if r["oos_trades"] >= 20
        and r["oos_pf"] >= 3.0
        and r["oos_dd"] >= -0.07
        and r["train_pf"] >= 1.5
    ]

    for r in sorted(
        robust,
        key=lambda x: (
            x["oos_return"],
            x["oos_pf"],
            x["oos_dd"],
        ),
        reverse=True,
    ):
        print(
            f"B={r['breadth']:.2f} "
            f"S={r['stop_atr']:.2f} "
            f"T={r['target_atr']:.2f} "
            f"H={r['hold_days']:2d} | "
            f"OOS N={r['oos_trades']:2d} "
            f"R={r['oos_return']*100:6.2f}% "
            f"PF={r['oos_pf']:5.2f} "
            f"DD={r['oos_dd']*100:6.2f}% | "
            f"TRAIN PF={r['train_pf']:5.2f}"
        )

    print(f"\nSaved: {OUT}")


if __name__ == "__main__":
    main()
