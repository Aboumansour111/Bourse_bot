import sqlite3
from datetime import datetime

DB_PATH = "/opt/bourse-bot/data/bourse.db"


def fmt_date(value):
    if not value:
        return "-"
    s = str(value)
    if len(s) == 8:
        return f"{s[:4]}/{s[4:6]}/{s[6:]}"
    return s


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    active_count = conn.execute("""
        SELECT COUNT(*)
        FROM symbols
        WHERE active = 1
    """).fetchone()[0]

    price_date = conn.execute("""
        SELECT MAX(trade_date)
        FROM daily_prices
        WHERE close_price IS NOT NULL
          AND close_price > 0
    """).fetchone()[0]

    client_date = conn.execute("""
        SELECT MAX(trade_date)
        FROM client_type
    """).fetchone()[0]

    market_date = conn.execute("""
        SELECT MAX(trade_date)
        FROM market_context
    """).fetchone()[0]

    tech_date = conn.execute("""
        SELECT MAX(trade_date)
        FROM technical_analysis
    """).fetchone()[0]

    decision_date = conn.execute("""
        SELECT MAX(trade_date)
        FROM decision_results
    """).fetchone()[0]

    # تعداد نمادهای فعال که در آخرین روز قیمت داده دارند
    price_coverage = conn.execute("""
        SELECT COUNT(DISTINCT d.inscode)
        FROM daily_prices d
        JOIN symbols s
          ON s.inscode = d.inscode
        WHERE s.active = 1
          AND d.trade_date = ?
    """, (price_date,)).fetchone()[0] if price_date else 0

    # تعداد نمادهای فعال که در آخرین روز client type داده دارند
    client_coverage = conn.execute("""
        SELECT COUNT(DISTINCT c.inscode)
        FROM client_type c
        JOIN symbols s
          ON s.inscode = c.inscode
        WHERE s.active = 1
          AND c.trade_date = ?
    """, (client_date,)).fetchone()[0] if client_date else 0

    # تعداد نمادهای فعال دارای تحلیل
    tech_coverage = conn.execute("""
        SELECT COUNT(DISTINCT t.inscode)
        FROM technical_analysis t
        JOIN symbols s
          ON s.inscode = t.inscode
        WHERE s.active = 1
          AND t.trade_date = ?
    """, (tech_date,)).fetchone()[0] if tech_date else 0

    # اختلاف تاریخ آخرین داده‌ها
    dates = {
        "price": price_date,
        "client": client_date,
        "market": market_date,
        "technical": tech_date,
        "decision": decision_date,
    }

    unique_dates = {
        value for value in dates.values()
        if value is not None
    }

    same_session = len(unique_dates) <= 1

    print("=== DATA FRESHNESS ===")
    print("Checked at:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("Active symbols:", active_count)
    print()

    print("Price date:", fmt_date(price_date))
    print("Client-Type date:", fmt_date(client_date))
    print("Market date:", fmt_date(market_date))
    print("Technical date:", fmt_date(tech_date))
    print("Decision date:", fmt_date(decision_date))
    print()

    print(
        f"Price coverage: "
        f"{price_coverage}/{active_count}"
    )

    print(
        f"Client-Type coverage: "
        f"{client_coverage}/{active_count}"
    )

    print(
        f"Technical coverage: "
        f"{tech_coverage}/{active_count}"
    )

    print()

    if same_session:
        print("SESSION CHECK: OK")
    else:
        print("SESSION CHECK: WARNING - dates differ")

    if active_count > 0:
        price_pct = price_coverage / active_count * 100
        client_pct = client_coverage / active_count * 100
        tech_pct = tech_coverage / active_count * 100

        print(
            f"Price coverage: {price_pct:.1f}%"
        )
        print(
            f"Client coverage: {client_pct:.1f}%"
        )
        print(
            f"Technical coverage: {tech_pct:.1f}%"
        )

    conn.close()


if __name__ == "__main__":
    main()
