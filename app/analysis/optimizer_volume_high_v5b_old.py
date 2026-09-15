import sqlite3
from collections import defaultdict
from statistics import mean

DB_PATH = "/opt/bourse-bot/data/bourse.db"

MIN_HISTORY = 0
MAX_HOLD_DAYS = 10
ROUND_TRIP_COST = 0.007
ENTRY_FEE = ROUND_TRIP_COST / 2
EXIT_FEE = ROUND_TRIP_COST / 2

INITIAL_CAPITAL = 100_000_000.0
RISK_PER_TRADE = 0.01
MAX_POSITION_WEIGHT = 0.20
MAX_CONCURRENT_POSITIONS = 5

BREADTH_THRESHOLD = 0.42
VOLUME_LOW = 1.2
VOLUME_POOL_HIGH = 5.0

TRAIN_START = "2025-01-01"
TRAIN_END = "2026-03-31"
OOS_START = "2026-04-01"
OOS_END = "2026-09-15"

VOLUME_HIGH_VALUES = [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values, period):
    if len(values) < period:
        return []

    multiplier = 2 / (period + 1)
    ema_value = sum(values[:period]) / period
    result = [ema_value]

    for price in values[period:]:
        ema_value = (price - ema_value) * multiplier + ema_value
        result.append(ema_value)

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd_histogram(values):
    ema12 = ema_series(values, 12)
    ema26 = ema_series(values, 26)

    if not ema12 or not ema26:
        return None

    start = 26 - 12
    ema12_aligned = ema12[start:]

    if len(ema12_aligned) != len(ema26):
        return None

    macd = [a - b for a, b in zip(ema12_aligned, ema26)]

    signal = ema_series(macd, 9)

    if not signal:
        return None

    return macd[-1] - signal[-1]


def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None

    trs = []

    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    if len(trs) < period:
        return None

    return sum(trs[-period:]) / period


def volume_ratio(volumes, period=20):
    if len(volumes) < period + 1:
        return None

    previous = volumes[-period - 1:-1]

    if not previous:
        return None

    avg_volume = sum(previous) / len(previous)

    if avg_volume <= 0:
        return None

    return volumes[-1] / avg_volume


def technical_signal(closes, highs, lows, volumes):
    if len(closes) < MIN_HISTORY:
        return None

    current = closes[-1]

    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)

    ema20_values = ema_series(closes, 20)
    ema50_values = ema_series(closes, 50)

    if not ema20_values or not ema50_values:
        return None

    ema20 = ema20_values[-1]
    ema50 = ema50_values[-1]

    rsi14 = rsi(closes, 14)
    macd_hist = macd_histogram(closes)
    atr14 = atr(highs, lows, closes, 14)
    vol_ratio = volume_ratio(volumes, 20)

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

    eligible_base = (
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

    return {
        "quality": quality,
        "eligible_base": eligible_base,
        "trend": trend,
        "rsi": rsi14,
        "macd_hist": macd_hist,
        "atr": atr14,
        "volume_ratio": vol_ratio,
    }


def load_data():
    conn = sqlite3.connect(DB_PATH)

    rows = conn.execute("""
        SELECT
            s.symbol,
            dp.trade_date,
            dp.first_price,
            dp.close_price,
            dp.high_price,
            dp.low_price,
            dp.volume
        FROM daily_prices dp
        JOIN symbols s ON s.inscode = dp.inscode
        WHERE dp.close_price IS NOT NULL
        ORDER BY s.symbol, dp.trade_date
    """).fetchall()

    conn.close()

    data = defaultdict(list)

    for symbol, date, first_price, close_price, high, low, volume in rows:
        data[symbol].append({
            "date": str(date),
            "open": float(first_price) if first_price is not None else float(close_price),
            "close": float(close_price),
            "high": float(high) if high is not None else float(close_price),
            "low": float(low) if low is not None else float(close_price),
            "volume": float(volume or 0),
        })

    return data

def load_breadth():
    conn = sqlite3.connect(DB_PATH)

    rows = conn.execute("""
        SELECT
            trade_date,
            SUM(CASE
                WHEN first_price IS NOT NULL
                 AND yesterday_price IS NOT NULL
                 AND first_price > yesterday_price
                THEN 1 ELSE 0 END) AS positive,
            SUM(CASE
                WHEN first_price IS NOT NULL
                 AND yesterday_price IS NOT NULL
                 AND first_price < yesterday_price
                THEN 1 ELSE 0 END) AS negative,
            COUNT(*) AS total
        FROM daily_prices
        WHERE close_price IS NOT NULL
        GROUP BY trade_date
        ORDER BY trade_date
    """).fetchall()

    conn.close()

    breadth = {}

    for date, positive, negative, total in rows:
        denominator = positive + negative

        if denominator > 0:
            breadth[str(date)] = positive / denominator

    return breadth

def generate_candidate_pool(data, breadth):
    candidates = []

    symbols = sorted(data.keys())

    print("Generating candidate pool...")

    for idx, symbol in enumerate(symbols, 1):
        rows = data[symbol]

        if idx % 50 == 0 or idx == len(symbols):
            print(f"Candidates [{idx}/{len(symbols)}]")

        for i in range(1, len(rows) - 1):
            current = rows[i]
            signal_date = current["date"]

            if signal_date < TRAIN_START:
                continue

            if signal_date > OOS_END:
                break

            closes = [x["close"] for x in rows[:i + 1]]
            highs = [x["high"] for x in rows[:i + 1]]
            lows = [x["low"] for x in rows[:i + 1]]
            volumes = [x["volume"] for x in rows[:i + 1]]

            signal = technical_signal(closes, highs, lows, volumes)

            if not signal or not signal["eligible_base"]:
                continue

            market_breadth = breadth.get(signal_date)

            if market_breadth is None:
                continue

            if market_breadth < BREADTH_THRESHOLD:
                continue

            entry = rows[i + 1]

            entry_price = entry["open"] if "open" in entry else entry["close"]

            if entry_price <= 0:
                continue

            atr_value = signal["atr"]

            stop = entry_price - 1.5 * atr_value
            target = entry_price + 3.0 * atr_value

            if stop <= 0:
                continue

            exit_price = None
            exit_date = None
            exit_reason = None

            last_index = min(i + 1 + MAX_HOLD_DAYS, len(rows) - 1)

            for j in range(i + 1, last_index + 1):
                day = rows[j]

                if day["low"] <= stop:
                    exit_price = stop
                    exit_date = day["date"]
                    exit_reason = "STOP"
                    break

                if day["high"] >= target:
                    exit_price = target
                    exit_date = day["date"]
                    exit_reason = "TARGET"
                    break

            if exit_price is None:
                day = rows[last_index]
                exit_price = day["close"]
                exit_date = day["date"]
                exit_reason = "TIME"

            gross = (exit_price - entry_price) / entry_price
            net = gross - ROUND_TRIP_COST

            candidates.append({
                "symbol": symbol,
                "signal_date": signal_date,
                "entry_date": entry["date"],
                "entry_price": entry_price,
                "exit_date": exit_date,
                "exit_price": exit_price,
                "return": net,
                "quality": signal["quality"],
                "breadth": market_breadth,
                "volume_ratio": signal["volume_ratio"],
                "exit_reason": exit_reason,
                "atr": atr_value,
            })

    return candidates


def simulate(candidates, start_date, end_date):
    candidates = [
        c for c in candidates
        if start_date <= c["entry_date"] <= end_date
        and start_date <= c["exit_date"] <= end_date
    ]

    by_date = defaultdict(list)

    for c in candidates:
        by_date[c["entry_date"]].append(c)

    capital = INITIAL_CAPITAL
    cash = capital
    positions = []
    equity_curve = []

    all_dates = sorted(
        set(
            [c["entry_date"] for c in candidates]
            + [c["exit_date"] for c in candidates]
        )
    )

    trades = []

    for date in all_dates:
        still_open = []

        for pos in positions:
            if pos["exit_date"] <= date:
                proceeds = (
                    pos["shares"]
                    * pos["exit_price"]
                    * (1 - EXIT_FEE)
                )

                cash += proceeds
                trades.append(pos)
            else:
                still_open.append(pos)

        positions = still_open

        available_slots = MAX_CONCURRENT_POSITIONS - len(positions)

        if available_slots > 0:
            day_candidates = sorted(
                by_date.get(date, []),
                key=lambda x: (-x["quality"], -x["breadth"])
            )

            for c in day_candidates[:available_slots]:
                equity = cash + sum(
                    p["shares"] * p["entry_price"]
                    for p in positions
                )

                risk_per_share = max(
                    c["entry_price"] - (c["entry_price"] - 1.5 * c["atr"]),
                    0.01
                )

                risk_amount = equity * RISK_PER_TRADE

                shares_by_risk = risk_amount / risk_per_share

                max_position_value = equity * MAX_POSITION_WEIGHT
                shares_by_weight = max_position_value / c["entry_price"]

                shares = min(
                    shares_by_risk,
                    shares_by_weight
                )

                if shares <= 0:
                    continue

                cost = (
                    shares
                    * c["entry_price"]
                    * (1 + ENTRY_FEE)
                )

                if cost > cash:
                    shares = cash / (
                        c["entry_price"] * (1 + ENTRY_FEE)
                    )
                    cost = (
                        shares
                        * c["entry_price"]
                        * (1 + ENTRY_FEE)
                    )

                if shares <= 0:
                    continue

                cash -= cost

                positions.append({
                    **c,
                    "shares": shares,
                    "cost": cost,
                })

        equity = cash + sum(
            p["shares"] * p["entry_price"]
            for p in positions
        )

        equity_curve.append(equity)

    for pos in positions:
        proceeds = (
            pos["shares"]
            * pos["exit_price"]
            * (1 - EXIT_FEE)
        )

        cash += proceeds
        trades.append(pos)

    final_capital = cash

    if not trades:
        return {
            "trades": 0,
            "return": 0.0,
            "win_rate": 0.0,
            "avg_return": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "max_dd": 0.0,
            "target": 0,
            "stop": 0,
            "time": 0,
            "final": final_capital,
        }

    returns = [t["return"] for t in trades]

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    if gross_loss > 0:
        pf = gross_profit / gross_loss
    else:
        pf = float("inf")

    peak = INITIAL_CAPITAL
    max_dd = 0.0

    for equity in equity_curve:
        peak = max(peak, equity)
        dd = (equity - peak) / peak
        max_dd = min(max_dd, dd)

    return {
        "trades": len(trades),
        "return": final_capital / INITIAL_CAPITAL - 1,
        "win_rate": len(wins) / len(returns),
        "avg_return": mean(returns),
        "avg_win": mean(wins) if wins else 0,
        "avg_loss": mean(losses) if losses else 0,
        "profit_factor": pf,
        "expectancy": mean(returns),
        "max_dd": max_dd,
        "target": sum(1 for t in trades if t["exit_reason"] == "TARGET"),
        "stop": sum(1 for t in trades if t["exit_reason"] == "STOP"),
        "time": sum(1 for t in trades if t["exit_reason"] == "TIME"),
        "final": final_capital,
    }


def main():
    print("Loading data...")
    data = load_data()

    print(f"Valid symbols: {len(data)}")

    print("Loading historical market breadth...")
    breadth = load_breadth()

    print(f"Breadth dates: {len(breadth)}")

    print()
    print("=" * 90)
    print("BUILDING CANDIDATE POOL WITH VOLUME <= 5.0")
    print("=" * 90)

    pool = generate_candidate_pool(data, breadth)

    print()
    print(f"Candidate pool: {len(pool)}")

    print()
    print("=" * 90)
    print("VOLUME UPPER-BOUND SWEEP")
    print("=" * 90)

    results = []

    for high in VOLUME_HIGH_VALUES:
        filtered = [
            c for c in pool
            if VOLUME_LOW <= c["volume_ratio"] <= high
        ]

        train = simulate(
            filtered,
            TRAIN_START,
            TRAIN_END
        )

        oos = simulate(
            filtered,
            OOS_START,
            OOS_END
        )

        results.append((high, train, oos))

        print()
        print(f"===== VOLUME HIGH = {high:.1f} =====")

        print(
            f"Candidates: {len(filtered)}"
        )

        print(
            "TRAIN | "
            f"Trades={train['trades']} | "
            f"Return={train['return']*100:.2f}% | "
            f"Win={train['win_rate']*100:.2f}% | "
            f"PF={train['profit_factor']:.2f} | "
            f"Exp={train['expectancy']*100:.2f}% | "
            f"DD={train['max_dd']*100:.2f}%"
        )

        print(
            "OOS   | "
            f"Trades={oos['trades']} | "
            f"Return={oos['return']*100:.2f}% | "
            f"Win={oos['win_rate']*100:.2f}% | "
            f"PF={oos['profit_factor']:.2f} | "
            f"Exp={oos['expectancy']*100:.2f}% | "
            f"DD={oos['max_dd']*100:.2f}%"
        )

    print()
    print("=" * 90)
    print("SUMMARY")
    print("=" * 90)

    print(
        "HIGH | "
        "TRAIN_RET | TRAIN_PF | TRAIN_DD | "
        "OOS_RET | OOS_PF | OOS_DD"
    )

    for high, train, oos in results:
        print(
            f"{high:>4.1f} | "
            f"{train['return']*100:>9.2f}% | "
            f"{train['profit_factor']:>8.2f} | "
            f"{train['max_dd']*100:>8.2f}% | "
            f"{oos['return']*100:>7.2f}% | "
            f"{oos['profit_factor']:>6.2f} | "
            f"{oos['max_dd']*100:>7.2f}%"
        )


if __name__ == "__main__":
    main()
