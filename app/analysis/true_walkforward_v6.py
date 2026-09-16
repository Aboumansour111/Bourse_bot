import sqlite3
from statistics import mean
import regime_atr_v5b as regime
import backtest_final_v5b as base


# ---------------------------------------------------------
# TRUE WALK-FORWARD
#
# Each fold:
#   1) Optimize configuration on TRAIN
#   2) Freeze configuration
#   3) Test it on completely unseen OOS period
# ---------------------------------------------------------

ATR_CONFIGS = [
    (1.00, 3.00),
    (1.00, 3.50),
    (1.00, 3.75),
    (1.20, 3.50),
    (1.20, 3.75),
    (1.50, 3.00),
    (1.70, 3.00),
    (1.80, 3.00),
    (1.90, 3.00),
]

BREADTH_LEVELS = [
    0.42,
    0.43,
    0.44,
    0.45,
    0.46,
    0.47,
    0.48,
    0.50,
]

MODES = [
    "BREADTH",
    "BREADTH_MOMENTUM",
    "BREADTH_AND_CHANGE",
    "FULL",
]

# Expanding train / unseen OOS
FOLDS = [
    ("WF1", 20250101, 20250630, 20250701, 20250930),
    ("WF2", 20250101, 20250930, 20251001, 20251231),
    ("WF3", 20250101, 20251231, 20260101, 20260331),
    ("WF4", 20250101, 20260331, 20260401, 20260915),
]


def run_period(candidates, data, start, end):
    selected = [
        x for x in candidates
        if start <= x["entry_date"] <= end
        and start <= x["exit_date"] <= end
    ]

    completed, _, final_equity, max_dd = (
        base.simulate_portfolio(
            selected,
            data,
        )
    )

    trades = len(completed)

    if trades == 0:
        return {
            "trades": 0,
            "return": 0.0,
            "win": 0.0,
            "pf": 0.0,
            "dd": 0.0,
        }

    returns = [
        x["return_pct"]
        for x in completed
    ]

    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x <= 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    return {
        "trades": trades,
        "return": (
            final_equity / base.INITIAL_CAPITAL - 1
        ) * 100,
        "win": len(wins) / trades * 100,
        "pf": pf,
        "dd": max_dd,
    }


def selection_score(stats):
    """
    Training-only selection score.

    Return is important, but PF and drawdown also matter.
    This prevents selecting a configuration merely because
    it produced one unusually large gain.
    """
    if stats["trades"] < 5:
        return -999999

    if stats["pf"] < 1.30:
        return -999999

    if stats["dd"] < -15.0:
        return -999999

    return (
        stats["return"]
        + stats["pf"] * 4.0
        + stats["dd"] * 0.5
    )


def main():
    print("Loading data...")
    data = regime.load_data()
    print(f"Valid symbols: {len(data)}")

    print("Building market context...")
    context = regime.build_market_context(data)
    print(f"Market dates: {len(context)}")

    print("Building technical pool...")
    pool = regime.build_pool(data)
    print(f"Technical pool: {len(pool)}")

    print("Building ATR candidate pools...")

    all_candidates = {}

    for atr in ATR_CONFIGS:
        all_candidates[atr] = regime.build_candidates(
            pool,
            atr[0],
            atr[1],
        )

    print()
    print("=" * 150)
    print("TRUE EXPANDING WALK-FORWARD")
    print("=" * 150)

    oos_results = []

    for fold_name, train_start, train_end, oos_start, oos_end in FOLDS:

        print()
        print("=" * 150)
        print(
            f"{fold_name} | "
            f"TRAIN {train_start}-{train_end} | "
            f"OOS {oos_start}-{oos_end}"
        )
        print("=" * 150)

        train_rows = []

        # -------------------------------------------------
        # TRAIN: every configuration competes here
        # -------------------------------------------------

        for mode in MODES:
            for threshold in BREADTH_LEVELS:

                for atr, candidates in all_candidates.items():

                    filtered = regime.apply_regime_filter(
                        candidates,
                        context,
                        mode,
                        threshold,
                    )

                    stats = run_period(
                        filtered,
                        data,
                        train_start,
                        train_end,
                    )

                    score = selection_score(stats)

                    train_rows.append({
                        "mode": mode,
                        "threshold": threshold,
                        "stop": atr[0],
                        "target": atr[1],
                        "stats": stats,
                        "score": score,
                    })

        train_rows.sort(
            key=lambda x: x["score"],
            reverse=True,
        )

        best = train_rows[0]

        print()
        print("TRAIN WINNER")
        print(
            f"MODE={best['mode']} "
            f"TH={best['threshold']:.2f} "
            f"ATR={best['stop']:.2f}/{best['target']:.2f}"
        )

        s = best["stats"]

        print(
            f"TRAIN | "
            f"TR={s['trades']} "
            f"RET={s['return']:.2f}% "
            f"WIN={s['win']:.2f}% "
            f"PF={s['pf']:.2f} "
            f"DD={s['dd']:.2f}% "
            f"SCORE={best['score']:.2f}"
        )

        # Show next best train candidates
        print()
        print("TOP 10 TRAIN CONFIGS")

        for i, row in enumerate(train_rows[:10], 1):
            s = row["stats"]

            print(
                f"{i:2d}. "
                f"{row['mode']:18s} "
                f"TH={row['threshold']:.2f} "
                f"ATR={row['stop']:.2f}/{row['target']:.2f} "
                f"RET={s['return']:7.2f}% "
                f"PF={s['pf']:5.2f} "
                f"DD={s['dd']:7.2f}% "
                f"TR={s['trades']:3d} "
                f"SCORE={row['score']:7.2f}"
            )

        # -------------------------------------------------
        # OOS: selected configuration is now frozen
        # -------------------------------------------------

        selected_atr = (
            best["stop"],
            best["target"],
        )

        selected_candidates = regime.apply_regime_filter(
            all_candidates[selected_atr],
            context,
            best["mode"],
            best["threshold"],
        )

        oos = run_period(
            selected_candidates,
            data,
            oos_start,
            oos_end,
        )

        print()
        print("FROZEN OOS RESULT")

        print(
            f"OOS | "
            f"TR={oos['trades']} "
            f"RET={oos['return']:.2f}% "
            f"WIN={oos['win']:.2f}% "
            f"PF={oos['pf']:.2f} "
            f"DD={oos['dd']:.2f}%"
        )

        oos_results.append({
            "fold": fold_name,
            "mode": best["mode"],
            "threshold": best["threshold"],
            "stop": best["stop"],
            "target": best["target"],
            **oos,
        })

    # -----------------------------------------------------
    # FINAL WALK-FORWARD SUMMARY
    # -----------------------------------------------------

    print()
    print("=" * 150)
    print("FINAL WALK-FORWARD OOS SUMMARY")
    print("=" * 150)

    total_trades = sum(
        x["trades"]
        for x in oos_results
    )

    avg_return = mean(
        x["return"]
        for x in oos_results
    )

    avg_pf = mean(
        x["pf"]
        for x in oos_results
        if x["trades"] > 0
    )

    worst_dd = min(
        x["dd"]
        for x in oos_results
    )

    positive_folds = sum(
        x["return"] > 0
        for x in oos_results
    )

    print(
        f"AVG OOS RETURN : {avg_return:.2f}%"
    )

    print(
        f"AVG OOS PF     : {avg_pf:.2f}"
    )

    print(
        f"POSITIVE FOLDS : {positive_folds}/{len(oos_results)}"
    )

    print(
        f"WORST OOS DD   : {worst_dd:.2f}%"
    )

    print(
        f"TOTAL OOS TRADES: {total_trades}"
    )

    print()
    print(
        "FOLD | SELECTED CONFIG | OOS RETURN | OOS PF | "
        "OOS DD | TRADES"
    )

    for x in oos_results:
        print(
            f"{x['fold']:4s} | "
            f"{x['mode']:18s} "
            f"{x['threshold']:.2f} "
            f"{x['stop']:.2f}/{x['target']:.2f} | "
            f"{x['return']:9.2f}% | "
            f"{x['pf']:6.2f} | "
            f"{x['dd']:7.2f}% | "
            f"{x['trades']:6d}"
        )


if __name__ == "__main__":
    main()
