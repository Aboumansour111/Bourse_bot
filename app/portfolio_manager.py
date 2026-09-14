import sqlite3

DB_PATH = "/opt/bourse-bot/data/bourse.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_cash():
    conn = get_conn()
    row = conn.execute(
        "SELECT amount FROM cash_balance WHERE id = 1"
    ).fetchone()
    conn.close()

    return float(row["amount"]) if row else 0.0


def set_cash(amount):
    conn = get_conn()

    conn.execute(
        """
        INSERT INTO cash_balance (id, amount, updated_at)
        VALUES (1, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id)
        DO UPDATE SET
            amount = excluded.amount,
            updated_at = CURRENT_TIMESTAMP
        """,
        (float(amount),),
    )

    conn.commit()
    conn.close()


def find_symbol(symbol):
    conn = get_conn()

    row = conn.execute(
        """
        SELECT inscode, symbol
        FROM symbols
        WHERE symbol = ?
          AND active = 1
        ORDER BY inscode
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()

    conn.close()
    return row


def buy(symbol, quantity, price, fee=0.0, trade_date=None):
    quantity = int(quantity)
    price = float(price)
    fee = float(fee)

    if quantity <= 0:
        raise ValueError("quantity must be positive")

    if price <= 0:
        raise ValueError("price must be positive")

    stock = find_symbol(symbol)

    if not stock:
        raise ValueError(f"Symbol not found: {symbol}")

    inscode = int(stock["inscode"])
    actual_symbol = stock["symbol"]

    conn = get_conn()

    cash_row = conn.execute(
        "SELECT amount FROM cash_balance WHERE id = 1"
    ).fetchone()

    cash = float(cash_row["amount"]) if cash_row else 0.0

    total_cost = quantity * price + fee

    if total_cost > cash:
        conn.close()
        raise ValueError(
            f"Insufficient cash: required={total_cost:.0f}, "
            f"available={cash:.0f}"
        )

    position = conn.execute(
        """
        SELECT quantity, average_price
        FROM portfolio
        WHERE inscode = ?
        """,
        (inscode,),
    ).fetchone()

    old_quantity = int(position["quantity"]) if position else 0
    old_average = float(position["average_price"]) if position else 0.0

    new_quantity = old_quantity + quantity

    new_average = (
        (
            old_quantity * old_average
        ) + (
            quantity * price
        )
    ) / new_quantity

    conn.execute(
        """
        INSERT INTO portfolio (
            inscode,
            symbol,
            quantity,
            average_price
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(inscode)
        DO UPDATE SET
            symbol = excluded.symbol,
            quantity = excluded.quantity,
            average_price = excluded.average_price,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            inscode,
            actual_symbol,
            new_quantity,
            new_average,
        ),
    )

    conn.execute(
        """
        INSERT INTO portfolio_transactions (
            inscode,
            symbol,
            side,
            quantity,
            price,
            fee,
            trade_date
        )
        VALUES (?, ?, 'BUY', ?, ?, ?, ?)
        """,
        (
            inscode,
            actual_symbol,
            quantity,
            price,
            fee,
            trade_date,
        ),
    )

    new_cash = cash - total_cost

    conn.execute(
        """
        UPDATE cash_balance
        SET amount = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (new_cash,),
    )

    conn.commit()
    conn.close()

    return {
        "symbol": actual_symbol,
        "quantity": new_quantity,
        "average_price": new_average,
        "cash": new_cash,
    }


def sell(symbol, quantity, price, fee=0.0, trade_date=None):
    quantity = int(quantity)
    price = float(price)
    fee = float(fee)

    if quantity <= 0:
        raise ValueError("quantity must be positive")

    if price <= 0:
        raise ValueError("price must be positive")

    stock = find_symbol(symbol)

    if not stock:
        raise ValueError(f"Symbol not found: {symbol}")

    inscode = int(stock["inscode"])
    actual_symbol = stock["symbol"]

    conn = get_conn()

    position = conn.execute(
        """
        SELECT quantity, average_price
        FROM portfolio
        WHERE inscode = ?
        """,
        (inscode,),
    ).fetchone()

    if not position:
        conn.close()
        raise ValueError("No position exists")

    old_quantity = int(position["quantity"])
    average_price = float(position["average_price"])

    if quantity > old_quantity:
        conn.close()
        raise ValueError(
            f"Insufficient position: owned={old_quantity}, "
            f"requested={quantity}"
        )

    proceeds = quantity * price - fee
    new_quantity = old_quantity - quantity

    if new_quantity == 0:
        conn.execute(
            "DELETE FROM portfolio WHERE inscode = ?",
            (inscode,),
        )
    else:
        conn.execute(
            """
            UPDATE portfolio
            SET quantity = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE inscode = ?
            """,
            (new_quantity, inscode),
        )

    conn.execute(
        """
        INSERT INTO portfolio_transactions (
            inscode,
            symbol,
            side,
            quantity,
            price,
            fee,
            trade_date
        )
        VALUES (?, ?, 'SELL', ?, ?, ?, ?)
        """,
        (
            inscode,
            actual_symbol,
            quantity,
            price,
            fee,
            trade_date,
        ),
    )

    cash_row = conn.execute(
        "SELECT amount FROM cash_balance WHERE id = 1"
    ).fetchone()

    cash = float(cash_row["amount"]) if cash_row else 0.0
    new_cash = cash + proceeds

    conn.execute(
        """
        UPDATE cash_balance
        SET amount = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (new_cash,),
    )

    realized_pnl = (
        quantity * (price - average_price)
    ) - fee

    conn.commit()
    conn.close()

    return {
        "symbol": actual_symbol,
        "remaining_quantity": new_quantity,
        "cash": new_cash,
        "realized_pnl": realized_pnl,
    }


def get_portfolio():
    conn = get_conn()

    positions = conn.execute(
        """
        SELECT
            p.inscode,
            p.symbol,
            p.quantity,
            p.average_price,
            t.close AS market_price
        FROM portfolio p
        LEFT JOIN technical_analysis t
            ON t.inscode = p.inscode
        WHERE p.quantity > 0
        ORDER BY p.symbol
        """
    ).fetchall()

    cash_row = conn.execute(
        "SELECT amount FROM cash_balance WHERE id = 1"
    ).fetchone()

    cash = float(cash_row["amount"]) if cash_row else 0.0

    result = []

    total_cost = 0.0
    total_market_value = 0.0

    for row in positions:
        average_price = float(row["average_price"])
        quantity = int(row["quantity"])

        market_price = (
            float(row["market_price"])
            if row["market_price"] is not None
            else average_price
        )

        cost = quantity * average_price
        market_value = quantity * market_price
        pnl = market_value - cost

        total_cost += cost
        total_market_value += market_value

        result.append(
            {
                "inscode": int(row["inscode"]),
                "symbol": row["symbol"],
                "quantity": quantity,
                "average_price": average_price,
                "market_price": market_price,
                "cost": cost,
                "market_value": market_value,
                "pnl": pnl,
                "pnl_percent": (
                    (pnl / cost) * 100
                    if cost > 0
                    else 0.0
                ),
            }
        )

    conn.close()

    return {
        "cash": cash,
        "positions": result,
        "total_cost": total_cost,
        "market_value": total_market_value,
        "total_assets": cash + total_market_value,
        "total_pnl": total_market_value - total_cost,
        "total_pnl_percent": (
            (total_market_value - total_cost)
            / total_cost
            * 100
            if total_cost > 0
            else 0.0
        ),
    }


def get_signal(symbol):
    conn = get_conn()

    row = conn.execute(
        """
        SELECT
            sr.inscode,
            sr.score,
            sr.decision,
            sr.reason,
            COALESCE(p.quantity, 0) AS quantity
        FROM scoring_results sr
        JOIN symbols s
            ON s.inscode = sr.inscode
        LEFT JOIN portfolio p
            ON p.inscode = sr.inscode
        WHERE s.symbol = ?
        ORDER BY sr.final_score DESC
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()

    conn.close()

    if not row:
        return None

    quantity = int(row["quantity"])
    base_decision = row["decision"]

    if quantity > 0:
        if base_decision == "BUY":
            final_decision = "ADD"
        elif base_decision == "REDUCE":
            final_decision = "REDUCE"
        elif base_decision == "AVOID":
            final_decision = "EXIT"
        else:
            final_decision = "HOLD"
    else:
        final_decision = base_decision

    return {
        "inscode": int(row["inscode"]),
        "symbol": symbol,
        "score": float(row["score"]),
        "decision": final_decision,
        "quantity": quantity,
        "reason": row["reason"],
    }


def show_portfolio():
    data = get_portfolio()

    print("Cash:", round(data["cash"], 2))
    print("Positions:", len(data["positions"]))
    print("Market value:", round(data["market_value"], 2))
    print("Total assets:", round(data["total_assets"], 2))
    print("Total P/L:", round(data["total_pnl"], 2))
    print("P/L %:", round(data["total_pnl_percent"], 2))

    for position in data["positions"]:
        print(
            position["symbol"],
            "| qty =", position["quantity"],
            "| avg =", round(position["average_price"], 2),
            "| market =", round(position["market_price"], 2),
            "| P/L =", round(position["pnl"], 2),
            "| P/L % =", round(position["pnl_percent"], 2),
        )


if __name__ == "__main__":
    show_portfolio()
