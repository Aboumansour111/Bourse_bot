import sqlite3

DB_PATH = "/opt/bourse-bot/data/bourse.db"


def clamp(value, low=0, high=100):
    return max(low, min(high, value))


def apply_risk_filter(row):
    score = float(row["score"])
    rsi = row["rsi14"]
    volume_ratio = row["volume_ratio"]
    value_ratio = row["value_ratio"]
    macd_hist = row["macd_hist"]
    buyer_power = row["buyer_power"]

    penalty = 0
    reasons = []

    # RSI بیش از حد کشیده
    if rsi is not None:
        if rsi >= 90:
            penalty += 18
            reasons.append("RSI بسیار بالا")
        elif rsi >= 80:
            penalty += 10
            reasons.append("RSI بالا")
        elif rsi >= 72:
            penalty += 4
            reasons.append("RSI نسبتاً بالا")

    # حجم بسیار غیرعادی
    if volume_ratio is not None:
        if volume_ratio >= 8:
            penalty += 8
            reasons.append("حجم غیرعادی")
        elif volume_ratio >= 5:
            penalty += 5
            reasons.append("حجم بسیار بالا")

    # نقدشوندگی ضعیف
    if value_ratio is not None and value_ratio < 0.5:
        penalty += 8
        reasons.append("ارزش معاملات ضعیف")

    # MACD منفی در حالی که Score بالا است
    if macd_hist is not None and macd_hist < 0:
        penalty += 6
        reasons.append("MACD منفی")

    # قدرت خریدار بسیار افراطی؛ نیازمند تأیید بیشتر
    if buyer_power is not None and buyer_power >= 10:
        penalty += 4
        reasons.append("قدرت خریدار غیرعادی")

    final_score = round(clamp(score - penalty), 2)

    # تصمیم محافظه‌کارانه‌تر
    if final_score >= 85:
        decision = "BUY"
    elif final_score >= 75:
        decision = "BUY"
    elif final_score >= 60:
        decision = "HOLD"
    elif final_score >= 45:
        decision = "REDUCE"
    else:
        decision = "AVOID"

    # اگر ریسک بالا باشد، BUY را به HOLD تبدیل می‌کنیم
    if "RSI بسیار بالا" in reasons and decision == "BUY":
        decision = "HOLD"

    if (
        "ارزش معاملات ضعیف" in reasons
        and decision == "BUY"
    ):
        decision = "HOLD"

    return final_score, decision, penalty, reasons


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    columns = {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info(scoring_results)"
        ).fetchall()
    }

    if "risk_penalty" not in columns:
        conn.execute(
            "ALTER TABLE scoring_results "
            "ADD COLUMN risk_penalty REAL DEFAULT 0"
        )

    if "final_score" not in columns:
        conn.execute(
            "ALTER TABLE scoring_results "
            "ADD COLUMN final_score REAL"
        )

    if "risk_reason" not in columns:
        conn.execute(
            "ALTER TABLE scoring_results "
            "ADD COLUMN risk_reason TEXT"
        )

    rows = conn.execute("""
        SELECT *
        FROM scoring_results
    """).fetchall()

    success = 0

    for row in rows:
        try:
            final_score, decision, penalty, reasons = apply_risk_filter(row)

            conn.execute(
                """
                UPDATE scoring_results
                SET
                    score = ?,
                    decision = ?,
                    risk_penalty = ?,
                    final_score = ?,
                    risk_reason = ?
                WHERE inscode = ?
                """,
                (
                    final_score,
                    decision,
                    penalty,
                    final_score,
                    "، ".join(reasons),
                    row["inscode"],
                ),
            )

            success += 1

        except Exception as exc:
            print(
                f"ERROR {row['inscode']}: {exc}"
            )

    conn.execute("DELETE FROM signals")

    latest = conn.execute("""
        SELECT
            inscode,
            score,
            decision,
            reason
        FROM scoring_results
        ORDER BY score DESC
    """).fetchall()

    for row in latest:
        conn.execute(
            """
            INSERT INTO signals (
                inscode,
                decision,
                score,
                reason
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                row["inscode"],
                row["decision"],
                row["score"],
                row["reason"],
            ),
        )

    conn.commit()
    conn.close()

    print("Risk filter complete")
    print("Processed:", success)


if __name__ == "__main__":
    main()
