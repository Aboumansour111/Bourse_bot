import sqlite3

DB_PATH = "/opt/bourse-bot/data/bourse.db"

MAX_POSITIONS = 3
RESERVE_RATIO = 0.20


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cash_row = conn.execute(
        "SELECT amount FROM cash_balance WHERE id = 1"
    ).fetchone()

    cash = float(cash_row["amount"]) if cash_row else 0.0

    rows = conn.execute("""
        SELECT
            inscode,
            symbol,
            score,
            risk_level,
            close_price,
            stop_loss,
            target1,
            target2,
            entry_quality
        FROM entry_signals
        WHERE action = 'BUY_NOW'
        ORDER BY entry_quality DESC, score DESC
        LIMIT 10
    """).fetchall()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS position_recommendations (
            inscode INTEGER PRIMARY KEY,
            symbol TEXT,
            entry_quality REAL,
            risk_level TEXT,
            close_price REAL,
            stop_loss REAL,
            target1 REAL,
            target2 REAL,
            allocation REAL,
            quantity INTEGER,
            position_value REAL,
            rank_position INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("DELETE FROM position_recommendations")

    if cash <= 0:
        conn.commit()
        conn.close()
        print("Cash is zero.")
        return

    if not rows:
        conn.commit()
        conn.close()
        print("No BUY_NOW candidates.")
        return

    investable = cash * (1 - RESERVE_RATIO)

    selected = rows[:MAX_POSITIONS]

    weights = []

    for row in selected:
        quality = float(row["entry_quality"] or 0)

        risk_factor = {
            "LOW": 1.00,
            "MEDIUM": 0.85,
            "HIGH": 0.65,
        }.get(row["risk_level"], 0.75)

        weights.append(max(1.0, quality) * risk_factor)

    total_weight = sum(weights)

    print(f"Cash: {cash:,.0f}")
    print(f"Reserve: {cash * RESERVE_RATIO:,.0f}")
    print(f"Investable: {investable:,.0f}")
    print()

    for rank, (row, weight) in enumerate(
        zip(selected, weights), 1
    ):
        allocation = investable * weight / total_weight

        price = float(row["close_price"] or 0)

        if price <= 0:
            continue

        quantity = int(allocation // price)
        position_value = quantity * price

        conn.execute("""
            INSERT INTO position_recommendations (
                inscode,
                symbol,
                entry_quality,
                risk_level,
                close_price,
                stop_loss,
                target1,
                target2,
                allocation,
                quantity,
                position_value,
                rank_position
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["inscode"],
            row["symbol"],
            row["entry_quality"],
            row["risk_level"],
            price,
            row["stop_loss"],
            row["target1"],
            row["target2"],
            allocation,
            quantity,
            position_value,
            rank,
        ))

        print(
            f"{rank}. {row['symbol']} | "
            f"Quality={row['entry_quality']:.1f} | "
            f"Risk={row['risk_level']} | "
            f"Allocation={allocation:,.0f} | "
            f"Qty={quantity} | "
            f"Value={position_value:,.0f}"
        )

        if row["stop_loss"] is not None:
            print(
                f"   Entry={price:,.0f} | "
                f"Stop={float(row['stop_loss']):,.0f} | "
                f"T1={float(row['target1']):,.0f} | "
                f"T2={float(row['target2']):,.0f}"
            )

    conn.commit()
    conn.close()

    print()
    print("Position sizing complete.")


if __name__ == "__main__":
    main()
