import regime_atr_v5b as regime
import backtest_final_v5b as base
from statistics import mean


# =========================================================
# TRUE EXPANDING WALK-FORWARD v7
# =========================================================
#
# For every fold:
#
#   TRAIN
#      ↓
#   select configuration
#      ↓
#   FREEZE configuration
#      ↓
#   unseen OOS
#
# No OOS data is used for parameter selection.
#
# v7 fixes:
#   - no fake winner when training data is insufficient
#   - minimum 10 training trades
#   - reports insufficient folds explicitly
#   - stability / neighbor analysis
# =========================================================


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


# Expanding training windows
# followed by completely unseen OOS windows.

FOLDS = [
    ("WF1", 20250101, 20250630, 20250701, 20250930),
    ("WF2", 20250101, 20250930, 20251001, 20251231),
    ("WF3", 20250101, 20251231, 20260101, 20260331),
    ("WF4", 20250101, 20260331, 20260401, 20260915),
]


MIN_TRAIN_TRADES = 10


# =========================================================
# RUN PERIOD
# =========================================================

def run_period(candidates, data, start, end):

    selected = [
        x
        for x in candidates
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

    wins = [
        x
        for x in returns
        if x > 0
    ]

    losses = [
        x
        for x in returns
        if x <= 0
    ]

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
            final_equity
            / base.INITIAL_CAPITAL
            - 1
        ) * 100,

        "win": (
            len(wins)
            / trades
            * 100
        ),

        "pf": pf,

        "dd": max_dd,
    }


# =========================================================
# TRAINING SCORE
# =========================================================

def selection_score(stats):

    # Not enough observations.
    if stats["trades"] < MIN_TRAIN_TRADES:
        return None

    # Reject clearly poor systems.
    if stats["pf"] < 1.30:
        return None

    # Reject excessive drawdown.
    if stats["dd"] < -15.0:
        return None

    #
    # Return:
    #   positive
    #
    # PF:
    #   rewarded
    #
    # DD:
    #   penalized
    #
    return (
        stats["return"]
        + stats["pf"] * 4.0
        + stats["dd"] * 0.5
    )


# =========================================================
# CONFIGURATION LABEL
# =========================================================

def config_name(row):

    return (
        f"{row['mode']} "
        f"TH={row['threshold']:.2f} "
        f"ATR={row['stop']:.2f}/{row['target']:.2f}"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print("Loading data...")

    data = regime.load_data()

    print(
        f"Valid symbols: {len(data)}"
    )


    print(
        "Building market context..."
    )

    context = regime.build_market_context(
        data
    )

    print(
        f"Market dates: {len(context)}"
    )


    print(
        "Building technical pool..."
    )

    pool = regime.build_pool(
        data
    )

    print(
        f"Technical pool: {len(pool)}"
    )


    print(
        "Building ATR candidate pools..."
    )

    all_candidates = {}

    for atr in ATR_CONFIGS:

        print(
            f"  ATR {atr[0]:.2f}/{atr[1]:.2f}"
        )

        all_candidates[atr] = (
            regime.build_candidates(
                pool,
                atr[0],
                atr[1],
            )
        )


    print()
    print("=" * 150)
    print(
        "TRUE EXPANDING WALK-FORWARD v7"
    )
    print("=" * 150)


    oos_results = []


    # =====================================================
    # FOLDS
    # =====================================================

    for (
        fold_name,
        train_start,
        train_end,
        oos_start,
        oos_end,
    ) in FOLDS:


        print()
        print("=" * 150)

        print(
            f"{fold_name} | "
            f"TRAIN {train_start}-{train_end} | "
            f"OOS {oos_start}-{oos_end}"
        )

        print("=" * 150)


        train_rows = []


        # =================================================
        # TRAIN
        # =================================================

        for mode in MODES:

            for threshold in BREADTH_LEVELS:

                for atr, candidates in (
                    all_candidates.items()
                ):

                    filtered = (
                        regime.apply_regime_filter(
                            candidates,
                            context,
                            mode,
                            threshold,
                        )
                    )


                    stats = run_period(
                        filtered,
                        data,
                        train_start,
                        train_end,
                    )


                    score = (
                        selection_score(
                            stats
                        )
                    )


                    if score is None:
                        continue


                    train_rows.append({
                        "mode": mode,
                        "threshold": threshold,
                        "stop": atr[0],
                        "target": atr[1],
                        "stats": stats,
                        "score": score,
                    })


        # =================================================
        # NO VALID TRAIN CONFIG
        # =================================================

        if not train_rows:

            print()
            print(
                "TRAIN STATUS: "
                "INSUFFICIENT_DATA"
            )

            print(
                f"No configuration had "
                f"at least {MIN_TRAIN_TRADES} "
                f"valid completed trades."
            )

            print(
                "OOS STATUS: NOT_TESTED"
            )

            oos_results.append({
                "fold": fold_name,
                "status": "INSUFFICIENT_DATA",
            })

            continue


        # =================================================
        # SORT TRAIN CONFIGS
        # =================================================

        train_rows.sort(
            key=lambda x: x["score"],
            reverse=True,
        )


        best = train_rows[0]


        print()
        print(
            "TRAIN STATUS: VALID"
        )


        print()
        print(
            "TRAIN WINNER"
        )


        print(
            f"MODE={best['mode']} "
            f"TH={best['threshold']:.2f} "
            f"ATR="
            f"{best['stop']:.2f}/"
            f"{best['target']:.2f}"
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


        # =================================================
        # TOP TRAIN
        # =================================================

        print()
        print(
            "TOP 10 TRAIN CONFIGS"
        )


        for i, row in enumerate(
            train_rows[:10],
            1,
        ):

            s = row["stats"]


            print(
                f"{i:2d}. "
                f"{row['mode']:18s} "
                f"TH={row['threshold']:.2f} "
                f"ATR="
                f"{row['stop']:.2f}/"
                f"{row['target']:.2f} "
                f"RET="
                f"{s['return']:7.2f}% "
                f"PF="
                f"{s['pf']:5.2f} "
                f"DD="
                f"{s['dd']:7.2f}% "
                f"TR="
                f"{s['trades']:3d} "
                f"SCORE="
                f"{row['score']:7.2f}"
            )


        # =================================================
        # FREEZE CONFIGURATION
        # =================================================

        selected_atr = (
            best["stop"],
            best["target"],
        )


        selected_candidates = (
            regime.apply_regime_filter(
                all_candidates[
                    selected_atr
                ],
                context,
                best["mode"],
                best["threshold"],
            )
        )


        # =================================================
        # OOS
        # =================================================

        oos = run_period(
            selected_candidates,
            data,
            oos_start,
            oos_end,
        )


        print()
        print(
            "FROZEN OOS RESULT"
        )


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
            "status": "VALID",
            "mode": best["mode"],
            "threshold": best["threshold"],
            "stop": best["stop"],
            "target": best["target"],
            **oos,
        })


        # =================================================
        # TRAIN NEIGHBOR STABILITY
        # =================================================

        print()
        print(
            "TRAIN NEIGHBOR STABILITY"
        )


        best_stop = best["stop"]
        best_target = best["target"]
        best_mode = best["mode"]
        best_threshold = best["threshold"]


        neighbors = []


        for row in train_rows:

            same_mode = (
                row["mode"]
                == best_mode
            )

            close_threshold = (
                abs(
                    row["threshold"]
                    - best_threshold
                ) <= 0.01
            )

            close_stop = (
                abs(
                    row["stop"]
                    - best_stop
                ) <= 0.20
            )

            close_target = (
                abs(
                    row["target"]
                    - best_target
                ) <= 0.50
            )


            if (
                same_mode
                and close_threshold
                and close_stop
                and close_target
            ):

                neighbors.append(row)


        for row in neighbors[:10]:

            s = row["stats"]


            print(
                f"{row['mode']:18s} "
                f"TH={row['threshold']:.2f} "
                f"ATR="
                f"{row['stop']:.2f}/"
                f"{row['target']:.2f} "
                f"RET="
                f"{s['return']:7.2f}% "
                f"PF="
                f"{s['pf']:5.2f} "
                f"DD="
                f"{s['dd']:7.2f}% "
                f"TR="
                f"{s['trades']:3d}"
            )


    # =====================================================
    # FINAL SUMMARY
    # =====================================================

    print()
    print("=" * 150)
    print(
        "FINAL TRUE WALK-FORWARD SUMMARY"
    )
    print("=" * 150)


    valid_oos = [
        x
        for x in oos_results
        if x["status"] == "VALID"
    ]


    insufficient = [
        x
        for x in oos_results
        if x["status"]
        == "INSUFFICIENT_DATA"
    ]


    print()
    print(
        f"VALID FOLDS        : "
        f"{len(valid_oos)}/{len(FOLDS)}"
    )


    print(
        f"INSUFFICIENT FOLDS : "
        f"{len(insufficient)}"
    )


    if not valid_oos:

        print()
        print(
            "No valid OOS folds."
        )

        return


    positive = sum(
        x["return"] > 0
        for x in valid_oos
        if x["trades"] > 0
    )


    avg_return = mean(
        x["return"]
        for x in valid_oos
    )


    avg_pf_values = [
        x["pf"]
        for x in valid_oos
        if x["trades"] > 0
    ]


    avg_pf = (
        mean(avg_pf_values)
        if avg_pf_values
        else 0.0
    )


    worst_dd = min(
        x["dd"]
        for x in valid_oos
    )


    total_trades = sum(
        x["trades"]
        for x in valid_oos
    )


    print()
    print(
        f"AVG OOS RETURN : "
        f"{avg_return:.2f}%"
    )


    print(
        f"AVG OOS PF     : "
        f"{avg_pf:.2f}"
    )


    print(
        f"POSITIVE FOLDS : "
        f"{positive}/{len(valid_oos)}"
    )


    print(
        f"WORST OOS DD   : "
        f"{worst_dd:.2f}%"
    )


    print(
        f"TOTAL OOS TRADES: "
        f"{total_trades}"
    )


    # =====================================================
    # CONFIGURATION CONSISTENCY
    # =====================================================

    print()
    print("=" * 150)
    print(
        "SELECTED CONFIGURATION CONSISTENCY"
    )
    print("=" * 150)


    for x in valid_oos:

        print(
            f"{x['fold']:4s} | "
            f"{x['mode']:18s} | "
            f"TH={x['threshold']:.2f} | "
            f"ATR="
            f"{x['stop']:.2f}/"
            f"{x['target']:.2f} | "
            f"OOS="
            f"{x['return']:7.2f}% | "
            f"PF="
            f"{x['pf']:5.2f} | "
            f"DD="
            f"{x['dd']:7.2f}% | "
            f"TR="
            f"{x['trades']:3d}"
        )


    # =====================================================
    # CONFIGURATION FREQUENCY
    # =====================================================

    print()
    print("=" * 150)
    print(
        "CONFIGURATION FREQUENCY"
    )
    print("=" * 150)


    frequencies = {}


    for x in valid_oos:

        key = (
            x["mode"],
            x["threshold"],
            x["stop"],
            x["target"],
        )

        frequencies[key] = (
            frequencies.get(key, 0)
            + 1
        )


    sorted_frequency = sorted(
        frequencies.items(),
        key=lambda x: x[1],
        reverse=True,
    )


    for key, count in sorted_frequency:

        mode, threshold, stop, target = key


        print(
            f"{count}x | "
            f"{mode:18s} "
            f"TH={threshold:.2f} "
            f"ATR="
            f"{stop:.2f}/"
            f"{target:.2f}"
        )


    print()
    print("=" * 150)
    print(
        "END"
    )
    print("=" * 150)


if __name__ == "__main__":
    main()
