import sqlite3

DB_PATH = "/opt/bourse-bot/data/bourse.db"

MAX_PICKS = 3
RESERVE_RATIO = 0.20


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cash_row = conn.execute(
        "SELECT amount FROM cash_balance WHERE id = 1"
    ).fetchone()

    cash = float(cash_row["amount"]) if cash_row else 0.0

    market = conn.execute("""
        SELECT market_state
        FROM market_context
        ORDER BY trade_date DESC
        LIMIT 1
    """).fetchone()

    market_state = (
        market["market_state"]
        if market
        else "NEUTRAL"
    )

    candidates = conn.execute("""
        SELECT
            inscode,
            symbol,
            entry_quality,
            risk_level,
            close_price,
            stop_loss,
            target1,
            target2
        FROM entry_signals
        WHERE action = 'BUY_NOW'
        ORDER BY entry_quality DESC
        LIMIT 20
    """).fetchall()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS top_picks (
            rank_position INTEGER PRIMARY KEY,
            inscode INTEGER,
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
            market_state TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("DELETE FROM top_picks")

    if cash <= 0:
        conn.commit()
        conn.close()
        print("Cash is zero.")
        return

    if not candidates:
        conn.commit()
        conn.close()
        print("No BUY_NOW candidates.")
        return

    investable = cash * (1 - RESERVE_RATIO)

    # امتیازدهی وزن‌دار بر اساس کیفیت ورود و ریسک
    weighted = []

    for row in candidates:
        quality = float(row["entry_quality"] or 0)

        risk_factor = {
            "LOW": 1.00,
            "MEDIUM": 0.85,
            "HIGH": 0.65,
        }.get(row["risk_level"], 0.75)

        weighted_score = quality * risk_factor

        weighted.append((row, weighted_score))

    weighted.sort(
        key=lambda x: x[1],
        reverse=True,
    )

    selected = weighted[:MAX_PICKS]

    total_weight = sum(
        item[1] for item in selected
    )

    if total_weight <= 0:
        conn.close()
        print("Invalid weights.")
        return

    print("Cash:", f"{cash:,.0f}")
    print("Reserve:", f"{cash * RESERVE_RATIO:,.0f}")
    print("Investable:", f"{investable:,.0f}")
    print("Market:", market_state)
    print()

    for rank, (row, weighted_score) in enumerate(
        selected, 1
    ):
        price = float(row["close_price"] or 0)

        if price <= 0:
            continue

        allocation = (
            investable
            * weighted_score
            / total_weight
        )

        quantity = int(allocation // price)
        position_value = quantity * price

        conn.execute("""
            INSERT INTO top_picks (
                rank_position,
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
                market_state
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rank,
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
            market_state,
        ))

        print(
            f"{rank}. {row['symbol']} | "
            f"Quality={row['entry_quality']:.1f} | "
            f"Risk={row['risk_level']} | "
            f"Allocation={allocation:,.0f} | "
            f"Qty={quantity} | "
            f"Value={position_value:,.0f}"
        )

        print(
            f"   Price={price:,.0f} | "
            f"Stop={float(row['stop_loss'] or 0):,.0f} | "
            f"T1={float(row['target1'] or 0):,.0f} | "
            f"T2={float(row['target2'] or 0):,.0f}"
        )

    conn.commit()
    conn.close()

    print()
    print("Top Picks complete.")


if __name__ == "__main__":
    main()
