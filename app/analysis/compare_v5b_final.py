import sqlite3
import sys

sys.path.insert(0, "/opt/bourse-bot")

from app.analysis import oos_v5b as oos
from app.analysis import backtest_final_v5b_2026 as v5b

DB_PATH = "/opt/bourse-bot/data/bourse.db"

STRATEGIES = [
    ("V5B_CURRENT", 0.42, 1.50, 3.00, 10),
    ("V5B_1",       0.46, 2.00, 3.50, 10),
    ("V5B_1_SAFE",  0.42, 2.00, 3.50, 10),
]

START = 20260101
END = 20260921


def run_strategy(data, breadth, name, b, s, t, h):
    candidates = oos.make_candidates(
        oos.BASE,
        data,
        breadth,
        b, s, t, h,
        START,
        END,
    )

    completed, curve, final, dd = oos.simulate(
        candidates,
        data,
        START,
        END,
    )

    m = oos.metrics(completed)

    return {
        "name": name,
        "breadth": b,
        "stop": s,
        "target": t,
        "hold": h,
        "trades": m["trades"],
        "win_rate": m["win_rate"],
        "pf": m["pf"],
        "return": final / v5b.INITIAL_CAPITAL - 1,
        "dd": dd,
        "final": final,
        "completed": completed,
    }


def monthly_results(data, breadth, b, s, t, h):
    periods = [
        ("JAN", 20260101, 20260131),
        ("FEB", 20260201, 20260228),
        ("MAR", 20260301, 20260331),
        ("APR", 20260401, 20260430),
        ("MAY", 20260501, 20260531),
        ("JUN", 20260601, 20260630),
        ("JUL", 20260701, 20260731),
        ("AUG", 20260801, 20260831),
        ("SEP", 20260901, 20260921),
    ]

    result = []

    for month, start, end in periods:
        candidates = oos.make_candidates(
            oos.BASE,
            data,
            breadth,
            b, s, t, h,
            start,
            end,
        )

        completed, curve, final, dd = oos.simulate(
            candidates,
            data,
            start,
            end,
        )

        m = oos.metrics(completed)

        result.append({
            "month": month,
            "trades": m["trades"],
            "return": final / v5b.INITIAL_CAPITAL - 1,
            "win_rate": m["win_rate"],
            "pf": m["pf"],
            "dd": dd,
        })

    return result


def main():
    conn = sqlite3.connect(DB_PATH)
    data = v5b.load_data(conn)
    conn.close()

    breadth = v5b.build_breadth(data)
    oos.BASE = oos.prepare_base(data)

    results = []

    for name, b, s, t, h in STRATEGIES:
        print(
            f"\nRunning {name}: "
            f"B={b} S={s} T={t} H={h}"
        )

        r = run_strategy(data, breadth, name, b, s, t, h)
        results.append(r)

    print("\n" + "=" * 90)
    print("===== FULL 2026 COMPARISON =====")
    print("=" * 90)

    print(
        f"{'STRATEGY':15s} "
        f"{'TRADES':>7s} "
        f"{'RETURN':>10s} "
        f"{'WIN':>8s} "
        f"{'PF':>7s} "
        f"{'DD':>9s} "
        f"{'FINAL':>15s}"
    )

    for r in results:
        print(
            f"{r['name']:15s} "
            f"{r['trades']:7d} "
            f"{r['return']*100:9.2f}% "
            f"{r['win_rate']*100:7.2f}% "
            f"{r['pf']:7.2f} "
            f"{r['dd']*100:8.2f}% "
            f"{r['final']:15,.0f}"
        )

    for r in results:
        print("\n" + "=" * 90)
        print(
            f"===== MONTHLY: {r['name']} "
            f"(B={r['breadth']} S={r['stop']} "
            f"T={r['target']} H={r['hold']}) ====="
        )
        print("=" * 90)

        monthly = monthly_results(
            data,
            breadth,
            r["breadth"],
            r["stop"],
            r["target"],
            r["hold"],
        )

        for m in monthly:
            print(
                f"{m['month']:3s} | "
                f"N={m['trades']:2d} | "
                f"R={m['return']*100:7.2f}% | "
                f"WR={m['win_rate']*100:6.2f}% | "
                f"PF={m['pf']:5.2f} | "
                f"DD={m['dd']*100:7.2f}%"
            )

    print("\n" + "=" * 90)
    print("===== EXIT DISTRIBUTION =====")
    print("=" * 90)

    for r in results:
        counts = {}

        for x in r["completed"]:
            reason = x.get("reason", "UNKNOWN")
            counts[reason] = counts.get(reason, 0) + 1

        print(
            f"{r['name']:15s} | "
            f"TARGET={counts.get('TARGET', 0):2d} "
            f"STOP={counts.get('STOP', 0):2d} "
            f"TIME={counts.get('TIME', 0):2d}"
        )

    print("\n" + "=" * 90)
    print("===== TOP SYMBOL CONCENTRATION =====")
    print("=" * 90)

    from collections import defaultdict

    for r in results:
        by_symbol = defaultdict(float)

        for x in r["completed"]:
            by_symbol[x["symbol"]] += float(x.get("pnl", 0))

        items = sorted(
            by_symbol.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        total = sum(by_symbol.values())

        top1 = sum(x[1] for x in items[:1])
        top3 = sum(x[1] for x in items[:3])
        top5 = sum(x[1] for x in items[:5])

        print(
            f"{r['name']:15s} | "
            f"Unique={len(items):2d} | "
            f"TOP1={top1:,.0f} ({top1/total*100:5.1f}%) | "
            f"TOP3={top3:,.0f} ({top3/total*100:5.1f}%) | "
            f"TOP5={top5:,.0f} ({top5/total*100:5.1f}%)"
        )


if __name__ == "__main__":
    main()
