import sqlite3
from pathlib import Path

DB_PATH = Path("/opt/bourse-bot/data/bourse.db")


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS symbols (
        inscode INTEGER PRIMARY KEY,
        symbol TEXT,
        name TEXT,
        market TEXT,
        industry TEXT,
        active INTEGER DEFAULT 1,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS daily_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inscode INTEGER NOT NULL,
        trade_date INTEGER NOT NULL,
        last_price REAL,
        close_price REAL,
        yesterday_price REAL,
        first_price REAL,
        high_price REAL,
        low_price REAL,
        volume REAL,
        value REAL,
        trades_count INTEGER,
        UNIQUE(inscode, trade_date)
    );

    CREATE TABLE IF NOT EXISTS client_type (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inscode INTEGER NOT NULL,
        trade_date INTEGER NOT NULL,
        real_buy_count INTEGER,
        real_buy_volume REAL,
        real_sell_count INTEGER,
        real_sell_volume REAL,
        legal_buy_count INTEGER,
        legal_buy_volume REAL,
        legal_sell_count INTEGER,
        legal_sell_volume REAL,
        UNIQUE(inscode, trade_date)
    );

    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inscode INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        decision TEXT NOT NULL,
        score REAL,
        reason TEXT
    );

    CREATE TABLE IF NOT EXISTS portfolio (
        inscode INTEGER PRIMARY KEY,
        symbol TEXT NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 0,
        average_price REAL NOT NULL DEFAULT 0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS portfolio_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inscode INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        fee REAL DEFAULT 0,
        trade_date INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS cash_balance (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        amount REAL NOT NULL DEFAULT 0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    INSERT OR IGNORE INTO cash_balance (id, amount)
    VALUES (1, 0);
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialized: {DB_PATH}")
