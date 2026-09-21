import sqlite3
import csv
from pathlib import Path
from collections import defaultdict

import app.analysis.backtest_final_v5b_2026 as v5b


DB_PATH = "/opt/bourse-bot/data/bourse.db"
OUT = Path("/opt/bourse-bot/data/v5b_optimization.csv")

# Grid
BREADTH_VALUES = [0.38, 0.42, 0.46, 0.50]
STOP_ATR_VALUES = [1.25, 1.50, 1.75, 2.00]
TARGET_ATR_VALUES = [2.50, 3.00, 3.50, 4.00]
HOLD_VALUES = [7, 10, 12]

# Keep portfolio risk management fixed during strategy optimization.
RISK_PER_TRADE = 0.01
MAX_POSITION_WEIGHT = 0.20
MAX_CONCURRENT_POSITIONS = 5


def generate_candidates_param(
    data,
    breadth,
    stop_atr,
    target_atr,
    max_hold_days,
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
            len(dates) - 1
        ):
            signal = v5b.technical_signal(
                closes[:i + 1],
                highs[:i + 1],
                lows[:i + 1],
                volumes[:i + 1],
                item["gap_before"][:i + 1],
            )

            if signal is None or not signal["eligible"]:
                continue

            signal_date = dates[i]
            market = breadth_data.get(signal_date)

            if market is None:
                continue

            if market["breadth"] < breadth:
                continue

            entry_index = i + 1

            if entry_index >= len(dates):
                continue

            entry_date = dates[entry_index]

            if entry_date < 20260101 or entry_date > 20261231:
                continue

            entry = closes[entry_index]
            atr14 = signal["atr"]

            stop = entry - (stop_atr * atr14)
            target = entry + (target_atr * atr14)

            if stop <= 0 or target <= entry:
                continue

            last_index = min(
                entry_index + max_hold_days,
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

            gross_return = (exit_price - entry) / entry
            net_return = gross_return - v5b.ROUND_TRIP_COST

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


def simulate(candidates, data):
    candidates_by_date = defaultdict(list)

    for trade in candidates:
        candidates_by_date[
            trade["entry_date"]
        ].append(trade)

    for date in candidates_by_date:
        candidates_by_date[date].sort(
            key=lambda x: (-x["quality"], -x["breadth"])
        )

    all_dates = sorted({
        date
        for item in data.values()
        for date in item["dates"]
        if 20260101 <= date <= 20261231
    })

    price_map = v5b.build_price_map(data)

    cash = v5b.INITIAL_CAPITAL
    positions = []
    completed = []

    peak_equity = cash
    max_drawdown = 0.0

    for date in all_dates:

        remaining = []

        for pos in positions:
            if pos["exit_date"] == date:
                exit_value = pos["exit"] * pos["quantity"]
                exit_fee = exit_value * v5b.EXIT_FEE

                cash += exit_value - exit_fee

                entry_value = pos["entry"] * pos["quantity"]

                pnl = (
                    exit_value
                    - entry_value
                    - pos["entry_fee"]
                    - exit_fee
                )

                pos["pnl"] = pnl
                pos["return_pct"] = (
                    pnl / (entry_value + pos["entry_fee"]) * 100
                )

                completed.append(pos)
            else:
                remaining.append(pos)

        positions = remaining

        for candidate in candidates_by_date.get(date, []):

            if len(positions) >= MAX_CONCURRENT_POSITIONS:
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
                equity_before += current_price * p["quantity"]

            risk_budget = equity_before * RISK_PER_TRADE

            risk_per_share = (
                candidate["entry"] - candidate["stop"]
            )

            if risk_per_share <= 0:
                continue

            quantity_by_risk = (
                risk_budget / risk_per_share
            )

            max_value = (
                equity_before * MAX_POSITION_WEIGHT
            )

            quantity_by_weight = (
                max_value / candidate["entry"]
            )

            available_for_entry = (
                cash /
                (candidate["entry"] * (1 + v5b.ENTRY_FEE))
            )

            quantity = int(min(
                quantity_by_risk,
                quantity_by_weight,
                available_for_entry,
            ))

            if quantity <= 0:
                continue

            entry_value = candidate["entry"] * quantity
            entry_fee = entry_value * v5b.ENTRY_FEE
            total_cost = entry_value + entry_fee

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
            equity += current_price * pos["quantity"]

        peak_equity = max(peak_equity, equity)

        drawdown = (
            (equity - peak_equity)
            / peak_equity
            * 100
        )

        max_drawdown = min(max_drawdown, drawdown)

    last_test_date = all_dates[-1] if all_dates else None

    for pos in positions:
        last_price = price_map.get(
            (pos["inscode"], last_test_date),
            pos["entry"],
        )

        exit_value = last_price * pos["quantity"]
        exit_fee = exit_value * v5b.EXIT_FEE
        entry_value = pos["entry"] * pos["quantity"]

        pnl = (
            exit_value
            - entry_value
            - pos["entry_fee"]
            - exit_fee
        )

        pos["pnl"] = pnl

        pos["return_pct"] = (
            pnl / (entry_value + pos["entry_fee"]) * 100
        )

        cash += exit_value - exit_fee
        completed.append(pos)

    final_equity = cash

    wins = [x for x in completed if x["pnl"] > 0]
    losses = [x for x in completed if x["pnl"] <= 0]

    gross_profit = sum(x["pnl"] for x in wins)
    gross_loss = abs(sum(x["pnl"] for x in losses))

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else 999.0
    )

    win_rate = (
        len(wins) / len(completed) * 100
        if completed else 0
    )

    total_return = (
        (final_equity / v5b.INITIAL_CAPITAL - 1) * 100
    )

    # Composite score:
    # reward return/PF, penalize DD, and lightly penalize tiny samples.
    trades = len(completed)

    score = (
        total_return
        + (pf * 4)
        + (win_rate * 0.05)
        + (max_drawdown * 0.50)
    )

    if trades < 40:
        score -= (40 - trades) * 0.20

    return {
        "return": total_return,
        "final_equity": final_equity,
        "trades": trades,
        "win_rate": win_rate,
        "pf": pf,
        "max_dd": max_drawdown,
        "score": score,
    }


print("Loading data...")

conn = sqlite3.connect(DB_PATH)

data = v5b.load_data(conn)
breadth_data = v5b.build_breadth(data)

conn.close()

print(f"Valid symbols: {len(data)}")
print(f"Testing {len(BREADTH_VALUES) * len(STOP_ATR_VALUES) * len(TARGET_ATR_VALUES) * len(HOLD_VALUES)} combinations...")

results = []

total = (
    len(BREADTH_VALUES)
    * len(STOP_ATR_VALUES)
    * len(TARGET_ATR_VALUES)
    * len(HOLD_VALUES)
)

counter = 0

for breadth in BREADTH_VALUES:
    for stop_atr in STOP_ATR_VALUES:
        for target_atr in TARGET_ATR_VALUES:
            for hold in HOLD_VALUES:

                counter += 1

                candidates = generate_candidates_param(
                    data,
                    breadth,
                    stop_atr,
                    target_atr,
                    hold,
                )

                result = simulate(candidates, data)

                row = {
                    "breadth": breadth,
                    "stop_atr": stop_atr,
                    "target_atr": target_atr,
                    "hold_days": hold,
                    **result,
                    "candidates": len(candidates),
                }

                results.append(row)

                print(
                    f"[{counter}/{total}] "
                    f"B={breadth:.2f} "
                    f"S={stop_atr:.2f} "
                    f"T={target_atr:.2f} "
                    f"H={hold} "
                    f"Trades={result['trades']} "
                    f"Ret={result['return']:.2f}% "
                    f"PF={result['pf']:.2f} "
                    f"DD={result['max_dd']:.2f}%"
                )

results.sort(key=lambda x: x["score"], reverse=True)

OUT.parent.mkdir(parents=True, exist_ok=True)

with OUT.open("w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

print()
print("=" * 90)
print("TOP 20 PARAMETER SETS")
print("=" * 90)

for i, r in enumerate(results[:20], 1):
    print(
        f"{i:2d}. "
        f"B={r['breadth']:.2f} "
        f"S={r['stop_atr']:.2f} "
        f"T={r['target_atr']:.2f} "
        f"H={r['hold_days']:2d} | "
        f"Ret={r['return']:7.2f}% | "
        f"PF={r['pf']:5.2f} | "
        f"Win={r['win_rate']:5.1f}% | "
        f"DD={r['max_dd']:6.2f}% | "
        f"Trades={r['trades']:3d} | "
        f"Score={r['score']:7.2f}"
    )

print()
print(f"Saved: {OUT}")
