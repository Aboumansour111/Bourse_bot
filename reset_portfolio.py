import sqlite3

DB = "/opt/bourse-bot/data/bourse.db"

con = sqlite3.connect(DB)

try:
    con.execute("DELETE FROM portfolio")
    con.execute("DELETE FROM portfolio_transactions")
    con.execute("DELETE FROM position_levels")
    con.execute("DELETE FROM position_recommendations")
    con.execute("UPDATE cash_balance SET amount = 0")

    con.commit()
    print("Portfolio reset completed successfully.")

except Exception:
    con.rollback()
    raise

finally:
    con.close()
