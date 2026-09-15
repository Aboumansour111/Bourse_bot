import sqlite3
from collections import defaultdict

import backtest_final_v5b as base


DB_PATH = base.DB_PATH

TRAIN_START = 20250101
TRAIN_END = 20260331

OOS_START = 20260401
OOS_END = 20260915

VOLUME_LOW = 1.2
VOLUME_POOL_HIGH = 5.0

VOLUME_HIGH_VALUES = [
    2.0,
    2.5,
    3.0,
    3.5,
    4.0,
    5.0,
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
        dates = item["dates"]
        closes = item["closes"]

        previous = None

        for date, close in zip(dates, closes):
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


def technical_signal_pool(
    closes,
    highs,
    lows,
    volumes,
):
    """
    Exact v5b quality calculation.
    Only eligibility volume upper bound is relaxed
    to VOLUME_POOL_HIGH so that the sweep can later
    apply each tested upper bound independently.
    """

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

    eligible_pool = (
        trend >= 4
        and macd_hist is not None
        and macd_hist > 0
        and rsi14 is not None
        and rsi14 < 75
        and vol_ratio is not None
        and VOLUME_LOW <= vol_ratio <= VOLUME_POOL_HIGH
        and quality >= 75
        and atr14 is not None
        and atr14 > 0
    )

    if not eligible_pool:
        return None

    return {
        "quality": quality,
        "trend": trend,
        "rsi": rsi14,
        "macd_hist": macd_hist,
        "atr": atr14,
        "volume_ratio": vol_ratio,
    }


def generate_pool(data, breadth):
    pool = []

    for symbol_index, (inscode, item) in enumerate(
        data.items(), 1
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
            signal = technical_signal_pool(
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

            if market["breadth"] < 0.42:
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

            entry = closes[entry_index]

            atr14 = signal["atr"]

            stop = entry - (
                1.5 * atr14
            )

            target = entry + (
                3.0 * atr14
            )

            if stop <= 0 or target <= entry:
                continue

            last_index = min(
                entry_index + base.MAX_HOLD_DAYS,
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

            pool.append({
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
                "volume_ratio": signal["volume_ratio"],
            })

        if symbol_index % 50 == 0:
            print(
                f"Pool [{symbol_index}/{len(data)}]"
                f" = {len(pool)}"
            )

    return pool


def run_simulation(candidates, data):
    return base.simulate_portfolio(
        candidates,
        data,
    )


def stats(completed, final_equity, max_dd):
    trades = len(completed)

    if trades == 0:
        return {
            "trades": 0,
            "return": 0,
            "win": 0,
            "pf": 0,
            "expectancy": 0,
            "dd": max_dd,
            "target": 0,
            "stop": 0,
            "time": 0,
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
            len(wins) / trades
        ) * 100,
        "pf": pf,
        "expectancy": sum(returns) / trades,
        "dd": max_dd,
        "target": sum(
            1 for x in completed
            if x["reason"] == "TARGET"
        ),
        "stop": sum(
            1 for x in completed
            if x["reason"] == "STOP"
            or x["reason"]
            == "STOP_AND_TARGET_SAME_DAY"
        ),
        "time": sum(
            1 for x in completed
            if x["reason"] == "TIME"
        ),
    }


def filter_period(pool, start, end, volume_high):
    return [
        x for x in pool
        if (
            start <= x["entry_date"] <= end
            and start <= x["exit_date"] <= end
            and x["volume_ratio"] <= volume_high
        )
    ]


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
    print("=" * 90)
    print("BUILDING VOLUME POOL")
    print("=" * 90)

    pool = generate_pool(
        data,
        breadth,
    )

    print()
    print(
        f"Pool candidates: {len(pool)}"
    )

    # Sanity check against v5b baseline.
    baseline = [
        x for x in pool
        if VOLUME_LOW <= x["volume_ratio"] <= 3.0
    ]

    train_baseline = filter_period(
        pool,
        TRAIN_START,
        TRAIN_END,
        3.0,
    )

    oos_baseline = filter_period(
        pool,
        OOS_START,
        OOS_END,
        3.0,
    )

    print()
    print("=" * 90)
    print("SANITY CHECK")
    print("=" * 90)

    print(
        f"Baseline pool <= 3.0: "
        f"{len(baseline)}"
    )

    print(
        f"Train candidates <= 3.0: "
        f"{len(train_baseline)}"
    )

    print(
        f"OOS candidates <= 3.0: "
        f"{len(oos_baseline)}"
    )

    print()
    print("=" * 90)
    print("VOLUME HIGH SWEEP")
    print("=" * 90)

    print(
        "HIGH | "
        "TRAIN_TR | TRAIN_RET | TRAIN_PF | TRAIN_DD | "
        "OOS_TR | OOS_RET | OOS_PF | OOS_DD"
    )

    for high in VOLUME_HIGH_VALUES:

        train_candidates = filter_period(
            pool,
            TRAIN_START,
            TRAIN_END,
            high,
        )

        oos_candidates = filter_period(
            pool,
            OOS_START,
            OOS_END,
            high,
        )

        train_completed, _, train_final, train_dd = (
            run_simulation(
                train_candidates,
                data,
            )
        )

        oos_completed, _, oos_final, oos_dd = (
            run_simulation(
                oos_candidates,
                data,
            )
        )

        train = stats(
            train_completed,
            train_final,
            train_dd,
        )

        oos = stats(
            oos_completed,
            oos_final,
            oos_dd,
        )

        print(
            f"{high:>4.1f} | "
            f"{train['trades']:>8} | "
            f"{train['return']:>9.2f}% | "
            f"{train['pf']:>8.2f} | "
            f"{train['dd']:>8.2f}% | "
            f"{oos['trades']:>6} | "
            f"{oos['return']:>7.2f}% | "
            f"{oos['pf']:>6.2f} | "
            f"{oos['dd']:>7.2f}%"
        )


if __name__ == "__main__":
    main()
