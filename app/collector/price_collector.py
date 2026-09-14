import sqlite3
from datetime import datetime

import requests

GATEWAY_URL = "http://127.0.0.1:18080"
DB_PATH = "/opt/bourse-bot/data/bourse.db"


def get_quote(inscode: int):
    response = requests.get(
        f"{GATEWAY_URL}/quote/{inscode}",
        timeout=20,
    )
    response.raise_for_status()

    result = response.json()

    if result.get("status") != "ok":
        raise RuntimeError(result)

    return result["data"]


def save_daily_price(inscode: int, data: dict):
    trade_date = int(data["dEven"])

    conn = sqlite3.connect(DB_PATH)

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

    conn.commit()
    conn.close()


if __name__ == "__main__":
    INSCODE = 46348559193224090

    quote = get_quote(INSCODE)
    save_daily_price(INSCODE, quote)

    print("Price saved successfully.")
    print("Inscode:", INSCODE)
    print("Trade date:", quote.get("dEven"))
    print("Last price:", quote.get("pDrCotVal"))
    print("Close price:", quote.get("pClosing"))
