import sqlite3
import requests

GATEWAY_URL = "http://127.0.0.1:18080"
DB_PATH = "/opt/bourse-bot/data/bourse.db"
UNIVERSE_URL = f"{GATEWAY_URL}/stock-universe"

MIN_UNIVERSE_SIZE = 700


def fetch_universe():
    response = requests.get(
        UNIVERSE_URL,
        timeout=60,
    )
    response.raise_for_status()

    payload = response.json()

    rows = payload.get("data", {}).get("marketwatch")

    if not isinstance(rows, list):
        raise RuntimeError("Invalid stock-universe response")

    universe = {}

    for row in rows:
        inscode = row.get("insCode")

        if not inscode:
            continue

        universe[int(inscode)] = {
            "symbol": row.get("lva"),
            "name": row.get("lvc"),
        }

    if len(universe) < MIN_UNIVERSE_SIZE:
        raise RuntimeError(
            f"Universe unexpectedly small: {len(universe)}"
        )

    return universe


def sync_universe(universe):
    con = sqlite3.connect(DB_PATH)

    try:
        db_rows = con.execute("""
            SELECT inscode, market, active
            FROM symbols
        """).fetchall()

        db = {
            int(row[0]): {
                "market": row[1],
                "active": row[2],
            }
            for row in db_rows
        }

        tsetmc_ids = set(universe)
        db_ids = set(db)

        new_ids = tsetmc_ids - db_ids
        stale_ids = db_ids - tsetmc_ids

        # -------------------------------------------------
        # Current TSETMC universe -> active=1
        #
        # For existing symbols, preserve the existing
        # market classification.
        # -------------------------------------------------

        insert_sql = """
            INSERT INTO symbols (
                inscode,
                symbol,
                name,
                market,
                active
            )
            VALUES (?, ?, ?, NULL, 1)
            ON CONFLICT(inscode)
            DO UPDATE SET
                symbol = excluded.symbol,
                name = excluded.name,
                active = 1,
                updated_at = CURRENT_TIMESTAMP
        """

        records = [
            (
                inscode,
                info["symbol"],
                info["name"],
            )
            for inscode, info in universe.items()
        ]

        con.executemany(insert_sql, records)

        # -------------------------------------------------
        # Portfolio protection
        # -------------------------------------------------

        portfolio_ids = set()

        try:
            rows = con.execute("""
                SELECT DISTINCT inscode
                FROM portfolio
                WHERE inscode IS NOT NULL
            """).fetchall()

            portfolio_ids = {
                int(row[0])
                for row in rows
            }

        except sqlite3.Error:
            pass

        # -------------------------------------------------
        # Instruments no longer present in current
        # TSETMC universe -> inactive.
        #
        # Portfolio instruments remain active.
        # -------------------------------------------------

        deactivate_ids = stale_ids - portfolio_ids

        if deactivate_ids:
            placeholders = ",".join(
                "?" for _ in deactivate_ids
            )

            con.execute(
                f"""
                UPDATE symbols
                SET active = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE inscode IN ({placeholders})
                """,
                tuple(deactivate_ids),
            )

        con.commit()

        active_count = con.execute("""
            SELECT COUNT(*)
            FROM symbols
            WHERE active = 1
        """).fetchone()[0]

        total_count = con.execute("""
            SELECT COUNT(*)
            FROM symbols
        """).fetchone()[0]

        print("===== UNIVERSE SYNC =====")
        print("TSETMC universe:", len(tsetmc_ids))
        print("DB before:", len(db_ids))
        print("New symbols:", len(new_ids))
        print("Stale symbols:", len(stale_ids))
        print("Deactivated:", len(deactivate_ids))
        print("Portfolio protected:", len(portfolio_ids))
        print("DB total:", total_count)
        print("DB active:", active_count)

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()


def main():
    universe = fetch_universe()
    sync_universe(universe)


if __name__ == "__main__":
    main()
