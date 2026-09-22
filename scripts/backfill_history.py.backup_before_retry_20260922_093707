import sqlite3
import time
import requests
from datetime import datetime

DB_PATH = "/opt/bourse-bot/data/bourse.db"
GATEWAY_URL = "http://127.0.0.1:18080"

# برای technical_scan حداقل 200 روز لازم است.
# کمی بیشتر می‌گیریم تا در صورت وجود رکوردهای ناقص، به 200 رکورد معتبر برسیم.
HISTORY_TOP = 250

REQUEST_TIMEOUT = 30
SLEEP_BETWEEN_REQUESTS = 0.15

def fetch_history(session, inscode):
    url = f"{GATEWAY_URL}/history/{inscode}/{HISTORY_TOP}"

    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    result = response.json()

    if result.get("status") == "error":
        raise RuntimeError(result.get("error", "gateway returned error"))

    data = result.get("data", {})
    rows = data.get("closingPriceDaily", [])

    if not isinstance(rows, list):
        raise RuntimeError("closingPriceDaily is not a list")

    return rows


def save_history(conn, inscode, rows):
    saved = 0

    for row in rows:
        try:
            trade_date = int(row["dEven"])

            if trade_date <= 0:
                continue

            # حداقل داده لازم برای daily_prices
            p_closing = row.get("pClosing")
            p_last = row.get("pDrCotVal")

            if p_closing is None and p_last is None:
                continue

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
                ON CONFLICT(inscode, trade_date) DO UPDATE SET
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
                    row.get("pDrCotVal"),
                    row.get("pClosing"),
                    row.get("priceYesterday"),
                    row.get("priceFirst"),
                    row.get("priceMax"),
                    row.get("priceMin"),
                    row.get("qTotTran5J"),
                    row.get("qTotCap"),
                    row.get("zTotTran"),
                ),
            )

            saved += 1

        except (KeyError, TypeError, ValueError):
            continue

    conn.commit()
    return saved


def main():
    started = time.time()

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")

    session = requests.Session()

    symbols = conn.execute(
        """
        SELECT inscode, symbol
        FROM symbols
        WHERE active = 1
          AND (
              SELECT COUNT(*)
              FROM daily_prices dp
              WHERE dp.inscode = symbols.inscode
          ) < 200
        ORDER BY symbol
        """
    ).fetchall()

    total = len(symbols)

    print("=" * 70)
    print("HISTORY BACKFILL START")
    print("Time:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("Symbols requiring backfill:", total)
    print("History requested per symbol:", HISTORY_TOP)
    print("=" * 70, flush=True)

    success = 0
    failed = 0
    skipped = 0

    for idx, (inscode, symbol) in enumerate(symbols, 1):
        try:
            rows = fetch_history(session, inscode)

            if not rows:
                skipped += 1
                print(
                    f"[{idx}/{total}] {symbol} "
                    f"inscode={inscode} -> NO HISTORY",
                    flush=True,
                )
                continue

            saved = save_history(conn, inscode, rows)

            count = conn.execute(
                """
                SELECT COUNT(*)
                FROM daily_prices
                WHERE inscode = ?
                """,
                (inscode,),
            ).fetchone()[0]

            success += 1

            print(
                f"[{idx}/{total}] {symbol:<12} "
                f"history={len(rows):>3} "
                f"saved={saved:>3} "
                f"total={count:>3}",
                flush=True,
            )

        except Exception as exc:
            failed += 1

            print(
                f"[{idx}/{total}] {symbol:<12} "
                f"FAILED: {type(exc).__name__}: {exc}",
                flush=True,
            )

        time.sleep(SLEEP_BETWEEN_REQUESTS)

    # وضعیت نهایی
    remaining = conn.execute(
        """
        SELECT COUNT(*)
        FROM symbols s
        WHERE s.active = 1
          AND (
              SELECT COUNT(*)
              FROM daily_prices dp
              WHERE dp.inscode = s.inscode
          ) < 200
        """
    ).fetchone()[0]

    eligible = conn.execute(
        """
        SELECT COUNT(*)
        FROM symbols s
        WHERE s.active = 1
          AND (
              SELECT COUNT(*)
              FROM daily_prices dp
              WHERE dp.inscode = s.inscode
          ) >= 200
        """
    ).fetchone()[0]

    conn.close()

    elapsed = time.time() - started

    print("=" * 70)
    print("HISTORY BACKFILL COMPLETE")
    print(f"Elapsed: {elapsed:.1f}s")
    print(f"Processed: {total}")
    print(f"Success: {success}")
    print(f"Failed: {failed}")
    print(f"No history: {skipped}")
    print(f"Symbols with >=200 rows: {eligible}")
    print(f"Symbols still <200 rows: {remaining}")
    print("=" * 70)


if __name__ == "__main__":
    main()
