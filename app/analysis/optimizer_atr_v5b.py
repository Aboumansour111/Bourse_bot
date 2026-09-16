import sqlite3
from collections import defaultdict

import backtest_final_v5b as base


DB_PATH = base.DB_PATH

TRAIN_START = 20250101
TRAIN_END = 20260331

OOS_START = 20260401
OOS_END = 20260915

BREADTH_THRESHOLD = 0.42
VOLUME_LOW = 1.2
VOLUME_HIGH = 3.0
QUALITY_THRESHOLD = 75

CONFIGS = [
    (stop, target)
    for stop in [
        1.10,
        1.20,
        1.30,
        1.40,
        1.50,
        1.60,
        1.70,
        1.80,
        1.90,
        2.00,
    ]
    for target in [
        2.75,
        3.00,
        3.25,
        3.50,
        3.75,
    ]
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

            entry = closes[entry_index]

            pool.append({
                "symbol": item["symbol"],
                "inscode": inscode,
                "signal_date": signal_date,
                "entry_date": entry_date,
                "entry": entry,
                "atr": signal["atr"],
                "quality": signal["quality"],
                "breadth": market["breadth"],
                "dates": dates,
                "closes": closes,
                "highs": highs,
                "lows": lows,
            })

        if symbol_index % 50 == 0:
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

        entry_date = x["entry_date"]

        entry_index = dates.index(entry_date)

        entry = x["entry"]
        atr14 = x["atr"]

        stop = entry - stop_mult * atr14
        target = entry + target_mult * atr14

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
            (exit_price - entry) / entry
        )

        net_return = (
            gross_return
            - base.ROUND_TRIP_COST
        )

        candidates.append({
            "symbol": x["symbol"],
            "inscode": x["inscode"],
            "signal_date": x["signal_date"],
            "entry_date": entry_date,
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


def filter_period(candidates, start, end):
    return [
        x for x in candidates
        if start <= x["entry_date"] <= end
        and start <= x["exit_date"] <= end
    ]


def calculate_stats(completed, final_equity, max_dd):
    trades = len(completed)

    if trades == 0:
        return {
            "trades": 0,
            "return": 0.0,
            "win": 0.0,
            "avg": 0.0,
            "pf": 0.0,
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
        r for r in returns
        if r > 0
    ]

    losses = [
        r for r in returns
        if r <= 0
    ]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    pf = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    reasons = [
        x.get("reason")
        for x in completed
    ]

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
        "avg": sum(returns) / trades,
        "pf": pf,
        "dd": max_dd,
        "target": reasons.count("TARGET"),
        "stop": reasons.count("STOP"),
        "time": reasons.count("TIME"),
    }


def run_config(candidates, data, start, end):
    selected = filter_period(
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

    return calculate_stats(
        completed,
        final_equity,
        max_dd,
    )


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
    print("=" * 110)
    print("BUILDING BASE SIGNAL POOL")
    print("=" * 110)

    pool = generate_pool(
        data,
        breadth,
    )

    print()
    print(
        f"Base pool candidates: {len(pool)}"
    )

    print()
    print("=" * 110)
    print("ATR STOP / TARGET SWEEP")
    print("=" * 110)

    print(
        "STOP | TARGET | "
        "TR_C | TR_RET | TR_WIN | TR_PF | TR_DD | "
        "OOS_C | OOS_RET | OOS_WIN | OOS_PF | OOS_DD | "
        "TGT | STP | TIME"
    )

    results = []

    for stop_mult, target_mult in CONFIGS:

        candidates = build_candidates(
            pool,
            stop_mult,
            target_mult,
        )

        train = run_config(
            candidates,
            data,
            TRAIN_START,
            TRAIN_END,
        )

        oos = run_config(
            candidates,
            data,
            OOS_START,
            OOS_END,
        )

        print(
            f"{stop_mult:4.2f} | "
            f"{target_mult:6.2f} | "
            f"{train['trades']:4d} | "
            f"{train['return']:7.2f}% | "
            f"{train['win']:7.2f}% | "
            f"{train['pf']:5.2f} | "
            f"{train['dd']:7.2f}% | "
            f"{oos['trades']:5d} | "
            f"{oos['return']:8.2f}% | "
            f"{oos['win']:8.2f}% | "
            f"{oos['pf']:6.2f} | "
            f"{oos['dd']:7.2f}% | "
            f"{oos['target']:3d} | "
            f"{oos['stop']:3d} | "
            f"{oos['time']:4d}"
        )

        results.append(
            (
                oos["return"],
                oos["pf"],
                oos["dd"],
                stop_mult,
                target_mult,
                train,
                oos,
            )
        )

    print()
    print("=" * 110)
    print("TOP OOS CONFIGS BY RETURN")
    print("=" * 110)

    results.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    for row in results[:5]:
        (
            ret,
            pf,
            dd,
            stop_mult,
            target_mult,
            train,
            oos,
        ) = row

        print(
            f"STOP={stop_mult:.2f} "
            f"TARGET={target_mult:.2f} | "
            f"OOS RETURN={ret:.2f}% | "
            f"PF={pf:.2f} | "
            f"DD={dd:.2f}% | "
            f"TRAIN RETURN={train['return']:.2f}% | "
            f"TRAIN PF={train['pf']:.2f} | "
            f"TRAIN DD={train['dd']:.2f}%"
        )


if __name__ == "__main__":
    main()
