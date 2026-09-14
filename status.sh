#!/bin/bash

DB="/opt/bourse-bot/data/bourse.db"
VENV="/opt/bourse-bot/.venv"

echo "=========================================="
echo "       BOURSE BOT PROJECT STATUS"
echo "=========================================="
echo

echo "Project:"
echo "  Path: /opt/bourse-bot"
echo

echo "Environment:"
"$VENV/bin/python" --version 2>/dev/null || echo "  Python: unavailable"
echo

echo "------------------------------------------"
echo "DATABASE"
echo "------------------------------------------"

"$VENV/bin/python" - <<'PY'
import sqlite3
from pathlib import Path

db = "/opt/bourse-bot/data/bourse.db"

if not Path(db).exists():
    print("Database: NOT FOUND")
    raise SystemExit

conn = sqlite3.connect(db)

def count(sql):
    row = conn.execute(sql).fetchone()
    return row[0] if row else 0

print("symbols:", count("SELECT COUNT(*) FROM symbols"))
print("active symbols:", count("SELECT COUNT(*) FROM symbols WHERE active=1"))
print("daily prices:", count("SELECT COUNT(*) FROM daily_prices"))
print("technical analysis:", count("SELECT COUNT(*) FROM technical_analysis"))
print("client type:", count("SELECT COUNT(*) FROM client_type"))
print("scoring results:", count("SELECT COUNT(*) FROM scoring_results"))
print("decision results:", count("SELECT COUNT(*) FROM decision_results"))
print("entry signals:", count("SELECT COUNT(*) FROM entry_signals"))
print("top picks:", count("SELECT COUNT(*) FROM top_picks"))
print("portfolio positions:", count("SELECT COUNT(*) FROM portfolio"))

cash = conn.execute(
    "SELECT amount FROM cash_balance WHERE id=1"
).fetchone()

print(
    "cash:",
    f"{float(cash[0]):,.0f}" if cash else "0"
)

try:
    row = conn.execute("""
        SELECT
            trade_date,
            market_state,
            positive,
            negative,
            unchanged,
            breadth
        FROM market_context
        ORDER BY trade_date DESC
        LIMIT 1
    """).fetchone()

    if row:
        print()
        print("Market context:")
        print("  date:", row[0])
        print("  state:", row[1])
        print("  positive:", row[2])
        print("  negative:", row[3])
        print("  unchanged:", row[4])
        print("  breadth:", round(row[5] * 100, 2), "%")
except Exception:
    pass

try:
    print()
    print("Top picks:")

    rows = conn.execute("""
        SELECT
            rank_position,
            symbol,
            entry_quality,
            risk_level,
            close_price,
            quantity,
            allocation
        FROM top_picks
        ORDER BY rank_position
        LIMIT 3
    """).fetchall()

    if not rows:
        print("  none")
    else:
        for row in rows:
            print(
                f"  {row[0]}. {row[1]} | "
                f"quality={row[2]:.1f} | "
                f"risk={row[3]} | "
                f"price={row[4]:,.0f} | "
                f"qty={row[5]} | "
                f"allocation={row[6]:,.0f}"
            )
except Exception:
    pass

conn.close()
PY

echo
echo "------------------------------------------"
echo "PROCESSES"
echo "------------------------------------------"

if pgrep -af "telegram_bot.py" > /dev/null; then
    echo "Telegram bot: RUNNING"
    pgrep -af "telegram_bot.py"
else
    echo "Telegram bot: STOPPED"
fi

if pgrep -af "backtest_final.py" > /dev/null; then
    echo "Backtest final: RUNNING"
    pgrep -af "backtest_final.py"
else
    echo "Backtest final: STOPPED / FINISHED"
fi

echo
echo "------------------------------------------"
echo "IMPORTANT FILES"
echo "------------------------------------------"

for file in \
    app/collector/universe.py \
    app/collector/bulk_history.py \
    app/collector/client_type_importer.py \
    app/analysis/technical_scan.py \
    app/analysis/scoring_engine.py \
    app/analysis/risk_filter.py \
    app/analysis/market_context.py \
    app/analysis/final_ranking.py \
    app/analysis/decision_engine.py \
    app/analysis/entry_filter.py \
    app/analysis/top_picks.py \
    app/analysis/data_freshness.py \
    app/analysis/backtest.py \
    app/analysis/backtest_final.py \
    app/portfolio_manager.py \
    app/telegram_bot.py
do
    if [ -f "$file" ]; then
        echo "OK   $file"
    else
        echo "MISS $file"
    fi
done

echo
echo "=========================================="
echo "STATUS COMPLETE"
echo "=========================================="
