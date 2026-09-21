import sqlite3
import csv
from pathlib import Path
from collections import defaultdict
from itertools import product

import app.analysis.backtest_final_v5b_2026 as v5b


DB_PATH = Path("/opt/bourse-bot/data/bourse.db")
OUT = Path("/opt/bourse-bot/data/v5b_optimization_fast.csv")

BREADTH_VALUES = [0.38, 0.42, 0.46, 0.50]
STOP_ATR_VALUES = [1.25, 1.50, 1.75, 2.00]
TARGET_ATR_VALUES = [2.50, 3.00, 3.50, 4.00]
HOLD_VALUES = [7, 10, 12]


def prepare_base(data):
    """
    Run the expensive technical_signal calculation only once.

    Each item contains everything needed to generate candidates for
    different breadth/stop/target/hold combinations.
    """
    base = []

    total = len(data)

    for n, (inscode, item) in enumerate(data.items(), 1):
        dates = item["dates"]
        closes = item["closes"]
        highs = item["highs"]
        lows = item["lows"]
        volumes = item["volumes"]
        gaps = item["gap_before"]

        for i in range(v5b.MIN_HISTORY, len(dates) - 1):

            signal = v5b.technical_signal(
                closes[:i + 1],
                highs[:i + 1],
                lows[:i + 1],
                volumes[:i + 1],
                gaps[:i + 1],
            )

            if signal is None or not signal["eligible"]:
                continue

            signal_date = dates[i]

            # Same entry-date restriction as the 2026 V5B backtest.
            entry_index = i + 1

            if entry_index >= len(dates):
                continue

            entry_date = dates[entry_index]

            if entry_date < 20260101 or entry_date > 20261231:
                continue

            entry = closes[entry_index]
            atr = signal["atr"]

            if entry <= 0 or atr <= 0:
                continue

            base.append({
                "symbol": item["symbol"],
                "inscode": inscode,
                "signal_date": signal_date,
                "entry_date": entry_date,
                "entry_index": entry_index,
                "entry": entry,
                "atr": atr,
                "quality": signal["quality"],
            })

        if n % 50 == 0:
            print(
                f"Base signals [{n}/{total}] = {len(base)}",
                flush=True,
            )

    return base


def make_candidates(base, data, breadth_map, breadth_value,
                    stop_atr, target_atr, max_hold):
    """
    Same V5B candidate/exit logic, parameterized.
    """
    candidates = []

    for b in base:
        market = breadth_map.get(b["signal_date"])

        if market is None:
            continue

        if market["breadth"] < breadth_value:
            continue

        item = data[b["inscode"]]
        dates = item["dates"]
        highs = item["highs"]
        lows = item["lows"]

        entry_index = b["entry_index"]
        entry = b["entry"]
        atr = b["atr"]

        stop = entry - stop_atr * atr
        target = entry + target_atr * atr

        if stop <= 0 or target <= entry:
            continue

        last_index = min(
            entry_index + max_hold,
            len(dates) - 1,
        )

        exit_price = dates and item["closes"][last_index]
        exit_date = dates[last_index]
        exit_reason = "TIME"

        for j in range(entry_index + 1, last_index + 1):
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

        candidates.append({
            "symbol": b["symbol"],
            "inscode": b["inscode"],
            "signal_date": b["signal_date"],
            "entry_date": b["entry_date"],
            "exit_date": exit_date,
            "entry": entry,
            "exit": exit_price,
            "stop": stop,
            "target": target,
            "return": (
                (exit_price - entry) / entry
                - v5b.ROUND_TRIP_COST
            ) * 100,
            "quality": b["quality"],
            "reason": exit_reason,
            "breadth": market["breadth"],
        })

    return candidates


def simulate(candidates, data):
    """
    Exact V5B portfolio simulation.
    """
    candidates_by_date = defaultdict(list)

    for trade in candidates:
        candidates_by_date[trade["entry_date"]].append(trade)

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

    price_map = {}

    for inscode, item in data.items():
        for date, close in zip(item["dates"], item["closes"]):
            price_map[(inscode, date)] = close

    cash = v5b.INITIAL_CAPITAL
    positions = []
    completed = []

    peak = cash
    max_dd = 0.0

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

                equity_before += current_price * p["quantity"]

            risk_budget = equity_before * v5b.RISK_PER_TRADE

            risk_per_share = (
                candidate["entry"] - candidate["stop"]
            )

            if risk_per_share <= 0:
                continue

            quantity_by_risk = risk_budget / risk_per_share

            max_value = (
                equity_before * v5b.MAX_POSITION_WEIGHT
            )

            quantity_by_weight = (
                max_value / candidate["entry"]
            )

            available = (
                cash /
                (candidate["entry"] * (1 + v5b.ENTRY_FEE))
            )

            quantity = int(min(
                quantity_by_risk,
                quantity_by_weight,
                available,
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

        peak = max(peak, equity)

        dd = (equity - peak) / peak * 100
        max_dd = min(max_dd, dd)

    last_date = all_dates[-1] if all_dates else None

    for pos in positions:
        last_price = price_map.get(
            (pos["inscode"], last_date),
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

    return completed, cash, max_dd


def metrics(completed, final_equity, max_dd):
    trades = len(completed)

    if trades == 0:
        return {
            "trades": 0,
            "return": 0.0,
            "win_rate": 0.0,
            "pf": 0.0,
            "dd": max_dd,
            "final": final_equity,
        }

    wins = [x["pnl"] for x in completed if x["pnl"] > 0]
    losses = [x["pnl"] for x in completed if x["pnl"] < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else 999.0
    )

    return {
        "trades": trades,
        "return": final_equity / v5b.INITIAL_CAPITAL - 1,
        "win_rate": len(wins) / trades,
        "pf": pf,
        "dd": max_dd / 100.0,
        "final": final_equity,
    }


def score(r):
    value = (
        r["return"]
        + r["pf"] * 4
        + r["win_rate"] * 0.05
        + r["dd"] * 0.50
    )

    if r["trades"] < 40:
        value -= (40 - r["trades"]) * 0.20

    return value


def main():
    print("Loading data...", flush=True)

    conn = sqlite3.connect(DB_PATH)

    try:
        data = v5b.load_data(conn)
    finally:
        conn.close()

    print(
        f"Valid symbols: {len(data)}",
        flush=True,
    )

    print("Building breadth...", flush=True)
    breadth_map = v5b.build_breadth(data)

    print("Caching technical signals...", flush=True)
    base = prepare_base(data)

    print(
        f"Base eligible entries: {len(base)}",
        flush=True,
    )

    combinations = list(product(
        BREADTH_VALUES,
        STOP_ATR_VALUES,
        TARGET_ATR_VALUES,
        HOLD_VALUES,
    ))

    print(
        f"Testing {len(combinations)} combinations...",
        flush=True,
    )

    results = []

    for n, (
        breadth,
        stop_atr,
        target_atr,
        max_hold,
    ) in enumerate(combinations, 1):

        candidates = make_candidates(
            base,
            data,
            breadth_map,
            breadth,
            stop_atr,
            target_atr,
            max_hold,
        )

        completed, final_equity, max_dd = simulate(
            candidates,
            data,
        )

        r = metrics(
            completed,
            final_equity,
            max_dd,
        )

        s = score(r)

        row = {
            "breadth": breadth,
            "stop_atr": stop_atr,
            "target_atr": target_atr,
            "hold": max_hold,
            "trades": r["trades"],
            "return": r["return"],
            "win_rate": r["win_rate"],
            "pf": r["pf"],
            "dd": r["dd"],
            "final": r["final"],
            "score": s,
        }

        results.append(row)

        print(
            f"[{n}/{len(combinations)}] "
            f"B={breadth:.2f} "
            f"S={stop_atr:.2f} "
            f"T={target_atr:.2f} "
            f"H={max_hold} "
            f"Trades={r['trades']} "
            f"Ret={r['return']:.2%} "
            f"PF={r['pf']:.2f} "
            f"DD={r['dd']:.2%}",
            flush=True,
        )

    results.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=results[0].keys(),
        )

        writer.writeheader()
        writer.writerows(results)

    print("\n===== TOP 20 PARAMETER SETS =====", flush=True)

    for i, r in enumerate(results[:20], 1):
        print(
            f"{i:02d}. "
            f"B={r['breadth']:.2f} "
            f"S={r['stop_atr']:.2f} "
            f"T={r['target_atr']:.2f} "
            f"H={r['hold']} | "
            f"Trades={r['trades']} | "
            f"Ret={r['return']:.2%} | "
            f"Win={r['win_rate']:.2%} | "
            f"PF={r['pf']:.2f} | "
            f"DD={r['dd']:.2%} | "
            f"Score={r['score']:.3f}",
            flush=True,
        )

    print(f"\nSaved: {OUT}", flush=True)


if __name__ == "__main__":
    main()
