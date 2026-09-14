import sqlite3
import requests

GATEWAY_URL = "http://127.0.0.1:18080"
DB_PATH = "/opt/bourse-bot/data/bourse.db"


def get_market():
    response = requests.get(
        f"{GATEWAY_URL}/market-watch",
        timeout=60,
    )
    response.raise_for_status()

    result = response.json()

    if result.get("status") != "ok":
        raise RuntimeError(result)

    data = result["data"]

    if not isinstance(data, dict):
        raise RuntimeError("Unexpected market-watch response")

    rows = data.get("marketwatch")

    if not isinstance(rows, list):
        raise RuntimeError("marketwatch list not found")

    return rows


def save_universe(rows):
    conn = sqlite3.connect(DB_PATH)

    sql = """
        INSERT INTO symbols (
            inscode,
            symbol,
            name,
            market,
            industry,
            active
        )
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(inscode)
        DO UPDATE SET
            symbol = excluded.symbol,
            name = excluded.name,
            market = excluded.market,
            industry = excluded.industry,
            active = 1,
            updated_at = CURRENT_TIMESTAMP
    """

    records = []

    for row in rows:
        # 300 = سهم عادی
        if str(row.get("yVal")) != "300":
            continue

        inscode = row.get("insCode")

        if not inscode:
            continue

        sector = row.get("csv")

        records.append((
            int(inscode),
            row.get("lva"),
            row.get("lvc"),
            row.get("cGrValCot"),
            sector,
        ))

    conn.executemany(sql, records)
    conn.commit()
    conn.close()

    return len(records)


if __name__ == "__main__":
    rows = get_market()

    print("Market instruments:", len(rows))

    saved = save_universe(rows)

    print("Ordinary shares saved:", saved)
