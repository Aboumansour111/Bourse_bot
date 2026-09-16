import itertools
import statistics
import sys
from pathlib import Path

# Allow imports from /opt/bourse-bot/app
APP_DIR = Path(__file__).resolve().parent
ANALYSIS_DIR = APP_DIR / "analysis"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

from analysis import regime_atr_v5b as regime


START_DATE = "20250101"
END_DATE = "20260915"

REGIMES = [
    "BREADTH",
    "BREADTH_MOMENTUM",
    "FULL",
]

BREADTH_LEVELS = [
    0.42,
    0.43,
    0.44,
    0.48,
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


def get_metric(result, names, default=0.0):
    for name in names:
        if name in result:
            return result[name]
    return default


def run_one(candidates, data, mode, breadth, stop_mult, target_mult):

    filtered = regime.apply_regime_filter(
        candidates,
        mode,
        breadth,
    )

    adjusted = []

    for candidate in filtered:
        entry = candidate["entry"]
        atr = candidate["atr"]

        if atr is None or atr <= 0:
            continue

        c = dict(candidate)

        c["stop"] = entry - stop_mult * atr
        c["target"] = entry + target_mult * atr

        adjusted.append(c)

    return regime.run(
        adjusted,
        data,
        START_DATE,
        END_DATE,
    )


def main():

    print("=" * 100)
    print("ROBUSTNESS REGION V1")
    print("=" * 100)
    print(f"Period: {START_DATE} -> {END_DATE}")
    print()

    print("Loading data...")
    data = regime.load_data()

    print(f"Valid symbols: {len(data)}")

    print("Building market context...")
    market_context = regime.build_market_context(data)

    print(f"Market dates: {len(market_context)}")

    print("Building technical pool...")
    pool = regime.build_pool(
        data,
        market_context,
    )

    print(f"Technical pool: {len(pool)}")

    print("Building base candidates...")

    base_candidates = regime.build_candidates(
        pool,
        data,
        1.50,
        3.00,
    )

    print(f"Base candidates: {len(base_candidates)}")
    print()

    results = []

    configs = list(
        itertools.product(
            REGIMES,
            BREADTH_LEVELS,
            ATR_CONFIGS,
        )
    )

    total = len(configs)

    print(f"Testing {total} configurations...")
    print()

    for idx, (mode, breadth, atr) in enumerate(configs, 1):

        stop_mult, target_mult = atr

        result = run_one(
            base_candidates,
            data,
            mode,
            breadth,
            stop_mult,
            target_mult,
        )

        trades = int(
            get_metric(
                result,
                [
                    "trades",
                    "accepted_trades",
                    "num_trades",
                ],
                0,
            )
        )

        ret = get_metric(
            result,
            [
                "return_pct",
                "total_return_pct",
                "return",
            ],
            0,
        )

        pf = get_metric(
            result,
            [
                "profit_factor",
                "pf",
            ],
            0,
        )

        dd = get_metric(
            result,
            [
                "max_drawdown_pct",
                "max_dd_pct",
                "max_dd",
            ],
            0,
        )

        win = get_metric(
            result,
            [
                "win_rate_pct",
                "win_rate",
            ],
            0,
        )

        results.append({
            "mode": mode,
            "breadth": breadth,
            "stop": stop_mult,
            "target": target_mult,
            "trades": trades,
            "return": ret,
            "pf": pf,
            "dd": dd,
            "win": win,
        })

        print(
            f"[{idx:02d}/{total}] "
            f"{mode:18s} "
            f"B={breadth:.2f} "
            f"S={stop_mult:.2f} "
            f"T={target_mult:.2f} "
            f"Trades={trades:3d} "
            f"Return={ret:8.2f}% "
            f"PF={pf:5.2f} "
            f"DD={dd:8.2f}%"
        )

    print()
    print("=" * 100)
    print("TOP CONFIGS — RETURN")
    print("=" * 100)

    top_return = sorted(
        results,
        key=lambda x: (
            x["return"],
            x["pf"],
            x["dd"],
        ),
        reverse=True,
    )

    for i, r in enumerate(top_return[:15], 1):
        print(
            f"{i:2d}. "
            f"{r['mode']:18s} "
            f"B={r['breadth']:.2f} "
            f"S={r['stop']:.2f} "
            f"T={r['target']:.2f} | "
            f"Trades={r['trades']:3d} | "
            f"Return={r['return']:.2f}% | "
            f"PF={r['pf']:.2f} | "
            f"DD={r['dd']:.2f}% | "
            f"Win={r['win']:.2f}%"
        )

    print()
    print("=" * 100)
    print("TOP CONFIGS — PROFIT FACTOR")
    print("=" * 100)

    top_pf = sorted(
        results,
        key=lambda x: (
            x["pf"],
            x["return"],
            x["dd"],
        ),
        reverse=True,
    )

    for i, r in enumerate(top_pf[:15], 1):
        print(
            f"{i:2d}. "
            f"{r['mode']:18s} "
            f"B={r['breadth']:.2f} "
            f"S={r['stop']:.2f} "
            f"T={r['target']:.2f} | "
            f"Trades={r['trades']:3d} | "
            f"Return={r['return']:.2f}% | "
            f"PF={r['pf']:.2f} | "
            f"DD={r['dd']:.2f}%"
        )

    print()
    print("=" * 100)
    print("LOWEST DRAWDOWN")
    print("=" * 100)

    lowest_dd = sorted(
        results,
        key=lambda x: (
            x["dd"],
            -x["return"],
        ),
        reverse=True,
    )

    for i, r in enumerate(lowest_dd[:15], 1):
        print(
            f"{i:2d}. "
            f"{r['mode']:18s} "
            f"B={r['breadth']:.2f} "
            f"S={r['stop']:.2f} "
            f"T={r['target']:.2f} | "
            f"Trades={r['trades']:3d} | "
            f"Return={r['return']:.2f}% | "
            f"PF={r['pf']:.2f} | "
            f"DD={r['dd']:.2f}%"
        )

    print()
    print("=" * 100)
    print("REGION AVERAGES")
    print("=" * 100)

    groups = {}

    for r in results:

        key = (
            r["mode"],
            r["breadth"],
        )

        groups.setdefault(key, []).append(r)

    for key, rows in sorted(groups.items()):

        mode, breadth = key

        avg_return = statistics.mean(
            x["return"] for x in rows
        )

        avg_pf = statistics.mean(
            x["pf"] for x in rows
        )

        avg_dd = statistics.mean(
            x["dd"] for x in rows
        )

        avg_trades = statistics.mean(
            x["trades"] for x in rows
        )

        print(
            f"{mode:18s} "
            f"B={breadth:.2f} | "
            f"AvgReturn={avg_return:8.2f}% | "
            f"AvgPF={avg_pf:5.2f} | "
            f"AvgDD={avg_dd:8.2f}% | "
            f"AvgTrades={avg_trades:5.1f}"
        )

    print()
    print("=" * 100)
    print("ROBUSTNESS TEST FINISHED")
    print("=" * 100)


if __name__ == "__main__":
    main()
