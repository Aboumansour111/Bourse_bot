import sqlite3

DB_PATH = "/opt/bourse-bot/data/bourse.db"


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
        value = (price - value) * alpha + value

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
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(values):
    if len(values) < 35:
        return None, None, None

    fast = []
    slow = []

    alpha_fast = 2 / 13
    alpha_slow = 2 / 27

    fast_value = values[0]
    slow_value = values[0]

    for price in values:
        fast_value = (price - fast_value) * alpha_fast + fast_value
        slow_value = (price - slow_value) * alpha_slow + slow_value

        fast.append(fast_value)
        slow.append(slow_value)

    macd_line = [f - s for f, s in zip(fast, slow)]

    signal_value = macd_line[0]
    alpha_signal = 2 / 10

    for value in macd_line:
        signal_value = (value - signal_value) * alpha_signal + signal_value

    histogram = macd_line[-1] - signal_value

    return macd_line[-1], signal_value, histogram


def atr(highs, lows, closes, period=14):
    if len(closes) <= period:
        return None

    true_ranges = []

    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)

    value = sum(true_ranges[:period]) / period

    for tr in true_ranges[period:]:
        value = ((value * (period - 1)) + tr) / period

    return value


def pct_change(current, previous):
    if previous == 0:
        return None
    return ((current - previous) / previous) * 100


def analyze(rows):
    if len(rows) < 200:
        return None

    closes = [
        float(row[2] if row[2] is not None else row[1])
        for row in rows
    ]

    highs = [float(row[3]) for row in rows]
    lows = [float(row[4]) for row in rows]

    volumes = [
        float(row[5]) if row[5] is not None else 0
        for row in rows
    ]

    values = [
        float(row[6]) if row[6] is not None else 0
        for row in rows
    ]

    current = closes[-1]
    previous = closes[-2]

    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    rsi14 = rsi(closes, 14)

    macd_line, macd_signal, macd_hist = macd(closes)

    atr14 = atr(highs, lows, closes, 14)

    volume_avg20 = sma(volumes, 20)
    value_avg20 = sma(values, 20)

    volume_ratio = None
    value_ratio = None

    if volume_avg20 and volume_avg20 > 0:
        volume_ratio = volumes[-1] / volume_avg20

    if value_avg20 and value_avg20 > 0:
        value_ratio = values[-1] / value_avg20

    trend_score = 0

    if sma20 is not None and current > sma20:
        trend_score += 1

    if sma50 is not None and current > sma50:
        trend_score += 1

    if sma200 is not None and current > sma200:
        trend_score += 1

    if ema20 is not None and ema50 is not None and ema20 > ema50:
        trend_score += 1

    momentum_score = 0

    if rsi14 is not None:
        if 50 <= rsi14 <= 70:
            momentum_score += 2
        elif 40 <= rsi14 < 50:
            momentum_score += 1
        elif rsi14 > 80 or rsi14 < 20:
            momentum_score -= 1

    if macd_hist is not None:
        if macd_hist > 0:
            momentum_score += 1
        else:
            momentum_score -= 1

    return {
        "trade_date": int(rows[-1][0]),
        "close": current,
        "previous_close": previous,
        "daily_change_pct": pct_change(current, previous),
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "ema20": ema20,
        "ema50": ema50,
        "rsi14": rsi14,
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "atr14": atr14,
        "volume": volumes[-1],
        "volume_avg20": volume_avg20,
        "volume_ratio": volume_ratio,
        "value": values[-1],
        "value_avg20": value_avg20,
        "value_ratio": value_ratio,
        "trend_score": trend_score,
        "momentum_score": momentum_score,
    }


def main():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS technical_analysis (
            inscode INTEGER PRIMARY KEY,
            trade_date INTEGER NOT NULL,
            close REAL,
            previous_close REAL,
            daily_change_pct REAL,
            sma20 REAL,
            sma50 REAL,
            sma200 REAL,
            ema20 REAL,
            ema50 REAL,
            rsi14 REAL,
            macd REAL,
            macd_signal REAL,
            macd_hist REAL,
            atr14 REAL,
            volume REAL,
            volume_avg20 REAL,
            volume_ratio REAL,
            value REAL,
            value_avg20 REAL,
            value_ratio REAL,
            trend_score INTEGER,
            momentum_score INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    symbols = conn.execute("""
        SELECT inscode, symbol
        FROM symbols
        WHERE active = 1
        ORDER BY symbol
    """).fetchall()

    sql = """
        INSERT INTO technical_analysis (
            inscode,
            trade_date,
            close,
            previous_close,
            daily_change_pct,
            sma20,
            sma50,
            sma200,
            ema20,
            ema50,
            rsi14,
            macd,
            macd_signal,
            macd_hist,
            atr14,
            volume,
            volume_avg20,
            volume_ratio,
            value,
            value_avg20,
            value_ratio,
            trend_score,
            momentum_score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(inscode)
        DO UPDATE SET
            trade_date = excluded.trade_date,
            close = excluded.close,
            previous_close = excluded.previous_close,
            daily_change_pct = excluded.daily_change_pct,
            sma20 = excluded.sma20,
            sma50 = excluded.sma50,
            sma200 = excluded.sma200,
            ema20 = excluded.ema20,
            ema50 = excluded.ema50,
            rsi14 = excluded.rsi14,
            macd = excluded.macd,
            macd_signal = excluded.macd_signal,
            macd_hist = excluded.macd_hist,
            atr14 = excluded.atr14,
            volume = excluded.volume,
            volume_avg20 = excluded.volume_avg20,
            volume_ratio = excluded.volume_ratio,
            value = excluded.value,
            value_avg20 = excluded.value_avg20,
            value_ratio = excluded.value_ratio,
            trend_score = excluded.trend_score,
            momentum_score = excluded.momentum_score,
            updated_at = CURRENT_TIMESTAMP
    """

    success = 0
    skipped = 0
    errors = 0

    total = len(symbols)

    for index, (inscode, symbol) in enumerate(symbols, 1):
        try:
            rows = conn.execute("""
                SELECT
                    trade_date,
                    last_price,
                    close_price,
                    high_price,
                    low_price,
                    volume,
                    value
                FROM daily_prices
                WHERE inscode = ?
                ORDER BY trade_date ASC
            """, (inscode,)).fetchall()

            result = analyze(rows)

            if result is None:
                skipped += 1
                continue

            conn.execute(sql, (
                inscode,
                result["trade_date"],
                result["close"],
                result["previous_close"],
                result["daily_change_pct"],
                result["sma20"],
                result["sma50"],
                result["sma200"],
                result["ema20"],
                result["ema50"],
                result["rsi14"],
                result["macd"],
                result["macd_signal"],
                result["macd_hist"],
                result["atr14"],
                result["volume"],
                result["volume_avg20"],
                result["volume_ratio"],
                result["value"],
                result["value_avg20"],
                result["value_ratio"],
                result["trend_score"],
                result["momentum_score"],
            ))

            success += 1

            if index % 50 == 0 or index == total:
                print(
                    f"[{index}/{total}] "
                    f"success={success} skipped={skipped} errors={errors}"
                )

        except Exception as exc:
            errors += 1
            print(f"[{index}/{total}] {symbol or '-'} ERROR: {exc}")

    conn.commit()
    conn.close()

    print()
    print("Technical analysis complete")
    print("Success:", success)
    print("Skipped:", skipped)
    print("Errors:", errors)


if __name__ == "__main__":
    main()
