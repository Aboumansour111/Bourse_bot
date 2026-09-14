import sqlite3
from statistics import mean

DB_PATH = "/opt/bourse-bot/data/bourse.db"

HOLD_DAYS = 5
MIN_HISTORY = 200

START_SCORE = 75


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema(values, period):
    if len(values) < period:
        return None

    value = sum(values[:period]) / period
    alpha = 2 / (period + 1)

    for price in values[period:]:
        value = (
            price - value
        ) * alpha + value

    return value


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
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def macd_histogram(values):
    if len(values) < 35:
        return None

    fast = ema(values, 12)
    slow = ema(values, 26)

    if fast is None or slow is None:
        return None

    # برای بک‌تست دقیق‌تر یک MACD سری‌ای می‌سازیم.
    fast_series = []
    slow_series = []

    alpha_fast = 2 / 13
    alpha_slow = 2 / 27

    fast_value = values[0]
    slow_value = values[0]

    for price in values:
        fast_value = (
            price - fast_value
        ) * alpha_fast + fast_value

        slow_value = (
            price - slow_value
        ) * alpha_slow + slow_value

        fast_series.append(fast_value)
        slow_series.append(slow_value)

    macd = [
        f - s
        for f, s in zip(
            fast_series,
            slow_series
        )
    ]

    if len(macd) < 10:
        return None

    signal = ema(macd, 9)

    if signal is None:
        return None

    return macd[-1] - signal


def signal_score(closes, volumes):
    if len(closes) < MIN_HISTORY:
        return None

    current = closes[-1]

    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    rsi14 = rsi(closes, 14)
    macd_hist = macd_histogram(closes)

    volume_avg20 = sma(volumes, 20)

    trend = 0

    if sma20 and current > sma20:
        trend += 1

    if sma50 and current > sma50:
        trend += 1

    if sma200 and current > sma200:
        trend += 1

    if ema20 and ema50 and ema20 > ema50:
        trend += 1

    score = (trend / 4) * 40

    # RSI
    if rsi14 is not None:
        if 50 <= rsi14 <= 68:
            score += 25
        elif 45 <= rsi14 < 50:
            score += 15
        elif 68 < rsi14 <= 72:
            score += 12
        elif rsi14 > 75:
            score -= 5
        else:
            score += 5

    # MACD
    if macd_hist is not None:
        if macd_hist > 0:
            score += 20
        else:
            score -= 5

    # Volume
    if volume_avg20 and volume_avg20 > 0:
        ratio = volumes[-1] / volume_avg20

        if 1.2 <= ratio <= 4:
            score += 15
        elif 1 <= ratio < 1.2:
            score += 10
        elif 0.7 <= ratio < 1:
            score += 5
        elif ratio > 7:
            score -= 5

    return score


def main():
    conn = sqlite3.connect(DB_PATH)

    symbols = conn.execute("""
        SELECT inscode, symbol
        FROM symbols
        WHERE active = 1
        ORDER BY inscode
    """).fetchall()

    print("Symbols:", len(symbols))
    print("Hold period:", HOLD_DAYS, "sessions")
    print()

    trades = []
    symbol_results = {}

    for symbol_index, (inscode, symbol) in enumerate(
        symbols, 1
    ):
        rows = conn.execute("""
            SELECT
                trade_date,
                close_price,
                volume
            FROM daily_prices
            WHERE inscode = ?
              AND close_price IS NOT NULL
              AND close_price > 0
            ORDER BY trade_date ASC
        """, (inscode,)).fetchall()

        if len(rows) < MIN_HISTORY + HOLD_DAYS:
            continue

        closes = [float(row[1]) for row in rows]
        volumes = [
            float(row[2] or 0)
            for row in rows
        ]
        dates = [row[0] for row in rows]

        symbol_trades = 0

        # فقط تا جایی که HOLD_DAYS آینده موجود است
        last_test_index = (
            len(rows) - HOLD_DAYS
        )

        for i in range(
            MIN_HISTORY,
            last_test_index
        ):
            history_closes = closes[:i + 1]
            history_volumes = volumes[:i + 1]

            score = signal_score(
                history_closes,
                history_volumes,
            )

            if score is None or score < START_SCORE:
                continue

            entry = closes[i]
            exit_price = closes[i + HOLD_DAYS]

            if entry <= 0:
                continue

            ret = (
                (exit_price - entry)
                / entry
            ) * 100

            trades.append({
                "symbol": symbol,
                "inscode": inscode,
                "entry_date": dates[i],
                "exit_date": dates[i + HOLD_DAYS],
                "entry": entry,
                "exit": exit_price,
                "return": ret,
                "score": score,
            })

            symbol_trades += 1

        if symbol_trades:
            symbol_results[symbol] = symbol_trades

        if symbol_index % 50 == 0:
            print(
                f"[{symbol_index}/{len(symbols)}] "
                f"trades={len(trades)}"
            )

    conn.close()

    total = len(trades)

    if total == 0:
        print()
        print("No historical signals found.")
        return

    returns = [
        trade["return"]
        for trade in trades
    ]

    winners = [
        value
        for value in returns
        if value > 0
    ]

    losers = [
        value
        for value in returns
        if value <= 0
    ]

    win_rate = len(winners) / total * 100
    average_return = mean(returns)

    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    print()
    print("========== BACKTEST ==========")
    print("Signals:", total)
    print("Winners:", len(winners))
    print("Losers:", len(losers))
    print(f"Win rate: {win_rate:.2f}%")
    print(f"Average return: {average_return:.2f}%")
    print(f"Profit factor: {profit_factor:.2f}")

    print()
    print("Best 10")

    best = sorted(
        trades,
        key=lambda x: x["return"],
        reverse=True
    )

    for trade in best[:10]:
        print(
            f"{trade['symbol']} | "
            f"{trade['entry_date']} → "
            f"{trade['exit_date']} | "
            f"{trade['return']:.2f}% | "
            f"score={trade['score']:.1f}"
        )

    print()
    print("Worst 10")

    worst = sorted(
        trades,
        key=lambda x: x["return"]
    )

    for trade in worst[:10]:
        print(
            f"{trade['symbol']} | "
            f"{trade['entry_date']} → "
            f"{trade['exit_date']} | "
            f"{trade['return']:.2f}% | "
            f"score={trade['score']:.1f}"
        )


if __name__ == "__main__":
    main()
