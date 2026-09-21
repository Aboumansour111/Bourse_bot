import sqlite3
from pathlib import Path
from itertools import product
from collections import defaultdict

import app.analysis.backtest_final_v5b_2026 as v5b


DB_PATH = Path("/opt/bourse-bot/data/bourse.db")
OUT = Path("/opt/bourse-bot/data/v5b_optimization_fast.csv")

BREADTH_VALUES = [0.38, 0.42, 0.46, 0.50]
STOP_ATR_VALUES = [1.25, 1.50, 1.75, 2.00]
TARGET_ATR_VALUES = [2.50, 3.00, 3.50, 4.00]
HOLD_VALUES = [7, 10, 12]

ROUND_TRIP_COST = v5b.ROUND_TRIP_COST
ENTRY_FEE = v5b.ENTRY_FEE
EXIT_FEE = v5b.EXIT_FEE

INITIAL_CAPITAL = v5b.INITIAL_CAPITAL
RISK_PER_TRADE = v5b.RISK_PER_TRADE
MAX_POSITION_WEIGHT = v5b.MAX_POSITION_WEIGHT
MAX_CONCURRENT_POSITIONS = v5b.MAX_CONCURRENT_POSITIONS


def build_base_candidates(data, breadth):
    """
    Generate candidates using the exact V5B technical logic,
    but without stop/target/hold calculations.
    """
    all_dates = sorted(data["market"].keys())

    candidates = []

    for date in all_dates:
        market = data["market"].get(date)
        if not market:
            continue

        if market["breadth"] < breadth:
            continue

        daily = data["daily"].get(date, {})

        for symbol, row in daily.items():
            tech = data["technical"].get(symbol, {}).get(date)
            if not tech:
                continue

            signal = v5b.technical_signal(tech)

            if not signal:
                continue

            # Match original V5B eligibility.
            if signal["quality"] < 75:
                continue

            if signal["trend_count"] < 4:
                continue

            if signal["rsi"] >= 75:
                continue

            if signal["macd"] <= 0:
                continue

            vr = signal["volume_ratio"]

            if not (1.2 <= vr <= 3.0):
                continue

            if signal["atr"] <= 0:
                continue

            next_date = None
            for d in all_dates:
                if d > date:
                    next_date = d
                    break

            if next_date is None:
                continue

            next_row = data["daily"].get(next_date, {}).get(symbol)

            if not next_row:
                continue

            entry_price = next_row["close_price"]

            if entry_price <= 0:
                continue

            candidates.append({
                "entry_date": next_date,
                "signal_date": date,
                "symbol": symbol,
                "entry_price": entry_price,
                "atr": signal["atr"],
                "quality": signal["quality"],
                "breadth": market["breadth"],
            })

    return candidates


def prepare_candidates(data):
    """
    Breadth only affects candidate eligibility.
    Technical calculations are reused across all breadth levels.
    """
    cache = {}

    for breadth in BREADTH_VALUES:
        print(f"Preparing candidates B={breadth:.2f}...", flush=True)
        cache[breadth] = build_base_candidates(data, breadth)
        print(
            f"  candidates={len(cache[breadth])}",
            flush=True
        )

    return cache


def simulate(data, candidates, stop_atr, target_atr, max_hold):
    """
    Portfolio simulation matching V5B portfolio logic.
    """
    all_dates = sorted(data["market"].keys())

    by_entry = defaultdict(list)

    for c in candidates:
        by_entry[c["entry_date"]].append(c)

    equity = INITIAL_CAPITAL
    cash = INITIAL_CAPITAL

    positions = {}
    trades = []

    equity_curve = []

    for date in all_dates:
        daily = data["daily"].get(date, {})

        # ---------------------------------------------------------
        # EXIT
        # ---------------------------------------------------------
        for symbol in list(positions.keys()):
            pos = positions[symbol]

            row = daily.get(symbol)
            if not row:
                continue

            high = row["high_price"]
            low = row["low_price"]
            close = row["close_price"]

            stop = pos["stop"]
            target = pos["target"]

            exit_price = None
            reason = None

            # Exact V5B behavior:
            # If both happen on same day, STOP wins.
            if low <= stop:
                exit_price = stop
                reason = "STOP"

            elif high >= target:
                exit_price = target
                reason = "TARGET"

            elif pos["hold_days"] >= max_hold:
                exit_price = close
                reason = "TIME"

            if exit_price is None:
                continue

            gross = (exit_price - pos["entry_price"]) / pos["entry_price"]

            net = gross - ROUND_TRIP_COST

            pnl = pos["capital"] * net

            cash += pos["capital"] + pnl

            trades.append({
                "symbol": symbol,
                "entry_date": pos["entry_date"],
                "exit_date": date,
                "entry_price": pos["entry_price"],
                "exit_price": exit_price,
                "return": net,
                "pnl": pnl,
                "reason": reason,
            })

            del positions[symbol]

        # ---------------------------------------------------------
        # MARK OPEN POSITIONS
        # ---------------------------------------------------------
        open_value = 0.0

        for symbol, pos in positions.items():
            row = daily.get(symbol)

            if row:
                price = row["close_price"]
                open_value += pos["capital"] * (
                    price / pos["entry_price"]
                )

        equity = cash + open_value
        equity_curve.append((date, equity))

        # ---------------------------------------------------------
        # ENTRY
        # ---------------------------------------------------------
        todays = by_entry.get(date, [])

        if todays:
            # Exact V5B ordering.
            todays = sorted(
                todays,
                key=lambda x: (
                    x["quality"],
                    x["breadth"],
                ),
                reverse=True,
            )

            for c in todays:
                symbol = c["symbol"]

                if symbol in positions:
                    continue

                if len(positions) >= MAX_CONCURRENT_POSITIONS:
                    break

                atr = c["atr"]
                entry_price = c["entry_price"]

                stop = entry_price - stop_atr * atr
                target = entry_price + target_atr * atr

                risk_per_share = entry_price - stop

                if risk_per_share <= 0:
                    continue

                risk_capital = equity * RISK_PER_TRADE

                capital = risk_capital / (
                    risk_per_share / entry_price
                )

                max_capital = equity * MAX_POSITION_WEIGHT

                capital = min(capital, max_capital, cash)

                if capital <= 0:
                    continue

                cash -= capital

                positions[symbol] = {
                    "symbol": symbol,
                    "entry_date": date,
                    "entry_price": entry_price,
                    "capital": capital,
                    "stop": stop,
                    "target": target,
                    "hold_days": 0,
                }

        # Increment holding days after today's processing.
        for pos in positions.values():
            if pos["entry_date"] != date:
                pos["hold_days"] += 1

    # -------------------------------------------------------------
    # CLOSE OPEN POSITIONS AT LAST TEST DATE
    # -------------------------------------------------------------
    final_date = all_dates[-1]
    final_daily = data["daily"].get(final_date, {})

    for symbol in list(positions.keys()):
        pos = positions[symbol]
        row = final_daily.get(symbol)

        if not row:
            continue

        exit_price = row["close_price"]

        gross = (
            exit_price - pos["entry_price"]
        ) / pos["entry_price"]

        net = gross - ROUND_TRIP_COST

        pnl = pos["capital"] * net

        cash += pos["capital"] + pnl

        trades.append({
            "symbol": symbol,
            "entry_date": pos["entry_date"],
            "exit_date": final_date,
            "entry_price": pos["entry_price"],
            "exit_price": exit_price,
            "return": net,
            "pnl": pnl,
            "reason": "END",
        })

    final_equity = cash

    if not trades:
        return {
            "trades": 0,
            "return": 0.0,
            "win_rate": 0.0,
            "pf": 0.0,
            "dd": 0.0,
            "final": INITIAL_CAPITAL,
        }

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else 999.0
    )

    win_rate = len(wins) / len(trades)

    peak = INITIAL_CAPITAL
    max_dd = 0.0

    for _, eq in equity_curve:
        peak = max(peak, eq)

        if peak > 0:
            dd = (eq - peak) / peak
            max_dd = min(max_dd, dd)

    total_return = (
        final_equity / INITIAL_CAPITAL - 1
    )

    return {
        "trades": len(trades),
        "return": total_return,
        "win_rate": win_rate,
        "pf": pf,
        "dd": max_dd,
        "final": final_equity,
    }


def score_result(r):
    score = (
        r["return"]
        + r["pf"] * 4
        + r["win_rate"] * 0.05
        + r["dd"] * 0.50
    )

    if r["trades"] < 40:
        score -= (40 - r["trades"]) * 0.20

    return score


def main():
    print("Loading data...", flush=True)

    conn = sqlite3.connect(DB_PATH)
    try:
        data = v5b.load_data(conn)
    finally:
        conn.close()

    print(
        f"Valid symbols: {len(data['symbols'])}",
        flush=True
    )

    print("Preparing cached candidates...", flush=True)

    candidate_cache = prepare_candidates(data)

    combinations = list(
        product(
            BREADTH_VALUES,
            STOP_ATR_VALUES,
            TARGET_ATR_VALUES,
            HOLD_VALUES,
        )
    )

    print(
        f"Testing {len(combinations)} combinations...",
        flush=True
    )

    results = []

    for i, (
        breadth,
        stop_atr,
        target_atr,
        hold,
    ) in enumerate(combinations, 1):

        candidates = candidate_cache[breadth]

        r = simulate(
            data,
            candidates,
            stop_atr,
            target_atr,
            hold,
        )

        score = score_result(r)

        result = {
            "breadth": breadth,
            "stop_atr": stop_atr,
            "target_atr": target_atr,
            "hold": hold,
            "trades": r["trades"],
            "return": r["return"],
            "win_rate": r["win_rate"],
            "pf": r["pf"],
            "dd": r["dd"],
            "final": r["final"],
            "score": score,
        }

        results.append(result)

        print(
            f"[{i}/{len(combinations)}] "
            f"B={breadth:.2f} "
            f"S={stop_atr:.2f} "
            f"T={target_atr:.2f} "
            f"H={hold} "
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

    import csv

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
