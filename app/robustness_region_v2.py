import itertools
import statistics
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ANALYSIS_DIR = APP_DIR / "analysis"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

from analysis import regime_atr_v5b as regime


START_DATE = 20250101
END_DATE = 20260915

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


def pct(x):
    return f"{x:.2f}%"


def metric(result, names, default=0.0):
    for name in names:
        if name in result:
            return result[name]
    return default


def main():

    print("=" * 110)
    print("ROBUSTNESS REGION V2")
    print("=" * 110)
    print(f"Period: {START_DATE} -> {END_DATE}")
    print("Testing: 3 regimes x 5 breadth x 6 ATR = 90 configurations")
    print()

    print("Loading data...")
    data = regime.load_data()
    print(f"Valid symbols: {len(data)}")

    print("Building market context...")
    context = regime.build_market_context(data)
    print(f"Market dates: {len(context)}")

    print("Building technical pool...")
    pool = regime.build_pool(data)
    print(f"Technical pool: {len(pool)}")

    print()
    print("=" * 110)
    print("RUNNING CONFIGURATIONS")
    print("=" * 110)

    results = []

    configs = list(
        itertools.product(
            REGIMES,
            BREADTH_LEVELS,
            ATR_CONFIGS,
        )
    )

    total = len(configs)

    for n, (mode, breadth, atr) in enumerate(configs, 1):

        stop_mult, target_mult = atr

        # IMPORTANT:
        # ATR stop/target are created here, before regime filtering.
        candidates = regime.build_candidates(
            pool,
            stop_mult,
            target_mult,
        )

        filtered = regime.apply_regime_filter(
            candidates,
            context,
            mode,
            breadth,
        )

        result = regime.run(
            filtered,
            data,
            START_DATE,
            END_DATE,
        )

        trades = int(
            metric(
                result,
                [
                    "trades",
                    "accepted_trades",
                    "num_trades",
                ],
                0,
            )
        )

        ret = metric(
            result,
            [
                "return_pct",
                "total_return_pct",
                "return",
            ],
            0.0,
        )

        pf = metric(
            result,
            [
                "profit_factor",
                "pf",
            ],
            0.0,
        )

        dd = metric(
            result,
            [
                "max_drawdown_pct",
                "max_dd_pct",
                        "max_dd",
                "dd",
            ],
            0.0,
        )

        win = metric(
            result,
            [
                "win_rate_pct",
                        "win_rate",
                "win",
            ],
            0.0,
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
            f"[{n:02d}/{total}] "
            f"{mode:18s} "
            f"B={breadth:.2f} "
            f"S={stop_mult:.2f} "
            f"T={target_mult:.2f} "
            f"| Trades={trades:3d} "
            f"| Return={ret:8.2f}% "
            f"| PF={pf:5.2f} "
            f"| DD={dd:8.2f}% "
            f"| Win={win:6.2f}%"
        )

    print()
    print("=" * 110)
    print("TOP 20 — RETURN")
    print("=" * 110)

    for i, r in enumerate(
        sorted(
            results,
            key=lambda x: (
                x["return"],
                x["pf"],
            ),
            reverse=True,
        )[:20],
        1,
    ):
        print(
            f"{i:2d}. "
            f"{r['mode']:18s} "
            f"B={r['breadth']:.2f} "
            f"S={r['stop']:.2f} "
            f"T={r['target']:.2f} "
            f"| Trades={r['trades']:3d} "
            f"| Return={r['return']:.2f}% "
            f"| PF={r['pf']:.2f} "
            f"| DD={r['dd']:.2f}% "
            f"| Win={r['win']:.2f}%"
        )

    print()
    print("=" * 110)
    print("TOP 20 — PROFIT FACTOR")
    print("=" * 110)

    for i, r in enumerate(
        sorted(
            results,
            key=lambda x: (
                x["pf"],
                x["return"],
            ),
            reverse=True,
        )[:20],
        1,
    ):
        print(
            f"{i:2d}. "
            f"{r['mode']:18s} "
            f"B={r['breadth']:.2f} "
            f"S={r['stop']:.2f} "
            f"T={r['target']:.2f} "
            f"| Trades={r['trades']:3d} "
            f"| Return={r['return']:.2f}% "
            f"| PF={r['pf']:.2f} "
            f"| DD={r['dd']:.2f}% "
            f"| Win={r['win']:.2f}%"
        )

    print()
    print("=" * 110)
    print("TOP 20 — LOWEST DRAWDOWN")
    print("=" * 110)

    for i, r in enumerate(
        sorted(
            results,
            key=lambda x: (
                x["dd"],
                -x["return"],
            ),
            reverse=True,
        )[:20],
        1,
    ):
        print(
            f"{i:2d}. "
            f"{r['mode']:18s} "
            f"B={r['breadth']:.2f} "
            f"S={r['stop']:.2f} "
            f"T={r['target']:.2f} "
            f"| Trades={r['trades']:3d} "
            f"| Return={r['return']:.2f}% "
            f"| PF={r['pf']:.2f} "
            f"| DD={r['dd']:.2f}% "
            f"| Win={r['win']:.2f}%"
        )

    print()
    print("=" * 110)
    print("REGION AVERAGES BY REGIME + BREADTH")
    print("=" * 110)

    groups = {}

    for r in results:

        key = (
            r["mode"],
            r["breadth"],
        )

        groups.setdefault(key, []).append(r)

    for (mode, breadth), rows in sorted(groups.items()):

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

        min_return = min(
            x["return"] for x in rows
        )

        max_return = max(
            x["return"] for x in rows
        )

        print(
            f"{mode:18s} "
            f"B={breadth:.2f} "
            f"| AvgReturn={avg_return:8.2f}% "
            f"| Min={min_return:8.2f}% "
            f"| Max={max_return:8.2f}% "
            f"| AvgPF={avg_pf:5.2f} "
            f"| AvgDD={avg_dd:8.2f}% "
            f"| AvgTrades={avg_trades:5.1f}"
        )

    print()
    print("=" * 110)
    print("ATR REGION AVERAGES")
    print("=" * 110)

    atr_groups = {}

    for r in results:

        key = (
            r["stop"],
            r["target"],
        )

        atr_groups.setdefault(key, []).append(r)

    for (stop, target), rows in sorted(atr_groups.items()):

        avg_return = statistics.mean(
            x["return"] for x in rows
        )

        avg_pf = statistics.mean(
            x["pf"] for x in rows
        )

        avg_dd = statistics.mean(
            x["dd"] for x in rows
        )

        print(
            f"S={stop:.2f} "
            f"T={target:.2f} "
            f"| AvgReturn={avg_return:8.2f}% "
            f"| AvgPF={avg_pf:5.2f} "
            f"| AvgDD={avg_dd:8.2f}%"
        )

    print()
    print("=" * 110)
    print("ROBUSTNESS TEST FINISHED")
    print("=" * 110)


if __name__ == "__main__":
    main()
