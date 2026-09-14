import sqlite3
import requests
from datetime import datetime

GATEWAY_URL = "http://127.0.0.1:18080"
DB_PATH = "/opt/bourse-bot/data/bourse.db"


def get_client_type_all():
    response = requests.get(
        f"{GATEWAY_URL}/client-type-all",
        timeout=60,
    )
    response.raise_for_status()

    result = response.json()

    if result.get("status") != "ok":
        raise RuntimeError(result)

    return result["data"]["clientTypeAllDto"]


def main():
    rows = get_client_type_all()

    # تاریخ امروز از خود سیستم
    trade_date = int(datetime.now().strftime("%Y%m%d"))

    conn = sqlite3.connect(DB_PATH)

    sql = """
        INSERT INTO client_type (
            inscode,
            trade_date,
            real_buy_count,
            real_buy_volume,
            real_sell_count,
            real_sell_volume,
            legal_buy_count,
            legal_buy_volume,
            legal_sell_count,
            legal_sell_volume
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(inscode, trade_date)
        DO UPDATE SET
            real_buy_count = excluded.real_buy_count,
            real_buy_volume = excluded.real_buy_volume,
            real_sell_count = excluded.real_sell_count,
            real_sell_volume = excluded.real_sell_volume,
            legal_buy_count = excluded.legal_buy_count,
            legal_buy_volume = excluded.legal_buy_volume,
            legal_sell_count = excluded.legal_sell_count,
            legal_sell_volume = excluded.legal_sell_volume
    """

    records = []

    for row in rows:
        records.append((
            int(row["insCode"]),
            trade_date,
            row.get("buy_CountI", 0),
            row.get("buy_I_Volume", 0),
            row.get("sell_CountI", 0),
            row.get("sell_I_Volume", 0),
            row.get("buy_CountN", 0),
            row.get("buy_N_Volume", 0),
            row.get("sell_CountN", 0),
            row.get("sell_N_Volume", 0),
        ))

    conn.executemany(sql, records)
    conn.commit()

    count = conn.execute(
        "SELECT COUNT(*) FROM client_type WHERE trade_date = ?",
        (trade_date,),
    ).fetchone()[0]

    conn.close()

    print("Downloaded:", len(rows))
    print("Saved for date:", trade_date)
    print("Database rows:", count)


if __name__ == "__main__":
    main()
