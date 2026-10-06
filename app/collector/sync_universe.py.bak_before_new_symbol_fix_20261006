import sqlite3
import requests

GATEWAY_URL = "http://127.0.0.1:18080"
DB_PATH = "/opt/bourse-bot/data/bourse.db"
UNIVERSE_URL = f"{GATEWAY_URL}/stock-universe"

MIN_UNIVERSE_SIZE = 700
MIN_DAYS_FOR_ACTIVE = 100


def fetch_universe():
    response = requests.get(UNIVERSE_URL, timeout=60)
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
        raise RuntimeError(f"Universe unexpectedly small: {len(universe)}")
    return universe


def sync_universe(universe):
    con = sqlite3.connect(DB_PATH)
    try:
        db_rows = con.execute("""
            SELECT inscode, market, active
            FROM symbols
        """).fetchall()

        db = {
            int(row[0]): {"market": row[1], "active": row[2]}
            for row in db_rows
        }

        tsetmc_ids = set(universe)
        db_ids = set(db)
        new_ids = tsetmc_ids - db_ids
        stale_ids = db_ids - tsetmc_ids

        # 1) Portfolio protection
        portfolio_ids = set()
        try:
            rows = con.execute("""
                SELECT DISTINCT inscode FROM portfolio
                WHERE inscode IS NOT NULL
            """).fetchall()
            portfolio_ids = {int(r[0]) for r in rows}
        except sqlite3.Error:
            pass

        # 2) Eligible symbols (>= MIN_DAYS_FOR_ACTIVE days of data)
        eligible_rows = con.execute("""
            SELECT s.inscode
            FROM symbols s
            JOIN daily_prices dp
              ON dp.inscode = s.inscode
             AND dp.close_price > 0
            GROUP BY s.inscode
            HAVING COUNT(dp.trade_date) >= ?
        """, (MIN_DAYS_FOR_ACTIVE,)).fetchall()
        eligible_ids = {int(r[0]) for r in eligible_rows}

        # 3) Upsert with computed active flag
        insert_sql = """
            INSERT INTO symbols (inscode, symbol, name, market, active)
            VALUES (?, ?, ?, NULL, ?)
            ON CONFLICT(inscode)
            DO UPDATE SET
                symbol = excluded.symbol,
                name = excluded.name,
                active = excluded.active,
                updated_at = CURRENT_TIMESTAMP
        """

        records = []
        for inscode, info in universe.items():
            is_eligible = (inscode in eligible_ids) or (inscode in portfolio_ids)
            records.append((
                inscode,
                info["symbol"],
                info["name"],
                1 if is_eligible else 0,
            ))

        con.executemany(insert_sql, records)

        # 4) Deactivate stale (except portfolio)
        deactivate_ids = stale_ids - portfolio_ids
        if deactivate_ids:
            placeholders = ",".join("?" for _ in deactivate_ids)
            con.execute(
                f"""UPDATE symbols SET active = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE inscode IN ({placeholders})""",
                tuple(deactivate_ids),
            )

        # 5) Final portfolio reactivation (safety)
        if portfolio_ids:
            placeholders = ",".join("?" for _ in portfolio_ids)
            con.execute(
                f"""UPDATE symbols SET active = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE inscode IN ({placeholders})""",
                tuple(portfolio_ids),
            )

        con.commit()

        active_count = con.execute(
            "SELECT COUNT(*) FROM symbols WHERE active = 1"
        ).fetchone()[0]
        total_count = con.execute(
            "SELECT COUNT(*) FROM symbols"
        ).fetchone()[0]

        skipped_no_data = sum(
            1 for inscode in tsetmc_ids
            if inscode not in eligible_ids and inscode not in portfolio_ids
        )

        print("===== UNIVERSE SYNC =====")
        print("TSETMC universe:", len(tsetmc_ids))
        print("DB before:", len(db_ids))
        print("New symbols:", len(new_ids))
        print("Stale symbols:", len(stale_ids))
        print("Deactivated (stale):", len(deactivate_ids))
        print("Skipped (no data):", skipped_no_data)
        print("Eligible (has data):", len(eligible_ids))
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
