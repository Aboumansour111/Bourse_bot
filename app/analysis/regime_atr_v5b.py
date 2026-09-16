import sqlite3
from collections import defaultdict
from statistics import mean

import backtest_final_v5b as base


DB_PATH = base.DB_PATH

INITIAL_CAPITAL = base.INITIAL_CAPITAL

# ATR configs selected from previous robustness test.
ATR_CONFIGS = [
    (1.00, 3.00),
    (1.00, 3.50),
    (1.00, 3.75),
    (1.20, 3.50),
    (1.20, 3.75),
    (1.70, 3.00),
    (1.80, 3.00),
    (1.90, 3.00),
    (1.50, 3.00),   # baseline
]

# Breadth thresholds to test.
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

WINDOWS = [
    ("WF1", 20250701, 20251231),
    ("WF2", 20260101, 20260331),
    ("WF3", 20260401, 20260630),
    ("WF4", 20260701, 20260915),
]


def load_data():
    conn = sqlite3.connect(DB_PATH)

    symbols = conn.execute("""
        SELECT inscode, symbol
        FROM symbols
        WHERE active = 1
        ORDER BY inscode
    """).fetchall()

    data = {}

    for inscode, symbol in symbols:
        rows = conn.execute("""
            SELECT
                trade_date,
                close_price,
                high_price,
                low_price,
                volume
            FROM daily_prices
            WHERE inscode = ?
              AND close_price IS NOT NULL
              AND close_price > 0
              AND high_price IS NOT NULL
              AND high_price > 0
              AND low_price IS NOT NULL
              AND low_price > 0
              AND volume IS NOT NULL
              AND volume > 0
              AND high_price >= low_price
              AND close_price >= low_price
              AND close_price <= high_price
            ORDER BY trade_date ASC
        """, (inscode,)).fetchall()

        if len(rows) < base.MIN_HISTORY + 2:
            continue

        data[inscode] = {
            "symbol": symbol,
            "dates": [r[0] for r in rows],
            "closes": [float(r[1]) for r in rows],
            "highs": [float(r[2]) for r in rows],
            "lows": [float(r[3]) for r in rows],
            "volumes": [float(r[4]) for r in rows],
        }

    conn.close()
    return data


def build_market_context(data):
    daily_states = defaultdict(dict)
    daily_returns = defaultdict(list)

    for inscode, item in data.items():
        dates = item["dates"]
        closes = item["closes"]

        for i in range(1, len(dates)):
            prev = closes[i - 1]
            current = closes[i]

            if current > prev:
                state = 1
            elif current < prev:
                state = -1
            else:
                state = 0

            daily_states[dates[i]][inscode] = state

            if prev > 0:
                daily_returns[dates[i]].append(
                    (current / prev - 1.0) * 100
                )

    context = {}

    all_dates = sorted(daily_states)

    for date in all_dates:
        states = daily_states[date]

        positive = sum(1 for x in states.values() if x > 0)
        negative = sum(1 for x in states.values() if x < 0)
        unchanged = sum(1 for x in states.values() if x == 0)

        total = positive + negative + unchanged

        if total == 0:
            continue

        breadth = positive / total

        avg_change = (
            mean(daily_returns[date])
            if daily_returns[date]
            else 0.0
        )

        context[date] = {
            "breadth": breadth,
            "avg_change": avg_change,
            "positive": positive,
            "negative": negative,
            "unchanged": unchanged,
        }

    # Historical breadth momentum.
    # Only past days are used.
    dates = sorted(context)

    for i, date in enumerate(dates):
        previous_breadths = [
            context[dates[j]]["breadth"]
            for j in range(max(0, i - 5), i)
        ]

        previous_changes = [
            context[dates[j]]["avg_change"]
            for j in range(max(0, i - 5), i)
        ]

        context[date]["breadth_ma5"] = (
            mean(previous_breadths)
            if previous_breadths
            else None
        )

        context[date]["change_ma5"] = (
            mean(previous_changes)
            if previous_changes
            else None
        )

    return context


def technical_signal(closes, highs, lows, volumes):
    current = closes[-1]

    sma20 = base.sma(closes, 20)
    sma50 = base.sma(closes, 50)
    sma200 = base.sma(closes, 200)

    ema20_values = base.ema_series(closes, 20)
    ema50_values = base.ema_series(closes, 50)

    if not ema20_values or not ema50_values:
        return None

    ema20 = ema20_values[-1]
    ema50 = ema50_values[-1]

    rsi14 = base.rsi(closes, 14)
    macd_hist = base.macd_histogram(closes)
    atr14 = base.atr(highs, lows, closes, 14)
    vol_ratio = base.volume_ratio(volumes, 20)

    trend = 0

    if sma20 is not None and current > sma20:
        trend += 1

    if sma50 is not None and current > sma50:
        trend += 1

    if sma200 is not None and current > sma200:
        trend += 1

    if ema20 is not None and ema50 is not None:
        if ema20 > ema50:
            trend += 1

    quality = 0.0

    if trend == 4:
        quality += 25
    elif trend == 3:
        quality += 20
    elif trend == 2:
        quality += 10

    if rsi14 is not None:
        if 50 <= rsi14 <= 65:
            quality += 20
        elif 65 < rsi14 <= 70:
            quality += 14
        elif 70 < rsi14 <= 75:
            quality += 7
        elif rsi14 > 75:
            quality -= 5
        else:
            quality += 3

    if macd_hist is not None:
        if macd_hist > 0:
            quality += 20
        else:
            quality -= 5

    if vol_ratio is not None:
        if 1.2 <= vol_ratio <= 3:
            quality += 15
        elif 1 <= vol_ratio < 1.2:
            quality += 10
        elif 3 < vol_ratio <= 5:
            quality += 10
        elif 5 < vol_ratio <= 8:
            quality += 4
        elif vol_ratio > 8:
            quality -= 5
        else:
            quality += 2

    eligible = (
        trend >= 4
        and macd_hist is not None
        and macd_hist > 0
        and rsi14 is not None
        and rsi14 < 75
        and vol_ratio is not None
        and 1.2 <= vol_ratio <= 3.0
        and quality >= 75
        and atr14 is not None
        and atr14 > 0
    )

    if not eligible:
        return None

    return {
        "quality": quality,
        "atr": atr14,
    }


def build_pool(data):
    pool = []

    for inscode, item in data.items():
        dates = item["dates"]
        closes = item["closes"]
        highs = item["highs"]
        lows = item["lows"]
        volumes = item["volumes"]

        for i in range(base.MIN_HISTORY, len(dates) - 1):
            signal = technical_signal(
                closes[:i + 1],
                highs[:i + 1],
                lows[:i + 1],
                volumes[:i + 1],
            )

            if signal is None:
                continue

            entry_index = i + 1

            if entry_index >= len(dates):
                continue

            entry_date = dates[entry_index]

            if entry_date < 20250101 or entry_date > 20261231:
                continue

            pool.append({
                "symbol": item["symbol"],
                "inscode": inscode,
                "signal_date": dates[i],
                "entry_date": entry_date,
                "entry_index": entry_index,
                "entry": closes[entry_index],
                "atr": signal["atr"],
                "quality": signal["quality"],
                "dates": dates,
                "closes": closes,
                "highs": highs,
                "lows": lows,
            })

    return pool


def build_candidates(pool, stop_mult, target_mult):
    candidates = []

    for x in pool:
        dates = x["dates"]
        closes = x["closes"]
        highs = x["highs"]
        lows = x["lows"]

        entry_index = x["entry_index"]
        entry = x["entry"]
        atr = x["atr"]

        stop = entry - stop_mult * atr
        target = entry + target_mult * atr

        if stop <= 0 or target <= entry:
            continue

        last_index = min(
            entry_index + base.MAX_HOLD_DAYS,
            len(dates) - 1,
        )

        exit_price = closes[last_index]
        exit_date = dates[last_index]
        reason = "TIME"

        for j in range(entry_index + 1, last_index + 1):
            hit_stop = lows[j] <= stop
            hit_target = highs[j] >= target

            if hit_stop and hit_target:
                exit_price = stop
                exit_date = dates[j]
                reason = "STOP_AND_TARGET_SAME_DAY"
                break

            if hit_stop:
                exit_price = stop
                exit_date = dates[j]
                reason = "STOP"
                break

            if hit_target:
                exit_price = target
                exit_date = dates[j]
                reason = "TARGET"
                break

        net_return = (
            (exit_price - entry) / entry
            - base.ROUND_TRIP_COST
        )

        candidates.append({
            "symbol": x["symbol"],
            "inscode": x["inscode"],
            "signal_date": x["signal_date"],
            "entry_date": x["entry_date"],
            "exit_date": exit_date,
            "entry": entry,
            "exit": exit_price,
            "stop": stop,
            "target": target,
            "return": net_return * 100,
            "quality": x["quality"],
            "breadth": 0,
            "reason": reason,
        })

    return candidates


def apply_regime_filter(candidates, context, mode, threshold):
    result = []

    for x in candidates:
        date = x["signal_date"]
        market = context.get(date)

        if market is None:
            continue

        breadth = market["breadth"]
        avg_change = market["avg_change"]
        breadth_ma5 = market["breadth_ma5"]
        change_ma5 = market["change_ma5"]

        ok = False

        if mode == "BREADTH":
            ok = breadth >= threshold

        elif mode == "BREADTH_MOMENTUM":
            ok = (
                breadth >= threshold
                and breadth_ma5 is not None
                and breadth >= breadth_ma5
            )

        elif mode == "BREADTH_AND_CHANGE":
            ok = (
                breadth >= threshold
                and avg_change > 0
            )

        elif mode == "FULL":
            ok = (
                breadth >= threshold
                and breadth_ma5 is not None
                and breadth >= breadth_ma5
                and avg_change > 0
                and change_ma5 is not None
                and avg_change >= change_ma5
            )

        if not ok:
            continue

        y = dict(x)
        y["breadth"] = breadth
        result.append(y)

    return result


def run(candidates, data, start, end):
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
            final_equity / INITIAL_CAPITAL - 1
        ) * 100,
        "win": len(wins) / trades * 100,
        "pf": pf,
        "dd": max_dd,
    }


def main():
    print("Loading data...")
    data = load_data()
    print(f"Valid symbols: {len(data)}")

    print("Building market context...")
    context = build_market_context(data)
    print(f"Market dates: {len(context)}")

    print("Building technical signal pool...")
    pool = build_pool(data)
    print(f"Technical pool: {len(pool)}")

    all_candidates = {}

    for atr in ATR_CONFIGS:
        print(
            f"Building ATR {atr[0]:.2f}/{atr[1]:.2f}"
        )
        all_candidates[atr] = build_candidates(
            pool,
            atr[0],
            atr[1],
        )

    modes = [
        "BREADTH",
        "BREADTH_MOMENTUM",
        "BREADTH_AND_CHANGE",
        "FULL",
    ]

    print()
    print("=" * 130)
    print("MARKET REGIME + ATR WALK-FORWARD")
    print("=" * 130)

    all_rows = []

    for mode in modes:
        for threshold in BREADTH_LEVELS:
            print()
            print(
                f"MODE={mode} "
                f"THRESHOLD={threshold:.2f}"
            )

            for atr, candidates in all_candidates.items():
                filtered = apply_regime_filter(
                    candidates,
                    context,
                    mode,
                    threshold,
                )

                results = []

                for name, start, end in WINDOWS:
                    stats = run(
                        filtered,
                        data,
                        start,
                        end,
                    )

                    results.append(stats)

                avg_return = mean(
                    x["return"] for x in results
                )

                valid_pf = [
                    x["pf"]
                    for x in results
                    if x["trades"] > 0
                ]

                avg_pf = (
                    mean(valid_pf)
                    if valid_pf
                    else 0
                )

                positive_windows = sum(
                    x["return"] > 0
                    for x in results
                )

                worst_dd = min(
                    x["dd"]
                    for x in results
                )

                total_trades = sum(
                    x["trades"]
                    for x in results
                )

                all_rows.append({
                    "mode": mode,
                    "threshold": threshold,
                    "stop": atr[0],
                    "target": atr[1],
                    "avg_return": avg_return,
                    "avg_pf": avg_pf,
                    "positive_windows": positive_windows,
                    "worst_dd": worst_dd,
                    "trades": total_trades,
                    "results": results,
                })

                print(
                    f"ATR {atr[0]:.2f}/{atr[1]:.2f} | "
                    f"AVG={avg_return:7.2f}% | "
                    f"PF={avg_pf:5.2f} | "
                    f"POS={positive_windows}/4 | "
                    f"DD={worst_dd:7.2f}% | "
                    f"TRADES={total_trades}"
                )

    print()
    print("=" * 130)
    print("TOP REGIME + ATR CONFIGURATIONS")
    print("=" * 130)

    # Require at least 20 total OOS trades.
    valid = [
        x for x in all_rows
        if x["trades"] >= 20
    ]

    # Score rewards return and PF,
    # rewards consistency,
    # penalizes drawdown.
    for x in valid:
        x["score"] = (
            x["avg_return"]
            + x["avg_pf"] * 4
            + x["positive_windows"] * 3
            + x["worst_dd"] * 0.5
        )

    valid.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    print(
        "MODE | TH | ATR | AVG_RET | AVG_PF | "
        "POS | WORST_DD | TRADES | SCORE"
    )

    for x in valid[:25]:
        print(
            f"{x['mode']:18s} | "
            f"{x['threshold']:.2f} | "
            f"{x['stop']:.2f}/{x['target']:.2f} | "
            f"{x['avg_return']:7.2f}% | "
            f"{x['avg_pf']:6.2f} | "
            f"{x['positive_windows']}/4 | "
            f"{x['worst_dd']:8.2f}% | "
            f"{x['trades']:6d} | "
            f"{x['score']:7.2f}"
        )

    print()
    print("=" * 130)
    print("TOP CONFIG DETAILS")
    print("=" * 130)

    for x in valid[:10]:
        print()
        print(
            f"{x['mode']} | "
            f"TH={x['threshold']:.2f} | "
            f"ATR={x['stop']:.2f}/{x['target']:.2f}"
        )

        for i, result in enumerate(
            x["results"],
            1,
        ):
            print(
                f"  WF{i}: "
                f"TR={result['trades']:3d} "
                f"RET={result['return']:7.2f}% "
                f"WIN={result['win']:6.2f}% "
                f"PF={result['pf']:5.2f} "
                f"DD={result['dd']:7.2f}%"
            )


if __name__ == "__main__":
    main()
