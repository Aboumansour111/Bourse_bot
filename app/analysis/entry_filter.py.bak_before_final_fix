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

    market = conn.execute("""
        SELECT market_state, breadth
        FROM market_context
        ORDER BY trade_date DESC
        LIMIT 1
    """).fetchone()

    if not market:
        conn.close()
        raise RuntimeError("Market context not found")

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
            d.real_flow_ratio
        FROM decision_results d
        JOIN symbols s
            ON s.inscode = d.inscode
        WHERE s.active = 1
          AND d.action = 'BUY'
        ORDER BY d.score DESC
    """).fetchall()

    conn.execute("DELETE FROM entry_signals")

    accepted = []

    for row in rows:
        quality = 0.0
        reasons = []

        rsi = row["rsi14"]
        macd = row["macd_hist"]
        trend = int(row["trend_score"] or 0)
        volume = row["volume_ratio"]
        power = row["buyer_power"]
        flow = row["real_flow_ratio"]
        risk = row["risk_level"]

        # ---------------------------------------
        # Trend: 25
        # ---------------------------------------
        if trend >= 4:
            quality += 25
            reasons.append("روند کاملاً تأییدشده")
        elif trend == 3:
            quality += 20
            reasons.append("روند صعودی")
        elif trend == 2:
            quality += 10
        else:
            quality += 0
            reasons.append("روند ضعیف")

        # ---------------------------------------
        # RSI: 20
        # ---------------------------------------
        if rsi is None:
            quality += 5
        elif 50 <= rsi <= 65:
            quality += 20
            reasons.append("RSI مناسب ورود")
        elif 65 < rsi <= 70:
            quality += 14
            reasons.append("RSI نسبتاً بالا")
        elif 70 < rsi <= 75:
            quality += 7
            reasons.append("RSI بالا")
        elif rsi > 75:
            quality -= 5
            reasons.append("RSI بیش از حد بالا")
        elif 40 <= rsi < 50:
            quality += 8
        else:
            quality += 3

        # ---------------------------------------
        # MACD: 20
        # ---------------------------------------
        if macd is None:
            quality += 5
        elif macd > 0:
            quality += 20
            reasons.append("MACD مثبت")
        else:
            quality += 0
            reasons.append("MACD منفی")

        # ---------------------------------------
        # Volume: 15
        # ---------------------------------------
        if volume is None:
            quality += 5
        elif 1.2 <= volume <= 3.0:
            quality += 15
            reasons.append("حجم تأییدکننده")
        elif 1.0 <= volume < 1.2:
            quality += 10
        elif 3.0 < volume <= 5.0:
            quality += 10
            reasons.append("حجم بالا")
        elif 5.0 < volume <= 8.0:
            quality += 4
            reasons.append("حجم غیرعادی")
        elif volume > 8.0:
            quality -= 5
            reasons.append("حجم بسیار غیرعادی")
        else:
            quality += 2
            reasons.append("حجم ضعیف")

        # ---------------------------------------
        # Buyer Power: 10
        # ---------------------------------------
        if power is None:
            quality += 4
        elif 1.2 <= power <= 3.0:
            quality += 10
            reasons.append("قدرت خریدار مناسب")
        elif 1.0 <= power < 1.2:
            quality += 6
        elif 3.0 < power <= 6.0:
            quality += 6
            reasons.append("قدرت خریدار بالا")
        elif power > 6.0:
            quality -= 3
            reasons.append("قدرت خریدار غیرعادی")
        else:
            quality += 0
            reasons.append("ضعف خریدار")

        # ---------------------------------------
        # Real Flow: 10
        # ---------------------------------------
        if flow is None:
            quality += 4
        elif flow >= 0.20:
            quality += 10
            reasons.append("ورود پول حقیقی قوی")
        elif flow >= 0.10:
            quality += 8
            reasons.append("ورود پول حقیقی")
        elif flow >= 0.03:
            quality += 5
        elif flow > -0.03:
            quality += 3
        elif flow >= -0.10:
            quality += 1
        else:
            quality -= 5
            reasons.append("خروج پول حقیقی")

        # ---------------------------------------
        # Market Context
        # ---------------------------------------
        if market["market_state"] == "BULLISH":
            quality += 5
            reasons.append("بازار صعودی")
        elif market["market_state"] == "POSITIVE":
            quality += 3
        elif market["market_state"] == "NEUTRAL":
            quality += 0
        elif market["market_state"] == "NEGATIVE":
            quality -= 5
        elif market["market_state"] == "BEARISH":
            quality -= 10

        # ---------------------------------------
        # Risk penalty
        # ---------------------------------------
        if risk == "HIGH":
            quality -= 10
            reasons.append("ریسک بالا")
        elif risk == "MEDIUM":
            quality -= 3

        # Score اصلی فقط نقش تأیید دارد.
        base_score = float(row["score"] or 0)

        if base_score >= 95:
            quality += 3
        elif base_score >= 90:
            quality += 2
        elif base_score >= 85:
            quality += 1

        quality = round(max(0.0, min(100.0, quality)), 2)

        # ---------------------------------------
        # Entry classification
        # ---------------------------------------
        if quality >= 85:
            entry_action = "BUY_NOW"
        elif quality >= 75:
            entry_action = "BUY_WATCH"
        else:
            continue

        # BUY_NOW برای RSI خیلی بالا ممنوع
        if rsi is not None and rsi >= 75:
            entry_action = "BUY_WATCH"

        # BUY_NOW برای MACD منفی ممنوع
        if macd is not None and macd < 0:
            entry_action = "BUY_WATCH"

        # Risk بالا فقط با کیفیت بسیار بالا
        if risk == "HIGH" and quality < 90:
            entry_action = "BUY_WATCH"

        accepted.append({
            "inscode": row["inscode"],
            "symbol": row["symbol"],
            "trade_date": row["trade_date"],
            "score": base_score,
            "action": entry_action,
            "risk_level": risk,
            "close_price": row["close_price"],
            "stop_loss": row["stop_loss"],
            "target1": row["target1"],
            "target2": row["target2"],
            "entry_quality": quality,
            "reason": "، ".join(reasons),
        })

    accepted.sort(
        key=lambda x: x["entry_quality"],
        reverse=True,
    )

    for item in accepted:
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
            item["inscode"],
            item["symbol"],
            item["trade_date"],
            item["score"],
            item["action"],
            item["risk_level"],
            item["close_price"],
            item["stop_loss"],
            item["target1"],
            item["target2"],
            item["entry_quality"],
            item["reason"],
        ))

    conn.commit()

    print("Entry filter complete")
    print("Raw BUY:", len(rows))
    print(
        "BUY NOW:",
        sum(1 for x in accepted if x["action"] == "BUY_NOW")
    )
    print(
        "BUY WATCH:",
        sum(1 for x in accepted if x["action"] == "BUY_WATCH")
    )

    print()
    print("FINAL ENTRY CANDIDATES")

    for i, item in enumerate(accepted[:20], 1):
        print(
            f"{i}. {item['symbol']} | "
            f"Quality={item['entry_quality']:.1f} | "
            f"{item['action']} | "
            f"Risk={item['risk_level']} | "
            f"Price={item['close_price']}"
        )
        print("   ", item["reason"])

    conn.close()


if __name__ == "__main__":
    main()
