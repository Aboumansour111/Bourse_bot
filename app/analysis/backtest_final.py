import sqlite3
from statistics import mean

DB_PATH = "/opt/bourse-bot/data/bourse.db"

MIN_HISTORY = 200
MAX_HOLD_DAYS = 10

# قابل تنظیم؛ فعلاً هزینه رفت‌وبرگشت را 0.7٪ فرض می‌کنیم.
ROUND_TRIP_COST = 0.007


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values, period):
    if len(values) < period:
        return []

    alpha = 2 / (period + 1)
    value = sum(values[:period]) / period
    result = [None] * (period - 1)
    result.append(value)

    for price in values[period:]:
        value = (price - value) * alpha + value
        result.append(value)

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
    if len(values) < 40:
        return None

    fast = ema_series(values, 12)
    slow = ema_series(values, 26)

    macd = []

    for f, s in zip(fast, slow):
        if f is None or s is None:
            macd.append(None)
        else:
            macd.append(f - s)

    valid = [x for x in macd if x is not None]

    if len(valid) < 9:
        return None

    signal = ema_series(valid, 9)

    if not signal or signal[-1] is None:
        return None

    return valid[-1] - signal[-1]


def atr(highs, lows, closes, period=14):
    if len(closes) <= period:
        return None

    trs = []

    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    value = sum(trs[:period]) / period

    for tr in trs[period:]:
        value = (
            (value * (period - 1)) + tr
        ) / period

    return value


def volume_ratio(volumes, period=20):
    if len(volumes) < period:
        return None

    avg = sum(volumes[-period:]) / period

    if avg <= 0:
        return None

    return volumes[-1] / avg


def technical_signal(closes, highs, lows, volumes):
    if len(closes) < MIN_HISTORY:
        return None

    current = closes[-1]

    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)

    ema20_series = ema_series(closes, 20)
    ema50_series = ema_series(closes, 50)

    ema20 = ema20_series[-1]
    ema50 = ema50_series[-1]

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

    # همان منطق ورود، بدون استفاده از داده آینده
    quality = 0.0

    # Trend / 25
    if trend == 4:
        quality += 25
    elif trend == 3:
        quality += 20
    elif trend == 2:
        quality += 10

    # RSI / 20
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

    # MACD / 20
    if macd_hist is not None:
        if macd_hist > 0:
            quality += 20
        else:
            quality -= 5

    # Volume / 15
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

    # شرایط ورود سخت‌گیرانه
    eligible = (
        trend >= 3
        and macd_hist is not None
        and macd_hist > 0
        and rsi14 is not None
        and rsi14 < 75
        and vol_ratio is not None
        and 1.0 <= vol_ratio <= 5.0
        and quality >= 70
    )

    return {
        "quality": quality,
        "eligible": eligible,
        "trend": trend,
        "rsi": rsi14,
        "macd_hist": macd_hist,
        "atr": atr14,
        "volume_ratio": vol_ratio,
    }


def main():
    conn = sqlite3.connect(DB_PATH)

    symbols = conn.execute("""
        SELECT inscode, symbol
        FROM symbols
        WHERE active = 1
        ORDER BY inscode
    """).fetchall()

    print("Symbols:", len(symbols))
    print("Max holding period:", MAX_HOLD_DAYS)
    print("Round-trip cost:", ROUND_TRIP_COST)
    print()

    all_trades = []

    for symbol_index, (inscode, symbol) in enumerate(
        symbols, 1
    ):
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
            ORDER BY trade_date ASC
        """, (inscode,)).fetchall()

        if len(rows) < MIN_HISTORY + 20:
            continue

        dates = [row[0] for row in rows]
        closes = [float(row[1]) for row in rows]
        highs = [float(row[2]) for row in rows]
        lows = [float(row[3]) for row in rows]
        volumes = [float(row[4] or 0) for row in rows]

        # برای هر تاریخ، breadth بازار را از داده‌های موجود همان تاریخ می‌سازیم.
        for i in range(
            MIN_HISTORY,
            len(rows) - MAX_HOLD_DAYS
        ):
            signal = technical_signal(
                closes[:i + 1],
                highs[:i + 1],
                lows[:i + 1],
                volumes[:i + 1],
            )

            if signal is None or not signal["eligible"]:
                continue

            signal_date = dates[i]

            # فقط همان روز و فقط از داده‌های قبل/همان روز
            market_rows = conn.execute("""
                SELECT
                    inscode,
                    close_price
                FROM daily_prices
                WHERE trade_date <= ?
                  AND close_price IS NOT NULL
                  AND close_price > 0
            """, (signal_date,)).fetchall()

            # این query به تنهایی روز قبل هر نماد را نمی‌دهد،
            # بنابراین breadth را با یک query دقیق‌تر محاسبه می‌کنیم.
            breadth_rows = conn.execute("""
                WITH ranked AS (
                    SELECT
                        inscode,
                        trade_date,
                        close_price,
                        ROW_NUMBER() OVER (
                            PARTITION BY inscode
                            ORDER BY trade_date DESC
                        ) AS rn
                    FROM daily_prices
                    WHERE trade_date <= ?
                      AND close_price IS NOT NULL
                      AND close_price > 0
                )
                SELECT
                    inscode,
                    MAX(
                        CASE
                            WHEN rn = 1
                            THEN close_price
                        END
                    ) AS current_close,
                    MAX(
                        CASE
                            WHEN rn = 2
                            THEN close_price
                        END
                    ) AS previous_close
                FROM ranked
                GROUP BY inscode
            """, (signal_date,)).fetchall()

            positive = 0
            negative = 0
            unchanged = 0

            for item in breadth_rows:
                current = item[1]
                previous = item[2]

                if current is None or previous is None:
                    continue

                if current > previous:
                    positive += 1
                elif current < previous:
                    negative += 1
                else:
                    unchanged += 1

            total = positive + negative + unchanged

            if total == 0:
                continue

            breadth = positive / total

            # در بازار خیلی ضعیف، ورود جدید ممنوع
            if breadth < 0.42:
                continue

            entry = closes[i]
            atr14 = signal["atr"]

            if atr14 is None or atr14 <= 0:
                continue

            stop = entry - (1.5 * atr14)
            target = entry + (2.0 * atr14)

            if stop <= 0:
                continue

            exit_index = i + MAX_HOLD_DAYS
            exit_price = closes[exit_index]
            exit_date = dates[exit_index]
            exit_reason = "TIME"

            # از روز بعد ورود بررسی می‌کنیم.
            for j in range(i + 1, exit_index + 1):
                day_low = lows[j]
                day_high = highs[j]

                hit_stop = day_low <= stop
                hit_target = day_high >= target

                if hit_stop and hit_target:
                    # حالت محافظه‌کارانه:
                    # وقتی ترتیب داخل کندل را نمی‌دانیم،
                    # حد ضرر را مقدم می‌گیریم.
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

            gross_return = (
                (exit_price - entry) / entry
            )

            net_return = gross_return - ROUND_TRIP_COST

            all_trades.append({
                "symbol": symbol,
                "inscode": inscode,
                "entry_date": signal_date,
                "exit_date": exit_date,
                "entry": entry,
                "exit": exit_price,
                "return": net_return * 100,
                "quality": signal["quality"],
                "reason": exit_reason,
                "breadth": breadth,
            })

        if symbol_index % 50 == 0:
            print(
                f"[{symbol_index}/{len(symbols)}] "
                f"trades={len(all_trades)}"
            )

    conn.close()

    if not all_trades:
        print("No trades found.")
        return

    returns = [
        x["return"]
        for x in all_trades
    ]

    winners = [
        x for x in all_trades
        if x["return"] > 0
    ]

    losers = [
        x for x in all_trades
        if x["return"] <= 0
    ]

    win_rate = (
        len(winners)
        / len(all_trades)
        * 100
    )

    average_return = mean(returns)

    avg_win = (
        mean(x["return"] for x in winners)
        if winners else 0
    )

    avg_loss = (
        mean(x["return"] for x in losers)
        if losers else 0
    )

    gross_profit = sum(
        x["return"] for x in winners
    )

    gross_loss = abs(sum(
        x["return"] for x in losers
    ))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    expectancy = (
        (win_rate / 100 * avg_win)
        + ((1 - win_rate / 100) * avg_loss)
    )

    # Equity curve با وزن مساوی هر معامله
    equity = 100.0
    peak = equity
    max_drawdown = 0.0

    for trade in sorted(
        all_trades,
        key=lambda x: x["exit_date"]
    ):
        equity *= (
            1 + trade["return"] / 100
        )

        peak = max(peak, equity)

        drawdown = (
            (equity - peak) / peak
        ) * 100

        max_drawdown = min(
            max_drawdown,
            drawdown
        )

    print()
    print("========== FINAL STRATEGY BACKTEST ==========")
    print("Trades:", len(all_trades))
    print(f"Win rate: {win_rate:.2f}%")
    print(f"Average return: {average_return:.2f}%")
    print(f"Average win: {avg_win:.2f}%")
    print(f"Average loss: {avg_loss:.2f}%")
    print(f"Profit factor: {profit_factor:.2f}")
    print(f"Expectancy/trade: {expectancy:.2f}%")
    print(f"Max drawdown: {max_drawdown:.2f}%")
    print(f"Final equity (100 base): {equity:.2f}")

    print()
    print("Exit reasons:")

    reasons = {}

    for trade in all_trades:
        reasons[trade["reason"]] = (
            reasons.get(trade["reason"], 0) + 1
        )

    for reason, count in sorted(
        reasons.items(),
        key=lambda x: x[1],
        reverse=True
    ):
        print(
            f"{reason}: {count}"
        )

    print()
    print("Best 10:")

    for trade in sorted(
        all_trades,
        key=lambda x: x["return"],
        reverse=True
    )[:10]:
        print(
            f"{trade['symbol']} | "
            f"{trade['entry_date']} → "
            f"{trade['exit_date']} | "
            f"{trade['return']:.2f}% | "
            f"{trade['reason']}"
        )

    print()
    print("Worst 10:")

    for trade in sorted(
        all_trades,
        key=lambda x: x["return"]
    )[:10]:
        print(
            f"{trade['symbol']} | "
            f"{trade['entry_date']} → "
            f"{trade['exit_date']} | "
            f"{trade['return']:.2f}% | "
            f"{trade['reason']}"
        )


if __name__ == "__main__":
    main()
