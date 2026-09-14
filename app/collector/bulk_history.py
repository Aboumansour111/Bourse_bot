import sqlite3
import time
import requests

GATEWAY_URL = "http://127.0.0.1:18080"
DB_PATH = "/opt/bourse-bot/data/bourse.db"
TOP = 400

session = requests.Session()
session.headers.update({
    "User-Agent": "bourse-bot/1.0",
    "Accept": "application/json",
})


def get_history(inscode):
    response = session.get(
        f"{GATEWAY_URL}/history/{inscode}/{TOP}",
        timeout=45,
    )
    response.raise_for_status()

    result = response.json()

    if result.get("status") != "ok":
        raise RuntimeError(result)

    return result["data"]["closingPriceDaily"]


def save_rows(inscode, rows):
    conn = sqlite3.connect(DB_PATH)

    sql = """
        INSERT INTO daily_prices (
            inscode,
            trade_date,
            last_price,
            close_price,
            yesterday_price,
            first_price,
            high_price,
            low_price,
            volume,
            value,
            trades_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(inscode, trade_date)
        DO UPDATE SET
            last_price = excluded.last_price,
            close_price = excluded.close_price,
            yesterday_price = excluded.yesterday_price,
            first_price = excluded.first_price,
            high_price = excluded.high_price,
            low_price = excluded.low_price,
            volume = excluded.volume,
            value = excluded.value,
            trades_count = excluded.trades_count
    """

    records = []

    for row in rows:
        records.append((
            int(inscode),
            int(row["dEven"]),
            row.get("pDrCotVal"),
            row.get("pClosing"),
            row.get("priceYesterday"),
            row.get("priceFirst"),
            row.get("priceMax"),
            row.get("priceMin"),
            row.get("qTotTran5J"),
            row.get("qTotCap"),
            row.get("zTotTran"),
        ))

    conn.executemany(sql, records)
    conn.commit()
    conn.close()

    return len(records)


def already_has_history(inscode):
    conn = sqlite3.connect(DB_PATH)

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM daily_prices
        WHERE inscode = ?
        """,
        (inscode,),
    ).fetchone()[0]

    conn.close()

    return count >= TOP


def main():
    conn = sqlite3.connect(DB_PATH)

    symbols = conn.execute(
        """
        SELECT inscode, symbol
        FROM symbols
        WHERE active = 1
        ORDER BY inscode
        """
    ).fetchall()

    conn.close()

    total = len(symbols)

    print("Active symbols:", total)
    print("Target history:", TOP)
    print()

    success = 0
    skipped = 0
    errors = 0

    for index, (inscode, symbol) in enumerate(symbols, start=1):

        if already_has_history(inscode):
            skipped += 1
            continue

        try:
            rows = get_history(inscode)
            saved = save_rows(inscode, rows)

            success += 1

            print(
                f"[{index}/{total}] "
                f"{symbol or '-'} → {saved} rows"
            )

        except Exception as exc:
            errors += 1

            print(
                f"[{index}/{total}] "
                f"{symbol or '-'} → ERROR: {exc}"
            )

        time.sleep(0.15)

    print()
    print("Finished")
    print("Downloaded:", success)
    print("Skipped:", skipped)
    print("Errors:", errors)


if __name__ == "__main__":
    main()
