import sqlite3

DB_PATH = "/opt/bourse-bot/data/bourse.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE IF NOT EXISTS entry_signals (
            inscode INTEGER PRIMARY KEY,
            symbol TEXT,
            trade_date INTEGER,
            score REAL,
            action TEXT,
            risk_level TEXT,
            close_price REAL,
            stop_loss REAL,
            target1 REAL,
            target2 REAL,
            entry_quality REAL,
            reason TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    rows = conn.execute("""
        SELECT
            d.inscode,
            d.symbol,
            d.trade_date,
            d.score,
            d.action,
            d.risk_level,
            d.close_price,
            d.stop_loss,
            d.target1,
            d.target2,
            d.rsi14,
            d.macd_hist,
            d.trend_score,
            d.volume_ratio,
            d.buyer_power,
            d.real_flow_ratio,
            d.reason
        FROM decision_results d
        JOIN symbols s
            ON s.inscode = d.inscode
        WHERE s.active = 1
          AND d.action = 'BUY'
        ORDER BY d.score DESC
    """).fetchall()

    conn.execute("DELETE FROM entry_signals")

    for row in rows:
        score = float(row["score"] or 0)

        conn.execute("""
            INSERT INTO entry_signals (
                inscode,
                symbol,
                trade_date,
                score,
                action,
                risk_level,
                close_price,
                stop_loss,
                target1,
                target2,
                entry_quality,
                reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["inscode"],
            row["symbol"],
            row["trade_date"],
            score,
            "BUY_NOW",
            row["risk_level"],
            row["close_price"],
            row["stop_loss"],
            row["target1"],
            row["target2"],
            score,
            row["reason"] or "سیگنال BUY موتور تصمیم‌گیری",
        ))

    conn.commit()

    print("Entry filter complete")
    print("Raw BUY:", len(rows))
    print("BUY NOW:", len(rows))
    print("BUY WATCH: 0")
    print()
    print("FINAL ENTRY CANDIDATES")

    for i, row in enumerate(rows[:20], 1):
        print(
            f"{i}. {row['symbol']} | "
            f"Score={float(row['score'] or 0):.1f} | "
            f"BUY_NOW | "
            f"Risk={row['risk_level']} | "
            f"Price={row['close_price']}"
        )

    conn.close()


if __name__ == "__main__":
    main()
