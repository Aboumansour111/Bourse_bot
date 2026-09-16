import sqlite3
from collections import defaultdict

import backtest_final_v5b as base


DB_PATH = base.DB_PATH

BREADTH_THRESHOLD = 0.42
VOLUME_LOW = 1.2
VOLUME_HIGH = 3.0
QUALITY_THRESHOLD = 75

MAX_HOLD_DAYS = base.MAX_HOLD_DAYS

# ATR configurations.
# We deliberately include the current baseline and the
# promising regions found in the previous sweep.
CONFIGS = [
    (1.00, 3.00),
    (1.00, 3.25),
    (1.00, 3.50),
    (1.00, 3.75),

    (1.10, 3.00),
    (1.10, 3.25),
    (1.10, 3.50),
    (1.10, 3.75),

    (1.20, 3.00),
    (1.20, 3.25),
    (1.20, 3.50),
    (1.20, 3.75),

    (1.30, 3.00),
    (1.30, 3.25),
    (1.30, 3.50),

    (1.50, 3.00),

    (1.60, 3.00),
    (1.70, 3.00),
    (1.80, 3.00),
    (1.90, 3.00),
    (2.00, 3.00),
]


# ---------------------------------------------------------
# Walk-forward windows
# ---------------------------------------------------------
#
# Each OOS period is evaluated independently.
# The train period is used only for diagnostics here;
# no parameter is selected using the OOS result.
#
# The final 2026 OOS window is especially important because
# it is the same regime used in the previous Train/OOS test.
#
WINDOWS = [
    {
        "name": "WF1",
        "train_start": 20250101,
        "train_end": 20250630,
        "oos_start": 20250701,
        "oos_end": 20251231,
    },
    {
        "name": "WF2",
        "train_start": 20250101,
        "train_end": 20251231,
        "oos_start": 20260101,
        "oos_end": 20260331,
    },
    {
        "name": "WF3",
        "train_start": 20250101,
        "train_end": 20260331,
        "oos_start": 20260401,
        "oos_end": 20260630,
    },
    {
        "name": "WF4",
        "train_start": 20250101,
        "train_end": 20260630,
        "oos_start": 20260701,
        "oos_end": 20260915,
    },
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


def build_breadth(data):
    daily = defaultdict(dict)

    for inscode, item in data.items():
        previous = None

        for date, close in zip(
            item["dates"],
            item["closes"],
        ):
            if previous is None:
                previous = close
                continue

            if close > previous:
                state = 1
            elif close < previous:
                state = -1
            else:
                state = 0

            daily[date][inscode] = state
            previous = close

    breadth = {}

    for date, states in daily.items():
        positive = sum(
            1 for x in states.values()
            if x > 0
        )
        negative = sum(
            1 for x in states.values()
            if x < 0
        )
        unchanged = sum(
            1 for x in states.values()
            if x == 0
        )

        total = (
            positive
            + negative
            + unchanged
        )

        if total:
            breadth[date] = {
                "positive": positive,
                "negative": negative,
                "unchanged": unchanged,
                "breadth": positive / total,
            }

    return breadth


def technical_signal(
    closes,
    highs,
    lows,
    volumes,
):
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
    atr14 = base.atr(
        highs,
        lows,
        closes,
        14,
    )
    vol_ratio = base.volume_ratio(
        volumes,
        20,
    )

    trend = 0

    if sma20 is not None and current > sma20:
        trend += 1

    if sma50 is not None and current > sma50:
        trend += 1

    if sma200 is not None and current > sma200:
        trend += 1

    if (
        ema20 is not None
        and ema50 is not None
        and ema20 > ema50
    ):
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

    if not (
        trend >= 4
        and macd_hist is not None
        and macd_hist > 0
        and rsi14 is not None
        and rsi14 < 75
        and vol_ratio is not None
        and VOLUME_LOW <= vol_ratio <= VOLUME_HIGH
        and quality >= QUALITY_THRESHOLD
        and atr14 is not None
        and atr14 > 0
    ):
        return None

    return {
        "quality": quality,
        "atr": atr14,
        "volume_ratio": vol_ratio,
    }


def generate_pool(data, breadth):
    pool = []

    for symbol_index, (inscode, item) in enumerate(
        data.items(),
        1,
    ):
        dates = item["dates"]
        closes = item["closes"]
        highs = item["highs"]
        lows = item["lows"]
        volumes = item["volumes"]

        for i in range(
            base.MIN_HISTORY,
            len(dates) - 1,
        ):
            signal = technical_signal(
                closes[:i + 1],
                highs[:i + 1],
                lows[:i + 1],
                volumes[:i + 1],
            )

            if signal is None:
                continue

            signal_date = dates[i]
            market = breadth.get(signal_date)

            if market is None:
                continue

            if market["breadth"] < BREADTH_THRESHOLD:
                continue

            entry_index = i + 1

            if entry_index >= len(dates):
                continue

            entry_date = dates[entry_index]

            if (
                entry_date < 20250101
                or entry_date > 20261231
            ):
                continue

            pool.append({
                "symbol": item["symbol"],
                "inscode": inscode,
                "signal_date": signal_date,
                "entry_date": entry_date,
                "entry_index": entry_index,
                "entry": closes[entry_index],
                "atr": signal["atr"],
                "quality": signal["quality"],
                "breadth": market["breadth"],
                "dates": dates,
                "closes": closes,
                "highs": highs,
                "lows": lows,
            })

        if symbol_index % 100 == 0:
            print(
                f"Pool [{symbol_index}/{len(data)}]"
                f" = {len(pool)}"
            )

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
        atr14 = x["atr"]

        stop = entry - stop_mult * atr14
        target = entry + target_mult * atr14

        if stop <= 0 or target <= entry:
            continue

        last_index = min(
            entry_index + MAX_HOLD_DAYS,
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
                exit_reason = (
                    "STOP_AND_TARGET_SAME_DAY"
                )
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
            (exit_price - entry)
            / entry
        )

        net_return = (
            gross_return
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
            "reason": exit_reason,
            "breadth": x["breadth"],
        })

    return candidates


def period_candidates(candidates, start, end):
    return [
        x for x in candidates
        if start <= x["entry_date"] <= end
        and start <= x["exit_date"] <= end
    ]


def run_period(candidates, data, start, end):
    selected = period_candidates(
        candidates,
        start,
        end,
    )

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
            "avg": 0.0,
            "dd": 0.0,
        }

    returns = [
        x["return_pct"]
        for x in completed
    ]

    wins = [
        x for x in returns
        if x > 0
    ]

    losses = [
        x for x in returns
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
        ) * 100,
        "pf": pf,
        "avg": sum(returns) / trades,
        "dd": max_dd,
    }


def main():
    print("Loading data...")
    data = load_data()

    print(
        f"Valid symbols: {len(data)}"
    )

    print(
        "Building historical market breadth..."
    )

    breadth = build_breadth(data)

    print(
        f"Breadth dates: {len(breadth)}"
    )

    print()
    print("=" * 100)
    print("BUILDING BASE SIGNAL POOL")
    print("=" * 100)

    pool = generate_pool(
        data,
        breadth,
    )

    print()
    print(
        f"Base pool candidates: {len(pool)}"
    )

    # Build candidate set once per ATR configuration.
    all_candidates = {}

    for stop_mult, target_mult in CONFIGS:
        print(
            f"Building "
            f"STOP={stop_mult:.2f} "
            f"TARGET={target_mult:.2f}"
        )

        all_candidates[
            (stop_mult, target_mult)
        ] = build_candidates(
            pool,
            stop_mult,
            target_mult,
        )

    print()
    print("=" * 120)
    print("WALK-FORWARD OOS RESULTS")
    print("=" * 120)

    for window in WINDOWS:
        print()
        print(
            "=" * 120
        )
        print(
            f"{window['name']}  "
            f"TRAIN {window['train_start']}→{window['train_end']}  "
            f"OOS {window['oos_start']}→{window['oos_end']}"
        )
        print(
            "=" * 120
        )

        print(
            "STOP | TARGET | "
            "OOS_TR | OOS_RET | OOS_WIN | OOS_PF | OOS_DD"
        )

        rows = []

        for config, candidates in all_candidates.items():
            stop_mult, target_mult = config

            oos = run_period(
                candidates,
                data,
                window["oos_start"],
                window["oos_end"],
            )

            print(
                f"{stop_mult:4.2f} | "
                f"{target_mult:6.2f} | "
                f"{oos['trades']:6d} | "
                f"{oos['return']:8.2f}% | "
                f"{oos['win']:8.2f}% | "
                f"{oos['pf']:6.2f} | "
                f"{oos['dd']:7.2f}%"
            )

            rows.append(
                (
                    oos["return"],
                    oos["pf"],
                    oos["dd"],
                    oos["trades"],
                    stop_mult,
                    target_mult,
                )
            )

        rows.sort(
            key=lambda x: x[0],
            reverse=True,
        )

        print()
        print("TOP 5 BY OOS RETURN:")

        for row in rows[:5]:
            (
                ret,
                pf,
                dd,
                trades,
                stop_mult,
                target_mult,
            ) = row

            print(
                f"STOP={stop_mult:.2f} "
                f"TARGET={target_mult:.2f} | "
                f"RETURN={ret:.2f}% "
                f"PF={pf:.2f} "
                f"DD={dd:.2f}% "
                f"TRADES={trades}"
            )

    # -----------------------------------------------------
    # Robustness summary
    # -----------------------------------------------------

    print()
    print("=" * 120)
    print("ROBUSTNESS SUMMARY")
    print("=" * 120)

    summary = []

    for config, candidates in all_candidates.items():
        stop_mult, target_mult = config

        window_results = []

        for window in WINDOWS:
            oos = run_period(
                candidates,
                data,
                window["oos_start"],
                window["oos_end"],
            )

            window_results.append(oos)

        returns = [
            x["return"]
            for x in window_results
        ]

        pfs = [
            x["pf"]
            for x in window_results
            if x["trades"] > 0
        ]

        dds = [
            x["dd"]
            for x in window_results
        ]

        positive_windows = sum(
            1 for x in returns
            if x > 0
        )

        avg_return = (
            sum(returns) / len(returns)
        )

        avg_pf = (
            sum(pfs) / len(pfs)
            if pfs
            else 0
        )

        worst_dd = min(dds)

        # Robustness score:
        # reward positive consistency and PF,
        # penalize drawdown.
        score = (
            avg_return
            + positive_windows * 5.0
            + avg_pf * 5.0
            + worst_dd * 0.5
        )

        summary.append({
            "stop": stop_mult,
            "target": target_mult,
            "avg_return": avg_return,
            "positive_windows": positive_windows,
            "avg_pf": avg_pf,
            "worst_dd": worst_dd,
            "score": score,
            "returns": returns,
        })

    summary.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    print(
        "STOP | TARGET | "
        "AVG_RET | POS_W | AVG_PF | WORST_DD | SCORE | "
        "WF1 | WF2 | WF3 | WF4"
    )

    for x in summary:
        print(
            f"{x['stop']:4.2f} | "
            f"{x['target']:6.2f} | "
            f"{x['avg_return']:7.2f}% | "
            f"{x['positive_windows']:5d} | "
            f"{x['avg_pf']:6.2f} | "
            f"{x['worst_dd']:8.2f}% | "
            f"{x['score']:6.2f} | "
            f"{x['returns'][0]:6.2f}% | "
            f"{x['returns'][1]:6.2f}% | "
            f"{x['returns'][2]:6.2f}% | "
            f"{x['returns'][3]:6.2f}%"
        )

    print()
    print("TOP ROBUST CONFIGS:")

    for x in summary[:10]:
        print(
            f"STOP={x['stop']:.2f} "
            f"TARGET={x['target']:.2f} | "
            f"AVG_RETURN={x['avg_return']:.2f}% | "
            f"POSITIVE_WINDOWS="
            f"{x['positive_windows']}/"
            f"{len(WINDOWS)} | "
            f"AVG_PF={x['avg_pf']:.2f} | "
            f"WORST_DD={x['worst_dd']:.2f}% | "
            f"SCORE={x['score']:.2f}"
        )


if __name__ == "__main__":
    main()
