import sqlite3

DB_PATH = "/opt/bourse-bot/data/bourse.db"


def clamp(value, low=0.0, high=100.0):
    return max(low, min(high, value))


def buyer_power_score(power, buy_count, sell_count):
    if power is None:
        return 8.0

    # اگر تعداد مشارکت‌کنندگان خیلی کم باشد،
    # نسبت قدرت خریدار قابل اتکا نیست.
    participants = (buy_count or 0) + (sell_count or 0)

    if participants < 10:
        return 8.0

    if power >= 2.0:
        return 20.0
    if power >= 1.5:
        return 17.0
    if power >= 1.2:
        return 14.0
    if power >= 1.0:
        return 11.0
    if power >= 0.8:
        return 7.0

    return 3.0


def volume_score(ratio):
    if ratio is None:
        return 6.0

    if ratio >= 3.0:
        return 15.0
    if ratio >= 2.0:
        return 14.0
    if ratio >= 1.5:
        return 12.0
    if ratio >= 1.2:
        return 10.0
    if ratio >= 1.0:
        return 8.0
    if ratio >= 0.7:
        return 5.0

    return 2.0


def liquidity_score(ratio):
    if ratio is None:
        return 6.0

    if ratio >= 3.0:
        return 15.0
    if ratio >= 2.0:
        return 14.0
    if ratio >= 1.5:
        return 12.0
    if ratio >= 1.2:
        return 10.0
    if ratio >= 1.0:
        return 8.0
    if ratio >= 0.7:
        return 5.0

    return 2.0


def calculate_score(technical, client):
    reasons = []
    score = 0.0

    # =========================================================
    # 1) TREND - 25
    # =========================================================
    trend_raw = int(technical["trend_score"] or 0)
    trend_points = (trend_raw / 4.0) * 25.0

    score += trend_points

    if trend_raw >= 3:
        reasons.append("روند صعودی")
    elif trend_raw <= 1:
        reasons.append("روند ضعیف")

    # =========================================================
    # 2) MOMENTUM - 20
    # =========================================================
    momentum_points = 0.0
    rsi = technical["rsi14"]

    if rsi is not None:
        if 52 <= rsi <= 65:
            momentum_points += 12
        elif 65 < rsi <= 72:
            momentum_points += 9
        elif 45 <= rsi < 52:
            momentum_points += 7
        elif 35 <= rsi < 45:
            momentum_points += 4
        elif rsi > 80:
            momentum_points += 1
            reasons.append("RSI اشباع خرید")
        elif rsi < 25:
            momentum_points += 1
            reasons.append("RSI اشباع فروش")
        else:
            momentum_points += 5

    macd_hist = technical["macd_hist"]

    if macd_hist is not None:
        if macd_hist > 0:
            momentum_points += 8
            reasons.append("MACD مثبت")
        else:
            momentum_points += 2
            reasons.append("MACD منفی")

    momentum_points = clamp(momentum_points, 0, 20)
    score += momentum_points

    # =========================================================
    # 3) VOLUME - 15
    # =========================================================
    volume_ratio = technical["volume_ratio"]
    volume_points = volume_score(volume_ratio)

    score += volume_points

    if volume_ratio is not None:
        if volume_ratio >= 2.0:
            reasons.append("حجم بالاتر از میانگین")
        elif volume_ratio < 0.7:
            reasons.append("حجم ضعیف")

    # =========================================================
    # 4) حقیقی / حقوقی + BUYER POWER - 25
    # =========================================================
    client_points = 8.0

    avg_buy_real = None
    avg_sell_real = None
    buyer_power = None
    net_real_volume = None
    real_flow_ratio = None

    if client:
        buy_count = float(client["real_buy_count"] or 0)
        buy_volume = float(client["real_buy_volume"] or 0)

        sell_count = float(client["real_sell_count"] or 0)
        sell_volume = float(client["real_sell_volume"] or 0)

        if buy_count > 0:
            avg_buy_real = buy_volume / buy_count

        if sell_count > 0:
            avg_sell_real = sell_volume / sell_count

        if avg_buy_real is not None and avg_sell_real and avg_sell_real > 0:
            buyer_power = avg_buy_real / avg_sell_real

        client_points = buyer_power_score(
            buyer_power,
            buy_count,
            sell_count,
        )

        net_real_volume = buy_volume - sell_volume

        # بسیار مهم:
        # جریان پول حقیقی را نسبت به کل حجم معامله می‌سنجیم،
        # نه نسبت به buy+sell حقیقی.
        total_volume = float(technical["volume"] or 0)

        if total_volume > 0:
            real_flow_ratio = net_real_volume / total_volume

            real_flow_ratio = clamp(
                real_flow_ratio,
                -1.0,
                1.0,
            )

            if real_flow_ratio >= 0.15:
                client_points += 5
                reasons.append("ورود پول حقیقی")
            elif real_flow_ratio >= 0.05:
                client_points += 3
            elif real_flow_ratio <= -0.15:
                client_points -= 5
                reasons.append("خروج پول حقیقی")
            elif real_flow_ratio <= -0.05:
                client_points -= 3

        client_points = clamp(client_points, 0, 25)

        if buyer_power is not None:
            if buyer_power >= 1.5:
                reasons.append("قدرت خریدار حقیقی مناسب")
            elif buyer_power < 0.8:
                reasons.append("قدرت فروشنده بیشتر")

    score += client_points

    # =========================================================
    # 5) LIQUIDITY / TRADING VALUE - 15
    # =========================================================
    value_ratio = technical["value_ratio"]
    liquidity_points = liquidity_score(value_ratio)

    score += liquidity_points

    # =========================================================
    # FINAL
    # =========================================================
    score = round(clamp(score), 2)

    if score >= 85:
        decision = "BUY"
    elif score >= 75:
        decision = "BUY"
    elif score >= 60:
        decision = "HOLD"
    elif score >= 45:
        decision = "REDUCE"
    else:
        decision = "AVOID"

    return {
        "score": score,
        "decision": decision,
        "trend_points": round(trend_points, 2),
        "momentum_points": round(momentum_points, 2),
        "volume_points": round(volume_points, 2),
        "client_points": round(client_points, 2),
        "liquidity_points": round(liquidity_points, 2),
        "buyer_power": buyer_power,
        "avg_buy_real": avg_buy_real,
        "avg_sell_real": avg_sell_real,
        "net_real_volume": net_real_volume,
        "real_flow_ratio": real_flow_ratio,
        "reason": "، ".join(reasons[:8]),
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE IF NOT EXISTS scoring_results (
            inscode INTEGER PRIMARY KEY,
            trade_date INTEGER NOT NULL,
            symbol TEXT,
            score REAL NOT NULL,
            decision TEXT NOT NULL,
            trend_points REAL,
            momentum_points REAL,
            volume_points REAL,
            client_points REAL,
            liquidity_points REAL,
            rsi14 REAL,
            macd_hist REAL,
            volume_ratio REAL,
            value_ratio REAL,
            buyer_power REAL,
            avg_buy_real REAL,
            avg_sell_real REAL,
            net_real_volume REAL,
            real_flow_ratio REAL,
            reason TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    rows = conn.execute("""
        SELECT
            s.inscode,
            s.symbol,
            t.trade_date,
            t.trend_score,
            t.rsi14,
            t.macd_hist,
            t.volume,
            t.volume_ratio,
            t.value_ratio,
            c.real_buy_count,
            c.real_buy_volume,
            c.real_sell_count,
            c.real_sell_volume
        FROM symbols s
        JOIN technical_analysis t
            ON t.inscode = s.inscode
        LEFT JOIN client_type c
            ON c.inscode = s.inscode
            AND c.trade_date = (
                SELECT MAX(c2.trade_date)
                FROM client_type c2
                WHERE c2.inscode = s.inscode
            )
        WHERE s.active = 1
        ORDER BY s.symbol
    """).fetchall()

    print("Symbols to score:", len(rows))

    insert_sql = """
        INSERT INTO scoring_results (
            inscode,
            trade_date,
            symbol,
            score,
            decision,
            trend_points,
            momentum_points,
            volume_points,
            client_points,
            liquidity_points,
            rsi14,
            macd_hist,
            volume_ratio,
            value_ratio,
            buyer_power,
            avg_buy_real,
            avg_sell_real,
            net_real_volume,
            real_flow_ratio,
            reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(inscode)
        DO UPDATE SET
            trade_date = excluded.trade_date,
            symbol = excluded.symbol,
            score = excluded.score,
            decision = excluded.decision,
            trend_points = excluded.trend_points,
            momentum_points = excluded.momentum_points,
            volume_points = excluded.volume_points,
            client_points = excluded.client_points,
            liquidity_points = excluded.liquidity_points,
            rsi14 = excluded.rsi14,
            macd_hist = excluded.macd_hist,
            volume_ratio = excluded.volume_ratio,
            value_ratio = excluded.value_ratio,
            buyer_power = excluded.buyer_power,
            avg_buy_real = excluded.avg_buy_real,
            avg_sell_real = excluded.avg_sell_real,
            net_real_volume = excluded.net_real_volume,
            real_flow_ratio = excluded.real_flow_ratio,
            reason = excluded.reason,
            updated_at = CURRENT_TIMESTAMP
    """

    counts = {
        "BUY": 0,
        "HOLD": 0,
        "REDUCE": 0,
        "AVOID": 0,
    }

    for row in rows:
        result = calculate_score(row, row)

        conn.execute(
            insert_sql,
            (
                row["inscode"],
                row["trade_date"],
                row["symbol"],
                result["score"],
                result["decision"],
                result["trend_points"],
                result["momentum_points"],
                result["volume_points"],
                result["client_points"],
                result["liquidity_points"],
                row["rsi14"],
                row["macd_hist"],
                row["volume_ratio"],
                row["value_ratio"],
                result["buyer_power"],
                result["avg_buy_real"],
                result["avg_sell_real"],
                result["net_real_volume"],
                result["real_flow_ratio"],
                result["reason"],
            ),
        )

        counts[result["decision"]] += 1

    conn.commit()

    conn.execute("DELETE FROM signals")

    signal_rows = conn.execute("""
        SELECT
            inscode,
            score,
            decision,
            reason
        FROM scoring_results
        ORDER BY score DESC
    """).fetchall()

    for row in signal_rows:
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

    print()
    print("Scoring complete")
    print("BUY:", counts["BUY"])
    print("HOLD:", counts["HOLD"])
    print("REDUCE:", counts["REDUCE"])
    print("AVOID:", counts["AVOID"])


if __name__ == "__main__":
    main()
