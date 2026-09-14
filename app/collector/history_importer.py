import sqlite3
import requests

GATEWAY_URL = "http://127.0.0.1:18080"
DB_PATH = "/opt/bourse-bot/data/bourse.db"


def get_history(inscode: int):
    response = requests.get(
        f"{GATEWAY_URL}/history/{inscode}",
        timeout=30,
    )
    response.raise_for_status()

    result = response.json()

    if result.get("status") != "ok":
        raise RuntimeError(result)

    return result["data"]["closingPriceDaily"]


def save_history(inscode: int, rows: list[dict]):
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
            inscode,
            int(row["dEven"]),
            row.get("pDrCotVal"),
            row.get("pClosing"),
            row.get("priceYesterday"),
            row.get("priceFirst"),
            row.get("priceMax"),
            row.get("priceMin"),
            row.get("qTotTran5J"),
            row.get("qTotCap"),
            int(row["zTotTran"]) if row.get("zTotTran") is not None else None,
        ))

    conn.executemany(sql, records)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    INSCODE = 46348559193224090

    rows = get_history(INSCODE)
    save_history(INSCODE, rows)

    print(f"Imported/updated {len(rows)} historical records.")
