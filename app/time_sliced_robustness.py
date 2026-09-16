import sys
import os

sys.path.insert(0, "/opt/bourse-bot/app")
sys.path.insert(0, "/opt/bourse-bot/app/analysis")

import regime_atr_v5b as regime


WINDOWS = [
    ("2025-H1", 20250101, 20250630),
    ("2025-H2", 20250701, 20251231),
    ("2026-H1", 20260101, 20260630),
    ("2026-H2", 20260701, 20260915),
]

MODES = [
    "BREADTH",
    "BREADTH_MOMENTUM",
    "FULL",
]

BREADTHS = [
    0.42,
    0.44,
    0.50,
]

ATR_CONFIGS = [
    (1.00, 3.50),
    (1.00, 3.75),
    (1.10, 3.50),
    (1.10, 3.75),
    (1.20, 3.50),
    (1.20, 3.75),
]


def metric(result, names, default=0.0):
    for name in names:
        if name in result:
            return result[name]
    return default


print("=" * 120)
print("TIME-SLICED ROBUSTNESS")
print("=" * 120)

print("Loading data...")

data = regime.load_data()
print(f"Valid symbols: {len(data)}")

market_context = regime.build_market_context(data)
print(f"Market dates: {len(market_context)}")

pool = regime.build_pool(data)
print(f"Technical pool: {len(pool)}")

candidates_by_config = {}

for mode in MODES:
    for breadth in BREADTHS:
        for stop_mult, target_mult in ATR_CONFIGS:

            key = (mode, breadth, stop_mult, target_mult)

            candidates = regime.build_candidates(
                pool,
                stop_mult,
                target_mult,
            )

            candidates = regime.apply_regime_filter(
                candidates,
                market_context,
                mode,
                breadth,
            )

            candidates_by_config[key] = candidates


print()
print("=" * 120)
print("RUNNING 54 CONFIGURATIONS x 4 TIME WINDOWS")
print("=" * 120)

all_results = []

total = len(MODES) * len(BREADTHS) * len(ATR_CONFIGS)
counter = 0

for mode in MODES:
    for breadth in BREADTHS:
        for stop_mult, target_mult in ATR_CONFIGS:

            key = (mode, breadth, stop_mult, target_mult)
            candidates = candidates_by_config[key]

            for window_name, start_date, end_date in WINDOWS:

                counter += 1

                result = regime.run(
                    candidates,
                    data,
                    start_date,
                    end_date,
                )

                trades = int(
                    metric(
                        result,
                        ["trades", "accepted_trades", "num_trades"],
                        0,
                    )
                )

                ret = metric(
                    result,
                    ["return_pct", "total_return_pct", "return"],
                    0.0,
                )

                pf = metric(
                    result,
                    ["profit_factor", "pf"],
                    0.0,
                )

                dd = metric(
                    result,
                    ["max_drawdown_pct", "max_dd_pct", "max_dd", "dd"],
                    0.0,
                )

                win = metric(
                    result,
                    ["win_rate_pct", "win_rate", "win"],
                    0.0,
                )

                row = {
                    "window": window_name,
                    "mode": mode,
                    "breadth": breadth,
                    "stop": stop_mult,
                    "target": target_mult,
                    "trades": trades,
                    "return": ret,
                    "pf": pf,
                    "dd": dd,
                    "win": win,
                }

                all_results.append(row)

                print(
                    f"[{counter:03d}] "
                    f"{window_name:8s} "
                    f"{mode:18s} "
                    f"B={breadth:.2f} "
                    f"S={stop_mult:.2f} "
                    f"T={target_mult:.2f} | "
                    f"Trades={trades:3d} | "
                    f"Return={ret:8.2f}% | "
                    f"PF={pf:5.2f} | "
                    f"DD={dd:7.2f}% | "
                    f"Win={win:6.2f}%"
                )


print()
print("=" * 120)
print("AGGREGATED BY CONFIGURATION")
print("=" * 120)

configs = {}

for row in all_results:
    key = (
        row["mode"],
        row["breadth"],
        row["stop"],
        row["target"],
    )

    configs.setdefault(key, []).append(row)


summary = []

for key, rows in configs.items():

    mode, breadth, stop, target = key

    returns = [r["return"] for r in rows]
    pfs = [r["pf"] for r in rows]
    dds = [r["dd"] for r in rows]
    wins = [r["win"] for r in rows]
    trades = [r["trades"] for r in rows]

    positive_windows = sum(1 for x in returns if x > 0)
    valid_windows = sum(1 for x in trades if x >= 5)

    summary.append({
        "mode": mode,
        "breadth": breadth,
        "stop": stop,
        "target": target,
        "avg_return": sum(returns) / len(returns),
        "min_return": min(returns),
        "max_return": max(returns),
        "avg_pf": sum(pfs) / len(pfs),
        "min_pf": min(pfs),
        "avg_dd": sum(dds) / len(dds),
        "worst_dd": min(dds),
        "avg_win": sum(wins) / len(wins),
        "total_trades": sum(trades),
        "positive_windows": positive_windows,
        "valid_windows": valid_windows,
    })


summary.sort(
    key=lambda x: (
        x["positive_windows"],
        x["valid_windows"],
        x["avg_return"],
        x["avg_pf"],
    ),
    reverse=True,
)


print()
print("=" * 120)
print("TOP CONFIGURATIONS — TIME STABILITY")
print("=" * 120)

for i, r in enumerate(summary[:30], 1):

    print(
        f"{i:2d}. "
        f"{r['mode']:18s} "
        f"B={r['breadth']:.2f} "
        f"S={r['stop']:.2f} "
        f"T={r['target']:.2f} | "
        f"AvgRet={r['avg_return']:7.2f}% | "
        f"MinRet={r['min_return']:7.2f}% | "
        f"MaxRet={r['max_return']:7.2f}% | "
        f"AvgPF={r['avg_pf']:5.2f} | "
        f"MinPF={r['min_pf']:5.2f} | "
        f"AvgDD={r['avg_dd']:7.2f}% | "
        f"WorstDD={r['worst_dd']:7.2f}% | "
        f"Win={r['positive_windows']}/4 | "
        f"Valid={r['valid_windows']}/4 | "
        f"Trades={r['total_trades']}"
    )


print()
print("=" * 120)
print("WINDOW LEADERS")
print("=" * 120)

for window_name, start_date, end_date in WINDOWS:

    rows = [
        r for r in all_results
        if r["window"] == window_name
    ]

    rows.sort(
        key=lambda r: (
            r["return"],
            r["pf"],
        ),
        reverse=True,
    )

    print()
    print(f"--- {window_name} ({start_date} -> {end_date}) ---")

    for i, r in enumerate(rows[:10], 1):

        print(
            f"{i:2d}. "
            f"{r['mode']:18s} "
            f"B={r['breadth']:.2f} "
            f"S={r['stop']:.2f} "
            f"T={r['target']:.2f} | "
            f"Trades={r['trades']:3d} | "
            f"Return={r['return']:7.2f}% | "
            f"PF={r['pf']:5.2f} | "
            f"DD={r['dd']:7.2f}% | "
            f"Win={r['win']:6.2f}%"
        )


print()
print("=" * 120)
print("TIME-SLICED ROBUSTNESS FINISHED")
print("=" * 120)
