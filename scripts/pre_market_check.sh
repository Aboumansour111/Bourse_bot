#!/bin/bash

set +e

BASE="/opt/bourse-bot"
PYTHON="$BASE/.venv/bin/python"
DB="$BASE/data/bourse.db"
LOG="$BASE/data/logs/market_cycle.log"
GATEWAY="http://127.0.0.1:18080"

PASS=0
WARN=0
FAIL=0

ok() {
    echo "  [OK]   $1"
    PASS=$((PASS+1))
}

warn() {
    echo "  [WARN] $1"
    WARN=$((WARN+1))
}

fail() {
    echo "  [FAIL] $1"
    FAIL=$((FAIL+1))
}

echo
echo "============================================================"
echo " BOURSE BOT — PRE MARKET HEALTH CHECK"
echo " $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "============================================================"

echo
echo "===== 1. CRON SERVICE ====="

if systemctl is-active --quiet cron; then
    ok "cron service is active"
else
    fail "cron service is NOT active"
fi

echo
echo "===== 2. CRON JOB ====="

CRON_LINE=$(crontab -l 2>/dev/null | grep -F "/opt/bourse-bot/scripts/run_market_cycle.sh" | head -1)

if [ -n "$CRON_LINE" ]; then
    ok "market cycle cron exists:"
    echo "       $CRON_LINE"
else
    fail "market cycle cron entry not found"
fi

echo
echo "===== 3. TELEGRAM BOT SERVICE ====="

if systemctl is-active --quiet bourse-bot; then
    ok "bourse-bot service is active"
else
    fail "bourse-bot service is NOT active"
fi

echo
echo "===== 4. ANDROID GATEWAY / PHONE TUNNEL ====="

if curl -sS --max-time 5 "$GATEWAY/quote/6131290133202745" >/tmp/bourse_gateway_test.json 2>/tmp/bourse_gateway_error.txt; then
    if grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' /tmp/bourse_gateway_test.json; then
        TRADE_DATE=$(grep -o '"dEven"[[:space:]]*:[[:space:]]*[0-9]*' /tmp/bourse_gateway_test.json | head -1 | grep -o '[0-9]*$')
        PRICE=$(grep -o '"pClosing"[[:space:]]*:[[:space:]]*[0-9.]*' /tmp/bourse_gateway_test.json | head -1 | grep -o '[0-9.]*$')

        ok "gateway is responding"
        echo "       test trade_date : ${TRADE_DATE:-unknown}"
        echo "       test close      : ${PRICE:-unknown}"
    else
        warn "gateway responded but status is not OK"
        cat /tmp/bourse_gateway_test.json
    fi
else
    fail "gateway/tunnel unavailable at $GATEWAY"
    cat /tmp/bourse_gateway_error.txt
fi

echo
echo "===== 5. ACTIVE MARKET CYCLE PROCESSES ====="

RUNNING=$(ps -eo pid,etime,cmd | grep -E \
'daily_update|run_market_cycle|technical_scan|scoring_engine|market_context|final_ranking|decision_engine|entry_filter|top_picks|position_manager' \
| grep -v grep)

if [ -z "$RUNNING" ]; then
    ok "no market-cycle process is currently running"
else
    warn "market-cycle process is currently running:"
    echo "$RUNNING"
fi

echo
echo "===== 6. DATABASE ====="

DB_RESULT=$("$PYTHON" - <<PY
import sqlite3

db = "$DB"

try:
    conn = sqlite3.connect(db, timeout=5)

    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    locking = conn.execute("PRAGMA locking_mode").fetchone()[0]
    busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]

    print(f"journal_mode={journal}")
    print(f"locking_mode={locking}")
    print(f"busy_timeout={busy}")
    print(f"integrity={integrity}")

    conn.close()

    if integrity == "ok":
        print("STATUS=OK")
    else:
        print("STATUS=FAIL")

except Exception as e:
    print(f"ERROR={e}")
    print("STATUS=FAIL")
PY
)

echo "$DB_RESULT"

if echo "$DB_RESULT" | grep -q "STATUS=OK"; then
    ok "SQLite integrity is OK"
else
    fail "SQLite check failed"
fi

echo
echo "===== 7. LATEST DAILY PRICE DATES ====="

"$PYTHON" - <<PY
import sqlite3

db = "$DB"
conn = sqlite3.connect(db)

rows = conn.execute("""
    SELECT trade_date, COUNT(*)
    FROM daily_prices
    GROUP BY trade_date
    ORDER BY trade_date DESC
    LIMIT 5
""").fetchall()

for date, count in rows:
    print(f"  {date} : {count} rows")

conn.close()
PY

echo
echo "===== 8. MARKET CONTEXT ====="

"$PYTHON" - <<PY
import sqlite3

db = "$DB"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

row = conn.execute("""
    SELECT trade_date,
           market_state,
           total_shares,
           positive,
           negative,
           unchanged,
           average_change_pct,
           breadth,
           updated_at
    FROM market_context
    ORDER BY trade_date DESC
    LIMIT 1
""").fetchone()

if row:
    print(f"  trade_date         : {row['trade_date']}")
    print(f"  market_state       : {row['market_state']}")
    print(f"  total_shares       : {row['total_shares']}")
    print(f"  positive           : {row['positive']}")
    print(f"  negative           : {row['negative']}")
    print(f"  unchanged          : {row['unchanged']}")
    print(f"  average_change_pct : {row['average_change_pct']}")
    print(f"  breadth            : {row['breadth']}")
    print(f"  updated_at         : {row['updated_at']}")
else:
    print("  No market_context row found")

conn.close()
PY

echo
echo "===== 9. LAST MARKET CYCLE ====="

if [ -f "$LOG" ]; then
    LAST_START=$(grep "MARKET CYCLE START" "$LOG" | tail -1)
    LAST_COMPLETE=$(grep "MARKET CYCLE COMPLETE" "$LOG" | tail -1)
    LAST_SKIP=$(grep "MARKET CYCLE SKIPPED" "$LOG" | tail -1)

    echo "  Last start    : ${LAST_START:-NONE}"
    echo "  Last complete : ${LAST_COMPLETE:-NONE}"
    echo "  Last skipped  : ${LAST_SKIP:-NONE}"

    LOCK_COUNT=$(tail -n 300 "$LOG" | grep -c "database is locked")
    GATEWAY_502=$(tail -n 300 "$LOG" | grep -c "502 Server Error")
    CONN_REFUSED=$(tail -n 300 "$LOG" | grep -c "Connection refused")

    echo
    echo "  Recent errors (last 300 lines):"
    echo "    database locked : $LOCK_COUNT"
    echo "    gateway 502     : $GATEWAY_502"
    echo "    connection refused : $CONN_REFUSED"

    if [ "$LOCK_COUNT" -gt 0 ]; then
        warn "recent database lock errors detected"
    fi

    if [ "$GATEWAY_502" -gt 0 ]; then
        warn "recent gateway 502 errors detected"
    fi

    if [ "$CONN_REFUSED" -gt 0 ]; then
        warn "recent gateway connection-refused errors detected"
    fi
else
    fail "market cycle log does not exist"
fi

echo
echo "============================================================"
echo " SUMMARY"
echo "============================================================"
echo "  OK   : $PASS"
echo "  WARN : $WARN"
echo "  FAIL : $FAIL"

if [ "$FAIL" -eq 0 ]; then
    echo
    echo "  RESULT: INFRASTRUCTURE CHECK PASSED"
else
    echo
    echo "  RESULT: CHECK FAILED — INVESTIGATE BEFORE MARKET"
fi

echo "============================================================"
echo
