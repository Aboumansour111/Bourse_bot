import sqlite3
import time

import requests

GATEWAY_URL = "http://127.0.0.1:18080"
DB_PATH = "/opt/bourse-bot/data/bourse.db"

REQUEST_TIMEOUT = 20
SLEEP_BETWEEN_REQUESTS = 0.05


def get_quote(session, inscode: int):
    response = session.get(
        f"{GATEWAY_URL}/quote/{inscode}",
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    result = response.json()

    if result.get("status") != "ok":
        raise RuntimeError(result)

    return result["data"]


def save_daily_price(conn, inscode: int, data: dict):
    trade_date = int(data["dEven"])

    conn.execute(
        """
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
        """,
        (
            inscode,
            trade_date,
            data.get("pDrCotVal"),
            data.get("pClosing"),
            data.get("priceYesterday"),
            data.get("priceFirst"),
            data.get("priceMax"),
            data.get("priceMin"),
            data.get("qTotTran5J"),
            data.get("qTotCap"),
            data.get("zTotTran"),
        ),
    )


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    symbols = conn.execute(
        """
        SELECT inscode, symbol
        FROM symbols
        WHERE active = 1
        ORDER BY symbol
        """
    ).fetchall()

    total = len(symbols)
    success = 0
    errors = 0

    if total == 0:
        conn.close()
        raise RuntimeError("No active symbols found")

    print(f"Updating daily prices for {total} symbols...")

    session = requests.Session()

    for index, row in enumerate(symbols, 1):
        inscode = row["inscode"]
        symbol = row["symbol"] or "-"

        try:
            data = get_quote(session, inscode)

            if not data.get("dEven"):
                raise RuntimeError("Gateway returned no trade date")

            save_daily_price(conn, inscode, data)

            success += 1

            if index % 50 == 0 or index == total:
                print(
                    f"[{index}/{total}] "
                    f"success={success} errors={errors}"
                )

        except Exception as exc:
            errors += 1
            print(
                f"[{index}/{total}] "
                f"{symbol} ({inscode}) ERROR: {exc}"
            )

        if SLEEP_BETWEEN_REQUESTS > 0:
            time.sleep(SLEEP_BETWEEN_REQUESTS)

    conn.commit()
    conn.close()
    session.close()

    print()
    print("Daily price update complete")
    print("Total:", total)
    print("Success:", success)
    print("Errors:", errors)


if __name__ == "__main__":
    main()
