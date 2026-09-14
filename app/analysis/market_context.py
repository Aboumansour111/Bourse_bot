import sqlite3

DB_PATH = "/opt/bourse-bot/data/bourse.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # آخرین تاریخ مشترک/موجود در دیتای روزانه
    latest_date_row = conn.execute("""
        SELECT MAX(trade_date)
        FROM daily_prices
        WHERE close_price IS NOT NULL
          AND close_price > 0
    """).fetchone()

    latest_date = latest_date_row[0]

    if latest_date is None:
        conn.close()
        raise RuntimeError("No daily price data found")

    # دو روز آخر هر نماد
    rows = conn.execute("""
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
            WHERE close_price IS NOT NULL
              AND close_price > 0
        )
        SELECT
            inscode,
            MAX(CASE WHEN rn = 1 THEN trade_date END) AS latest_trade_date,
            MAX(CASE WHEN rn = 1 THEN close_price END) AS latest_close,
            MAX(CASE WHEN rn = 2 THEN close_price END) AS previous_close
        FROM ranked
        GROUP BY inscode
    """).fetchall()

    total = 0
    positive = 0
    negative = 0
    unchanged = 0
    changes = []

    for row in rows:
        latest_close = row["latest_close"]
        previous_close = row["previous_close"]

        if latest_close is None or previous_close is None:
            continue

        if previous_close <= 0:
            continue

        total += 1

        change_pct = (
            (latest_close - previous_close)
            / previous_close
        ) * 100

        changes.append(change_pct)

        if change_pct > 0:
            positive += 1
        elif change_pct < 0:
            negative += 1
        else:
            unchanged += 1

    if total == 0:
        conn.close()
        raise RuntimeError("No comparable daily prices found")

    average_change = sum(changes) / len(changes)
    breadth = positive / total

    if breadth >= 0.65:
        market_state = "BULLISH"
    elif breadth >= 0.52:
        market_state = "POSITIVE"
    elif breadth >= 0.42:
        market_state = "NEUTRAL"
    elif breadth >= 0.30:
        market_state = "NEGATIVE"
    else:
        market_state = "BEARISH"

    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_context (
            trade_date INTEGER PRIMARY KEY,
            total_shares INTEGER,
            positive INTEGER,
            negative INTEGER,
            unchanged INTEGER,
            average_change_pct REAL,
            breadth REAL,
            total_volume REAL,
            total_value REAL,
            market_state TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # حجم و ارزش همان روز
    totals = conn.execute("""
        SELECT
            COALESCE(SUM(volume), 0),
            COALESCE(SUM(value), 0)
        FROM daily_prices
        WHERE trade_date = ?
    """, (latest_date,)).fetchone()

    total_volume = float(totals[0] or 0)
    total_value = float(totals[1] or 0)

    conn.execute("""
        INSERT INTO market_context (
            trade_date,
            total_shares,
            positive,
            negative,
            unchanged,
            average_change_pct,
            breadth,
            total_volume,
            total_value,
            market_state
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date)
        DO UPDATE SET
            total_shares = excluded.total_shares,
            positive = excluded.positive,
            negative = excluded.negative,
            unchanged = excluded.unchanged,
            average_change_pct = excluded.average_change_pct,
            breadth = excluded.breadth,
            total_volume = excluded.total_volume,
            total_value = excluded.total_value,
            market_state = excluded.market_state,
            updated_at = CURRENT_TIMESTAMP
    """, (
        latest_date,
        total,
        positive,
        negative,
        unchanged,
        average_change,
        breadth,
        total_volume,
        total_value,
        market_state,
    ))

    conn.commit()
    conn.close()

    print("Market context updated")
    print("Trade date:", latest_date)
    print("Shares:", total)
    print("Positive:", positive)
    print("Negative:", negative)
    print("Unchanged:", unchanged)
    print("Average change:", round(average_change, 2))
    print("Breadth:", round(breadth, 4))
    print("Market state:", market_state)


if __name__ == "__main__":
    main()
