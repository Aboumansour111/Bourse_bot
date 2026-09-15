import sqlite3
from collections import defaultdict

import backtest_final_v5b as v5b


DB_PATH = v5b.DB_PATH

TRAIN_START = 20250101
TRAIN_END   = 20260331

OOS_START = 20260401
OOS_END   = 20260915


def generate_candidates_range(data, breadth, start_date, end_date):
    """
    Same v5b candidate logic, but only candidates whose ENTRY date
    falls inside the requested evaluation period are returned.
    """

    candidates = []

    for symbol_index, (inscode, item) in enumerate(data.items(), 1):

        dates = item["dates"]
        closes = item["closes"]
        highs = item["highs"]
        lows = item["lows"]
        volumes = item["volumes"]

        if not dates:
            continue

        for i in range(len(dates) - 1):

            signal_date = dates[i]
            entry_index = i + 1

            if entry_index >= len(dates):
                continue

            entry_date = dates[entry_index]

            if entry_date < start_date or entry_date > end_date:
                continue

            signal = v5b.technical_signal(
                closes[:i + 1],
                highs[:i + 1],
                lows[:i + 1],
                volumes[:i + 1],
            )

            if not signal or not signal["eligible"]:
                continue

            market = breadth.get(signal_date)

            if market is None:
                continue

            if market["breadth"] < 0.42:
                continue

            entry = closes[entry_index]

            atr_value = signal["atr"]

            if atr_value is None or atr_value <= 0:
                continue

            stop = entry - (1.5 * atr_value)
            target = entry + (3.0 * atr_value)

            exit_price = None
            exit_date = None
            exit_reason = None

            last_index = min(
                entry_index + v5b.MAX_HOLD_DAYS,
                len(dates) - 1,
            )

            for j in range(entry_index + 1, last_index + 1):

                day_high = highs[j]
                day_low = lows[j]

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

            if exit_price is None:
                exit_index = last_index

                if exit_index <= entry_index:
                    continue

                exit_price = closes[exit_index]
                exit_date = dates[exit_index]
                exit_reason = "TIME"

            gross_return = (
                (exit_price - entry) / entry
            )

            net_return = (
                gross_return - v5b.ROUND_TRIP_COST
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

        if symbol_index % 100 == 0:
            print(
                f"Candidates [{symbol_index}/{len(data)}]"
                f" = {len(candidates)}"
            )

    return candidates


def simulate_range(candidates, data, start_date, end_date):
    """
    Same v5b portfolio simulation, restricted to the requested period.
    """

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

        candidates_today = candidates_by_date.get(
            date,
            []
        )

        for candidate in candidates_today:

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

    # Close remaining positions at the end of the period.
    for pos in positions:

        last_price = price_map.get(
            (pos["inscode"], end_date),
            pos["entry"],
        )

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


def print_summary(name, candidates, trades, final_equity, max_drawdown):

    print()
    print("=" * 60)
    print(name)
    print("=" * 60)

    if not trades:
        print("No accepted trades.")
        return

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

    avg_return = (
        sum(returns)
        / len(returns)
    )

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

    profit_factor = (
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

    reasons = defaultdict(int)

    for trade in trades:
        reasons[trade["reason"]] += 1

    print(f"Candidates:       {len(candidates)}")
    print(f"Accepted trades:  {len(trades)}")
    print(f"Final equity:     {final_equity:,.0f}")
    print(f"Return:           {total_return:.2f}%")
    print(f"Win rate:         {win_rate:.2f}%")
    print(f"Avg return:       {avg_return:.2f}%")
    print(f"Avg win:          {avg_win:.2f}%")
    print(f"Avg loss:         {avg_loss:.2f}%")
    print(f"Profit factor:    {profit_factor:.2f}")
    print(f"Expectancy:       {expectancy:.2f}%")
    print(f"Max drawdown:     {max_drawdown:.2f}%")

    print("Exit reasons:", dict(reasons))


def run_period(data, breadth, name, start_date, end_date):

    print()
    print(f"Generating {name} candidates...")

    candidates = generate_candidates_range(
        data,
        breadth,
        start_date,
        end_date,
    )

    print(
        f"{name} candidate trades:",
        len(candidates),
    )

    print(
        f"Simulating {name} portfolio..."
    )

    trades, final_equity, max_drawdown = simulate_range(
        candidates,
        data,
        start_date,
        end_date,
    )

    print_summary(
        name,
        candidates,
        trades,
        final_equity,
        max_drawdown,
    )

    return candidates, trades


def main():

    conn = sqlite3.connect(DB_PATH)

    print("Loading valid trading-day data...")

    data = v5b.load_data(conn)

    conn.close()

    print("Valid symbols:", len(data))

    if not data:
        return

    print("Building historical market breadth...")

    breadth = v5b.build_breadth(data)

    print("Breadth dates:", len(breadth))

    run_period(
        data,
        breadth,
        "TRAIN 2025-01-01 -> 2026-03-31",
        TRAIN_START,
        TRAIN_END,
    )

    run_period(
        data,
        breadth,
        "OOS 2026-04-01 -> 2026-09-15",
        OOS_START,
        OOS_END,
    )


if __name__ == "__main__":
    main()
