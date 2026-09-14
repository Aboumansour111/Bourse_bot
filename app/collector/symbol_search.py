import sqlite3
import requests
from urllib.parse import quote

GATEWAY_URL = "http://127.0.0.1:18080"
DB_PATH = "/opt/bourse-bot/data/bourse.db"


def search_symbols(query: str):
    encoded_query = quote(query, safe="")

    response = requests.get(
        f"{GATEWAY_URL}/search/{encoded_query}",
        timeout=20,
    )
    response.raise_for_status()

    result = response.json()

    if result.get("status") != "ok":
        raise RuntimeError(result)

    return result["data"]["instrumentSearch"]


def save_symbols(rows):
    conn = sqlite3.connect(DB_PATH)

    sql = """
        INSERT INTO symbols (
            inscode,
            symbol,
            name,
            market,
            active
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(inscode)
        DO UPDATE SET
            symbol = excluded.symbol,
            name = excluded.name,
            market = excluded.market,
            active = excluded.active,
            updated_at = CURRENT_TIMESTAMP
    """

    records = []

    for row in rows:
        records.append((
            int(row["insCode"]),
            row.get("lVal18AFC"),
            row.get("lVal30"),
            str(row.get("flow")) if row.get("flow") is not None else None,
            1,
        ))

    conn.executemany(sql, records)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    query = "فولاد"

    results = search_symbols(query)

    print(f"Found {len(results)} result(s).")

    for row in results:
        print(
            row.get("lVal18AFC"),
            "|",
            row.get("lVal30"),
            "|",
            row.get("insCode"),
            "| flow:",
            row.get("flow"),
        )

    save_symbols(results)

    print("Symbols saved successfully.")
