import sqlite3
from collections import defaultdict

import backtest_final_v5b as v5b


DB_PATH = v5b.DB_PATH

TRAIN_START = 20250101
TRAIN_END = 20260331

OOS_START = 20260401
OOS_END = 20260915

BREADTH_VALUES = [
    0.40,
    0.41,
    0.42,
    0.43,
    0.44,
    0.45,
    0.46,
    0.47,
    0.48,
]


def generate_candidates_range(
    data,
    breadth,
    start_date,
    end_date,
    breadth_threshold,
):
    candidates = []

    for symbol_index, (inscode, item) in enumerate(
        data.items(), 1
    ):

        dates = item["dates"]
        closes = item["closes"]
        highs = item["highs"]
        lows = item["lows"]
        volumes = item["volumes"]

        for i in range(
            v5b.MIN_HISTORY,
            len(dates) - 1,
        ):

            signal = v5b.technical_signal(
                closes[:i + 1],
                highs[:i + 1],
                lows[:i + 1],
                volumes[:i + 1],
            )

            if signal is None or not signal["eligible"]:
                continue

            signal_date = dates[i]

            market = breadth.get(signal_date)

            if market is None:
                continue

            if market["breadth"] < breadth_threshold:
                continue

            entry_index = i + 1

            if entry_index >= len(dates):
                continue

            entry_date = dates[entry_index]

            if entry_date < start_date or entry_date > end_date:
                continue

            entry = closes[entry_index]

            atr14 = signal["atr"]

            if atr14 is None or atr14 <= 0:
                continue

            stop = entry - (1.5 * atr14)
            target = entry + (3.0 * atr14)

            if stop <= 0 or target <= entry:
                continue

            last_index = min(
                entry_index + v5b.MAX_HOLD_DAYS,
                len(dates) - 1,
            )

            exit_price = closes[last_index]
            exit_date = dates[last_index]
            exit_reason = "TIME"

            for j in range(
                entry_index + 1,
                last_index + 1,
            ):

                day_low = lows[j]
                day_high = highs[j]

                hit_stop = day_low <= stop
                hit_target = day_high >= target

                if hit_stop and hit_target:
                    exit_price = stop
                    exit_date = dates[j]
                    exit_reason = "STOP_AND_TARGET_SAME_DAY"
                    break

                if hit_stop:
                    exit_price = stop
                    exit_date = dates[j]
                    exit_reason = "STOP"
                    break

                if hit_target:
                    exit_price = target
                    exit_date = dates[j]
                    exit_reason = "TARGET"
                    break

            gross_return = (
                (exit_price - entry) / entry
            )

            net_return = (
                gross_return
                - v5b.ROUND_TRIP_COST
            )

            candidates.append({
                "symbol": item["symbol"],
                "inscode": inscode,
                "signal_date": signal_date,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "entry": entry,
                "exit": exit_price,
                "stop": stop,
                "target": target,
                "return": net_return * 100,
                "quality": signal["quality"],
                "reason": exit_reason,
                "breadth": market["breadth"],
            })

    return candidates


def simulate_portfolio(
    candidates,
    data,
    start_date,
    end_date,
):
    candidates_by_date = defaultdict(list)

    for trade in candidates:
        candidates_by_date[
            trade["entry_date"]
        ].append(trade)

    for date in candidates_by_date:
        candidates_by_date[date].sort(
            key=lambda x: (
                -x["quality"],
                -x["breadth"],
            )
        )

    all_dates = sorted({
        date
        for item in data.values()
        for date in item["dates"]
        if start_date <= date <= end_date
    })

    price_map = v5b.build_price_map(data)

    cash = v5b.INITIAL_CAPITAL
    positions = []
    completed = []

    peak_equity = v5b.INITIAL_CAPITAL
    max_drawdown = 0.0

    for date in all_dates:

        remaining = []

        for pos in positions:

            if pos["exit_date"] == date:

                exit_value = (
                    pos["exit"]
                    * pos["quantity"]
                )

                exit_fee = (
                    exit_value
                    * v5b.EXIT_FEE
                )

                cash += exit_value - exit_fee

                entry_value = (
                    pos["entry"]
                    * pos["quantity"]
                )

                pnl = (
                    exit_value
                    - entry_value
                    - pos["entry_fee"]
                    - exit_fee
                )

                pos["pnl"] = pnl

                pos["return_pct"] = (
                    pnl
                    / (entry_value + pos["entry_fee"])
                    * 100
                )

                completed.append(pos)

            else:
                remaining.append(pos)

        positions = remaining

        for candidate in candidates_by_date.get(
            date,
            [],
        ):

            if len(positions) >= v5b.MAX_CONCURRENT_POSITIONS:
                break

            if any(
                p["inscode"] == candidate["inscode"]
                for p in positions
            ):
                continue

            equity_before = cash

            for p in positions:

                current_price = price_map.get(
                    (p["inscode"], date),
                    p["entry"],
                )

                equity_before += (
                    current_price
                    * p["quantity"]
                )

            risk_budget = (
                equity_before
                * v5b.RISK_PER_TRADE
            )

            risk_per_share = (
                candidate["entry"]
                - candidate["stop"]
            )

            if risk_per_share <= 0:
                continue

            quantity_by_risk = (
                risk_budget
                / risk_per_share
            )

            max_value = (
                equity_before
                * v5b.MAX_POSITION_WEIGHT
            )

            quantity_by_weight = (
                max_value
                / candidate["entry"]
            )

            available_for_entry = (
                cash
                / (
                    candidate["entry"]
                    * (1 + v5b.ENTRY_FEE)
                )
            )

            quantity = int(
                min(
                    quantity_by_risk,
                    quantity_by_weight,
                    available_for_entry,
                )
            )

            if quantity <= 0:
                continue

            entry_value = (
                candidate["entry"]
                * quantity
            )

            entry_fee = (
                entry_value
                * v5b.ENTRY_FEE
            )

            total_cost = (
                entry_value
                + entry_fee
            )

            if total_cost > cash:
                continue

            cash -= total_cost

            positions.append({
                **candidate,
                "quantity": quantity,
                "entry_value": entry_value,
                "entry_fee": entry_fee,
                "pnl": None,
                "return_pct": None,
            })

        equity = cash

        for pos in positions:

            current_price = price_map.get(
                (pos["inscode"], date),
                pos["entry"],
            )

            equity += (
                current_price
                * pos["quantity"]
            )

        peak_equity = max(
            peak_equity,
            equity,
        )

        drawdown = (
            (equity - peak_equity)
            / peak_equity
            * 100
        )

        max_drawdown = min(
            max_drawdown,
            drawdown,
        )

    for pos in positions:

        # آخرین قیمت موجود تا پایان همین دوره
        dates_for_symbol = data[pos["inscode"]]["dates"]

        valid_dates = [
            d
            for d in dates_for_symbol
            if start_date <= d <= end_date
        ]

        if valid_dates:
            final_date = valid_dates[-1]
            last_price = price_map.get(
                (pos["inscode"], final_date),
                pos["entry"],
            )
        else:
            last_price = pos["entry"]

        exit_value = (
            last_price
            * pos["quantity"]
        )

        exit_fee = (
            exit_value
            * v5b.EXIT_FEE
        )

        entry_value = (
            pos["entry"]
            * pos["quantity"]
        )

        pnl = (
            exit_value
            - entry_value
            - pos["entry_fee"]
            - exit_fee
        )

        pos["pnl"] = pnl

        pos["return_pct"] = (
            pnl
            / (entry_value + pos["entry_fee"])
            * 100
        )

        cash += exit_value - exit_fee

        completed.append(pos)

    return completed, cash, max_drawdown


def metrics(candidates, trades, final_equity, max_drawdown):

    if not trades:
        return {
            "candidates": len(candidates),
            "trades": 0,
            "return": 0,
            "win_rate": 0,
            "avg_return": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "pf": 0,
            "expectancy": 0,
            "dd": max_drawdown,
        }

    winners = [
        x for x in trades
        if x["pnl"] > 0
    ]

    losers = [
        x for x in trades
        if x["pnl"] <= 0
    ]

    returns = [
        x["return_pct"]
        for x in trades
    ]

    win_rate = (
        len(winners)
        / len(trades)
        * 100
    )

    avg_return = sum(returns) / len(returns)

    avg_win = (
        sum(x["return_pct"] for x in winners)
        / len(winners)
        if winners else 0
    )

    avg_loss = (
        sum(x["return_pct"] for x in losers)
        / len(losers)
        if losers else 0
    )

    gross_profit = sum(
        x["pnl"]
        for x in winners
    )

    gross_loss = abs(sum(
        x["pnl"]
        for x in losers
    ))

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    expectancy = (
        (win_rate / 100 * avg_win)
        + ((1 - win_rate / 100) * avg_loss)
    )

    total_return = (
        final_equity
        / v5b.INITIAL_CAPITAL
        - 1
    ) * 100

    return {
        "candidates": len(candidates),
        "trades": len(trades),
        "return": total_return,
        "win_rate": win_rate,
        "avg_return": avg_return,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "pf": pf,
        "expectancy": expectancy,
        "dd": max_drawdown,
    }


def run_period(
    data,
    breadth,
    start_date,
    end_date,
    threshold,
):

    candidates = generate_candidates_range(
        data,
        breadth,
        start_date,
        end_date,
        threshold,
    )

    trades, final_equity, dd = simulate_portfolio(
        candidates,
        data,
        start_date,
        end_date,
    )

    return metrics(
        candidates,
        trades,
        final_equity,
        dd,
    )


def main():

    conn = sqlite3.connect(DB_PATH)

    print("Loading data...")

    data = v5b.load_data(conn)

    conn.close()

    print("Valid symbols:", len(data))

    breadth = v5b.build_breadth(data)

    print("Breadth dates:", len(breadth))

    print()
    print("=" * 105)
    print(
        f"{'Threshold':>10} "
        f"{'Period':>8} "
        f"{'Cand':>6} "
        f"{'Trades':>7} "
        f"{'Return':>9} "
        f"{'Win%':>8} "
        f"{'PF':>7} "
        f"{'Expect':>9} "
        f"{'DD':>9}"
    )
    print("=" * 105)

    for threshold in BREADTH_VALUES:

        for name, start_date, end_date in [
            ("TRAIN", TRAIN_START, TRAIN_END),
            ("OOS", OOS_START, OOS_END),
        ]:

            result = run_period(
                data,
                breadth,
                start_date,
                end_date,
                threshold,
            )

            print(
                f"{threshold:>10.2f} "
                f"{name:>8} "
                f"{result['candidates']:>6} "
                f"{result['trades']:>7} "
                f"{result['return']:>8.2f}% "
                f"{result['win_rate']:>7.2f}% "
                f"{result['pf']:>7.2f} "
                f"{result['expectancy']:>8.2f}% "
                f"{result['dd']:>8.2f}%"
            )

    print("=" * 105)


if __name__ == "__main__":
    main()
