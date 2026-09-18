import sqlite3

DB_PATH = "/opt/bourse-bot/data/bourse.db"


def market_adjustment(state):
    return {
        "BULLISH": 3.0,
        "POSITIVE": 1.5,
        "NEUTRAL": 0.0,
        "NEGATIVE": -2.0,
        "BEARISH": -4.0,
    }.get(state, 0.0)


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    market = conn.execute("""
        SELECT
            market_state,
            breadth
        FROM market_context
        ORDER BY trade_date DESC
        LIMIT 1
    """).fetchone()

    if not market:
        conn.close()
        raise RuntimeError(
            "Market context not found. "
            "Run market_context.py first."
        )

    adjustment = market_adjustment(
        market["market_state"]
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS final_ranking (
            inscode INTEGER PRIMARY KEY,
            symbol TEXT,
            base_score REAL,
            market_adjustment REAL,
            final_score REAL,
            decision TEXT,
            rank_position INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    rows = conn.execute("""
        SELECT
            sr.inscode,
            s.symbol,
            sr.score,
            sr.decision,
            sr.value_ratio,
            sr.volume_ratio
        FROM scoring_results sr
        JOIN symbols s
            ON s.inscode = sr.inscode
        WHERE s.active = 1
        ORDER BY sr.score DESC
    """).fetchall()

    ranked = []

    for row in rows:
        score = float(row["score"])

        value_ratio = row["value_ratio"]
        volume_ratio = row["volume_ratio"]

        # نمادهای خیلی کم‌معامله در رتبه نهایی جریمه می‌شوند.
        liquidity_penalty = 0.0

        if value_ratio is not None and value_ratio < 0.5:
            liquidity_penalty += 4.0

        if volume_ratio is not None and volume_ratio < 0.5:
            liquidity_penalty += 2.0

        final_score = max(
            0.0,
            min(
                100.0,
                score + adjustment - liquidity_penalty
            )
        )

        decision = row["decision"]

        # در بازار منفی، خریدهای مرزی سخت‌گیرانه‌تر شوند.
        if market["market_state"] in (
            "NEGATIVE",
            "BEARISH",
        ) and decision == "BUY" and final_score < 85:
            decision = "HOLD"

        ranked.append({
            "inscode": row["inscode"],
            "symbol": row["symbol"],
            "base_score": score,
            "market_adjustment": adjustment,
            "final_score": round(final_score, 2),
            "decision": decision,
        })

    ranked.sort(
        key=lambda x: x["final_score"],
        reverse=True,
    )

    for position, item in enumerate(ranked, 1):
        conn.execute("""
            INSERT INTO final_ranking (
                inscode,
                symbol,
                base_score,
                market_adjustment,
                final_score,
                decision,
                rank_position
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(inscode)
            DO UPDATE SET
                symbol = excluded.symbol,
                base_score = excluded.base_score,
                market_adjustment = excluded.market_adjustment,
                final_score = excluded.final_score,
                decision = excluded.decision,
                rank_position = excluded.rank_position,
                updated_at = CURRENT_TIMESTAMP
        """, (
            item["inscode"],
            item["symbol"],
            item["base_score"],
            item["market_adjustment"],
            item["final_score"],
            item["decision"],
            position,
        ))

    conn.commit()
    conn.close()

    print("Final ranking complete")
    print("Market state:", market["market_state"])
    print("Market adjustment:", adjustment)
    print("Ranked:", len(ranked))

    print("\nTOP 20")
    for position, item in enumerate(ranked[:20], 1):
        print(
            f'{position}. '
            f'{item["symbol"]} | '
            f'Final={item["final_score"]} | '
            f'{item["decision"]}'
        )


if __name__ == "__main__":
    main()
