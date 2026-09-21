import sqlite3
import csv
from pathlib import Path
from collections import defaultdict
from itertools import product

from app.analysis import backtest_final_v5b_2026 as v5b

DB_PATH = "/opt/bourse-bot/data/bourse.db"
OUT_PATH = "/opt/bourse-bot/data/v5b_oos_results.csv"

TRAIN_START = 20260101
TRAIN_END   = 20260630

OOS_START = 20260701
OOS_END   = 20260921

PARAMS = list(product(
    [0.38, 0.42, 0.46, 0.50],
    [1.25, 1.50, 1.75, 2.00],
    [2.50, 3.00, 3.50, 4.00],
    [7, 10, 12],
))


def prepare_base(data):
    base = []

    for n, (inscode, item) in enumerate(data.items(), 1):
        dates = item["dates"]
        closes = item["closes"]
        highs = item["highs"]
        lows = item["lows"]
        volumes = item["volumes"]
        gaps = item["gap_before"]

        for i in range(len(dates) - 1):
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
            entry_index = i + 1

            if entry_index >= len(dates):
                continue

            entry_date = dates[entry_index]

            if entry_date < TRAIN_START or entry_date > OOS_END:
                continue

            base.append({
                "symbol": item["symbol"],
                "inscode": inscode,
                "signal_date": signal_date,
                "entry_date": entry_date,
                "entry_index": entry_index,
                "entry": closes[entry_index],
                "atr": signal["atr"],
                "quality": signal["quality"],
            })

        if n % 50 == 0:
            print(f"Base signals [{n}/{len(data)}] = {len(base)}", flush=True)

    return base


def make_candidates(base, data, breadth, breadth_value,
                    stop_atr, target_atr, max_hold,
                    period_start, period_end):

    candidates = []

    for b in base:
        entry_date = b["entry_date"]

        if entry_date < period_start or entry_date > period_end:
            continue

        market = breadth.get(b["signal_date"])
        if market is None or market["breadth"] < breadth_value:
            continue

        item = data[b["inscode"]]
        dates = item["dates"]
        closes = item["closes"]
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
            len(dates) - 1
        )

        # Never allow a TRAIN trade to inspect future OOS data.
        while last_index > entry_index and dates[last_index] > period_end:
            last_index -= 1

        if last_index <= entry_index:
            continue

        exit_price = closes[last_index]
        exit_date = dates[last_index]
        exit_reason = "TIME"

        for j in range(entry_index + 1, last_index + 1):
            hit_stop = lows[j] <= stop
            hit_target = highs[j] >= target

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

        gross = (exit_price - entry) / entry
        net = gross - v5b.ROUND_TRIP_COST

        candidates.append({
            "symbol": b["symbol"],
            "inscode": b["inscode"],
            "signal_date": b["signal_date"],
            "entry_date": entry_date,
            "exit_date": exit_date,
            "entry": entry,
            "exit": exit_price,
            "stop": stop,
            "target": target,
            "return": net * 100,
            "quality": b["quality"],
            "reason": exit_reason,
            "breadth": market["breadth"],
        })

    return candidates


def build_price_map(data):
    price_map = {}

    for inscode, item in data.items():
        for date, close in zip(item["dates"], item["closes"]):
            price_map[(inscode, date)] = close

    return price_map


def simulate(candidates, data, period_start, period_end):
    by_date = defaultdict(list)

    for c in candidates:
        if period_start <= c["entry_date"] <= period_end:
            by_date[c["entry_date"]].append(c)

    all_dates = sorted({
        d
        for item in data.values()
        for d in item["dates"]
        if period_start <= d <= period_end
    })

    if not all_dates:
        return [], [], v5b.INITIAL_CAPITAL, 0.0

    price_map = build_price_map(data)

    cash = v5b.INITIAL_CAPITAL
    positions = []
    completed = []
    equity_curve = []

    for date in all_dates:

        # EXIT
        remaining = []

        for pos in positions:
            if pos["exit_date"] != date:
                remaining.append(pos)
                continue

            exit_price = pos["exit"]

            exit_value = pos["quantity"] * exit_price
            exit_fee = exit_value * v5b.EXIT_FEE

            pnl = (
                exit_value
                - pos["entry_value"]
                - pos["entry_fee"]
                - exit_fee
            )

            denom = pos["entry_value"] + pos["entry_fee"]

            completed.append({
                **pos,
                "pnl": pnl,
                "return_pct": (pnl / denom * 100) if denom else 0.0,
            })

            cash += exit_value - exit_fee

        positions = remaining

        # ENTRY
        day_candidates = sorted(
            by_date.get(date, []),
            key=lambda x: (-x["quality"], -x["breadth"])
        )

        for c in day_candidates:

            if len(positions) >= v5b.MAX_CONCURRENT_POSITIONS:
                break

            if any(
                p["inscode"] == c["inscode"]
                for p in positions
            ):
                continue

            entry = c["entry"]
            risk_per_share = entry - c["stop"]

            if risk_per_share <= 0:
                continue

            marked_open = 0.0

            for p in positions:
                px = price_map.get(
                    (p["inscode"], date),
                    p["entry"]
                )
                marked_open += p["quantity"] * px

            equity_before = cash + marked_open
            risk_budget = equity_before * v5b.RISK_PER_TRADE

            qty_risk = risk_budget / risk_per_share

            max_value = (
                equity_before * v5b.MAX_POSITION_WEIGHT
            )
            qty_weight = max_value / entry

            qty_cash = cash / (
                entry * (1 + v5b.ENTRY_FEE)
            )

            quantity = int(
                min(qty_risk, qty_weight, qty_cash)
            )

            if quantity <= 0:
                continue

            entry_value = quantity * entry
            entry_fee = entry_value * v5b.ENTRY_FEE

            cash -= entry_value + entry_fee

            positions.append({
                **c,
                "quantity": quantity,
                "entry_value": entry_value,
                "entry_fee": entry_fee,
            })

        # EQUITY
        equity = cash

        for p in positions:
            px = price_map.get(
                (p["inscode"], date),
                p["entry"]
            )
            equity += p["quantity"] * px

        equity_curve.append((date, equity))

    # Force-close anything still open at the period end.
    final_date = all_dates[-1]

    for pos in positions:
        exit_price = price_map.get(
            (pos["inscode"], final_date),
            pos["entry"]
        )

        exit_value = pos["quantity"] * exit_price
        exit_fee = exit_value * v5b.EXIT_FEE

        pnl = (
            exit_value
            - pos["entry_value"]
            - pos["entry_fee"]
            - exit_fee
        )

        denom = pos["entry_value"] + pos["entry_fee"]

        completed.append({
            **pos,
            "exit": exit_price,
            "exit_date": final_date,
            "reason": "PERIOD_END",
            "pnl": pnl,
            "return_pct": (pnl / denom * 100) if denom else 0.0,
        })

        cash += exit_value - exit_fee

    final_equity = cash

    peak = v5b.INITIAL_CAPITAL
    max_dd = 0.0

    for _, equity in equity_curve:
        if equity > peak:
            peak = equity

        dd = (
            (equity - peak) / peak
            if peak > 0 else 0.0
        )

        if dd < max_dd:
            max_dd = dd

    return completed, equity_curve, final_equity, max_dd


def metrics(completed):
    trades = len(completed)

    if trades == 0:
        return {
            "trades": 0,
            "return": -1.0,
            "win_rate": 0.0,
            "pf": 0.0,
            "dd": 0.0,
            "final": v5b.INITIAL_CAPITAL,
        }

    wins = [
        x["pnl"]
        for x in completed
        if x["pnl"] > 0
    ]

    losses = [
        x["pnl"]
        for x in completed
        if x["pnl"] < 0
    ]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0 else 999.0
    )

    return {
        "trades": trades,
        "win_rate": len(wins) / trades,
        "pf": pf,
    }


def run_one(data, breadth, params, start_date, end_date):
    b, s, t, h = params

    candidates = make_candidates(
        BASE,
        data,
        breadth,
        b,
        s,
        t,
        h,
        start_date,
        end_date,
    )

    completed, curve, final, dd = simulate(
        candidates,
        data,
        start_date,
        end_date,
    )

    m = metrics(completed)

    ret = (
        final / v5b.INITIAL_CAPITAL - 1
    )

    m["return"] = ret
    m["dd"] = dd
    m["final"] = final

    return m


def main():
    print("Loading data...", flush=True)

    conn = sqlite3.connect(DB_PATH)
    data = v5b.load_data(conn)
    conn.close()

    print(f"Valid symbols: {len(data)}", flush=True)

    print("Building breadth...", flush=True)
    breadth = v5b.build_breadth(data)

    global BASE

    print("Caching technical signals...", flush=True)
    BASE = prepare_base(data)

    print(f"Cached base signals: {len(BASE)}", flush=True)
    print("Testing TRAIN...", flush=True)

    rows = []

    for idx, params in enumerate(PARAMS, 1):
        m = run_one(
            data,
            breadth,
            params,
            TRAIN_START,
            TRAIN_END,
        )

        b, s, t, h = params

        row = {
            "breadth": b,
            "stop_atr": s,
            "target_atr": t,
            "hold": h,
            "trades_train": m["trades"],
            "return_train": m["return"],
            "win_train": m["win_rate"],
            "pf_train": m["pf"],
            "dd_train": m["dd"],
            "final_train": m["final"],
        }

        rows.append(row)

        if idx % 10 == 0 or idx == len(PARAMS):
            print(
                f"TRAIN [{idx}/{len(PARAMS)}]",
                flush=True
            )

    # Rank TRAIN by the same general objective used previously.
    def train_score(r):
        score = (
            r["return_train"]
            + r["pf_train"] * 4
            + r["win_train"] * 0.05
            + r["dd_train"] * 0.50
        )

        if r["trades_train"] < 25:
            score -= (25 - r["trades_train"]) * 0.20

        return score

    rows.sort(key=train_score, reverse=True)

    print()
    print("===== TOP TRAIN =====")

    for i, r in enumerate(rows[:10], 1):
        print(
            f"{i:02d}. "
            f"B={r['breadth']:.2f} "
            f"S={r['stop_atr']:.2f} "
            f"T={r['target_atr']:.2f} "
            f"H={r['hold']} | "
            f"Trades={r['trades_train']} | "
            f"Ret={r['return_train']:.2%} | "
            f"Win={r['win_train']:.2%} | "
            f"PF={r['pf_train']:.2f} | "
            f"DD={r['dd_train']:.2%}"
        )

    print()
    print("===== OOS TEST =====")

    for r in rows:
        params = (
            r["breadth"],
            r["stop_atr"],
            r["target_atr"],
            r["hold"],
        )

        m = run_one(
            data,
            breadth,
            params,
            OOS_START,
            OOS_END,
        )

        r.update({
            "trades_oos": m["trades"],
            "return_oos": m["return"],
            "win_oos": m["win_rate"],
            "pf_oos": m["pf"],
            "dd_oos": m["dd"],
            "final_oos": m["final"],
        })

    # Save all 192 rows.
    fields = list(rows[0].keys())

    with open(OUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    # Show top TRAIN combinations with OOS results.
    for i, r in enumerate(rows[:10], 1):
        print(
            f"{i:02d}. "
            f"B={r['breadth']:.2f} "
            f"S={r['stop_atr']:.2f} "
            f"T={r['target_atr']:.2f} "
            f"H={r['hold']} | "
            f"TRAIN "
            f"R={r['return_train']:.2%} "
            f"PF={r['pf_train']:.2f} "
            f"DD={r['dd_train']:.2%} | "
            f"OOS "
            f"Trades={r['trades_oos']} "
            f"R={r['return_oos']:.2%} "
            f"Win={r['win_oos']:.2%} "
            f"PF={r['pf_oos']:.2f} "
            f"DD={r['dd_oos']:.2%}"
        )

    print()
    print(f"Saved: {OUT_PATH}")


if __name__ == "__main__":
    main()
