#!/usr/bin/env python3
"""
diagnose_ca_impact.py

آیا معاملات Backtest V5B.1 SAFE با رویدادهای Corporate Action
(افزایش سرمایه، بازگشایی از توقف، Split) هم‌پوشانی دارند؟

این اسکریپت DIAGNOSTIC ONLY است:
- هیچ فایلی را تغییر نمی‌دهد
- هیچ جدولی را نمی‌نویسد
- هیچ Production state را دست نمی‌زند

Usage:
    /opt/bourse-bot/.venv/bin/python /opt/bourse-bot/scripts/diagnose_ca_impact.py

Output:
    گزارش کامل از معاملات آلوده + جمع‌بندی آماری
"""

import sqlite3
from collections import defaultdict
from statistics import mean, median
from datetime import datetime, timedelta


DB_PATH = "/opt/bourse-bot/data/bourse.db"

# ============================================================================
# پارامترهای Backtest — دقیقاً مطابق backtest_v5b1_safe_audit.py
# ============================================================================
MIN_HISTORY = 0
MAX_HOLD_DAYS = 10
ROUND_TRIP_COST = 0.007
ENTRY_FEE = ROUND_TRIP_COST / 2
EXIT_FEE = ROUND_TRIP_COST / 2

# ============================================================================
# پارامترهای تشخیص CA
# ============================================================================
CA_CHANGE_THRESHOLD = 0.15     # حرکت بیش از 15% = CA مشکوک
CA_LOOKBACK_DAYS = 5           # CA در N روز قبل از signal_date
CA_LOOKAHEAD_DAYS = 5          # CA در N روز بعد از exit_date
CA_NOMINAL_YESTERDAY = 1000    # مقدار Placeholder TSETMC


# ============================================================================
# توابع اندیکاتور — کپی مستقیم از backtest_v5b1_safe_audit.py
# ============================================================================
def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values, period):
    if len(values) < period:
        return []
    alpha = 2 / (period + 1)
    value = sum(values[:period]) / period
    result = [None] * (period - 1)
    result.append(value)
    for price in values[period:]:
        value = (price - value) * alpha + value
        result.append(value)
    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd_histogram(values):
    if len(values) < 40:
        return None
    fast = ema_series(values, 12)
    slow = ema_series(values, 26)
    macd = []
    for f, s in zip(fast, slow):
        if f is None or s is None:
            macd.append(None)
        else:
            macd.append(f - s)
    valid = [x for x in macd if x is not None]
    if len(valid) < 9:
        return None
    signal = ema_series(valid, 9)
    if not signal or signal[-1] is None:
        return None
    return valid[-1] - signal[-1]


def atr(highs, lows, closes, gap_before=None, period=14):
    if len(closes) <= period:
        return None
    if gap_before is None:
        gap_before = [False] * len(closes)
    trs = []
    for i in range(1, len(closes)):
        if (highs[i] <= 0 or lows[i] <= 0
                or highs[i] < lows[i] or closes[i - 1] <= 0):
            continue
        if gap_before[i]:
            tr = highs[i] - lows[i]
        else:
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        trs.append(tr)
    if len(trs) < period:
        return None
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = ((value * (period - 1)) + tr) / period
    return value


def volume_ratio(volumes, period=20):
    valid = [float(v) for v in volumes if v is not None and v > 0]
    if len(valid) < period:
        return None
    recent = valid[-period:]
    avg = sum(recent) / period
    if avg <= 0:
        return None
    return recent[-1] / avg


def technical_signal(closes, highs, lows, volumes, gap_before=None):
    if len(closes) < MIN_HISTORY:
        return None
    current = closes[-1]

    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)

    ema20_values = ema_series(closes, 20)
    ema50_values = ema_series(closes, 50)
    if not ema20_values or not ema50_values:
        return None
    ema20 = ema20_values[-1]
    ema50 = ema50_values[-1]

    rsi14 = rsi(closes, 14)
    macd_hist = macd_histogram(closes)
    atr14 = atr(highs, lows, closes, gap_before, 14)
    vol_ratio = volume_ratio(volumes, 20)

    trend = 0
    if sma20 is not None and current > sma20:
        trend += 1
    if sma50 is not None and current > sma50:
        trend += 1
    if sma200 is not None and current > sma200:
        trend += 1
    if ema20 is not None and ema50 is not None and ema20 > ema50:
        trend += 1

    quality = 0.0
    if trend == 4:
        quality += 25
    elif trend == 3:
        quality += 20
    elif trend == 2:
        quality += 10

    if rsi14 is not None:
        if 50 <= rsi14 <= 65:
            quality += 20
        elif 65 < rsi14 <= 70:
            quality += 14
        elif 70 < rsi14 <= 75:
            quality += 7
        elif rsi14 > 75:
            quality -= 5
        else:
            quality += 3

    if macd_hist is not None:
        if macd_hist > 0:
            quality += 20
        else:
            quality -= 5

    if vol_ratio is not None:
        if 1.2 <= vol_ratio <= 3:
            quality += 15
        elif 1 <= vol_ratio < 1.2:
            quality += 10
        elif 3 < vol_ratio <= 5:
            quality += 10
        elif 5 < vol_ratio <= 8:
            quality += 4
        elif vol_ratio > 8:
            quality -= 5
        else:
            quality += 2

    eligible = (
        trend >= 4
        and macd_hist is not None and macd_hist > 0
        and rsi14 is not None and rsi14 < 75
        and vol_ratio is not None and 1.2 <= vol_ratio <= 3.0
        and quality >= 75
        and atr14 is not None and atr14 > 0
    )

    return {
        "quality": quality,
        "eligible": eligible,
        "trend": trend,
        "rsi": rsi14,
        "macd_hist": macd_hist,
        "atr": atr14,
        "volume_ratio": vol_ratio,
    }


# ============================================================================
# توابع کمکی تاریخ
# ============================================================================
def int_to_date(i):
    return datetime.strptime(str(i), "%Y%m%d")


def in_window(ca_date, sig_date, exit_date, before, after):
    """آیا ca_date در بازه [sig_date-before, exit_date+after] قرار دارد؟"""
    ca_dt = int_to_date(ca_date)
    start = int_to_date(sig_date) - timedelta(days=before)
    end = int_to_date(exit_date) + timedelta(days=after)
    return start <= ca_dt <= end


# ============================================================================
# بارگذاری داده
# ============================================================================
def load_data(conn):
    symbols = conn.execute("""
        SELECT inscode, symbol
        FROM symbols
        WHERE active = 1
        ORDER BY inscode
    """).fetchall()

    data = {}
    for inscode, symbol in symbols:
        rows = conn.execute("""
            SELECT trade_date, close_price, high_price, low_price, volume
            FROM daily_prices
            WHERE inscode = ?
              AND close_price IS NOT NULL
              AND high_price IS NOT NULL
              AND low_price IS NOT NULL
              AND volume IS NOT NULL
            ORDER BY trade_date ASC
        """, (inscode,)).fetchall()

        valid_rows, gap_before = [], []
        had_invalid = False
        for r in rows:
            trade_date, close_price, high_price, low_price, volume = r
            valid = (
                close_price > 0 and high_price > 0 and low_price > 0
                and volume > 0 and high_price >= low_price
                and close_price >= low_price and close_price <= high_price
            )
            if not valid:
                had_invalid = True
                continue
            valid_rows.append(r)
            gap_before.append(had_invalid)
            had_invalid = False

        if len(valid_rows) < MIN_HISTORY + 2:
            continue

        data[inscode] = {
            "symbol": symbol,
            "dates": [r[0] for r in valid_rows],
            "closes": [float(r[1]) for r in valid_rows],
            "highs": [float(r[2]) for r in valid_rows],
            "lows": [float(r[3]) for r in valid_rows],
            "volumes": [float(r[4]) for r in valid_rows],
            "gap_before": gap_before,
        }
    return data


def load_ca_events(conn):
    """بارگذاری همه CAهای 2025-2026."""
    rows = conn.execute("""
        SELECT s.inscode, s.symbol, dp.trade_date,
               dp.close_price, dp.yesterday_price,
               (dp.close_price - dp.yesterday_price) * 1.0
                   / dp.yesterday_price AS chg
        FROM daily_prices dp
        JOIN symbols s ON s.inscode = dp.inscode
        WHERE dp.yesterday_price > 0
          AND ABS((dp.close_price - dp.yesterday_price) * 1.0
                  / dp.yesterday_price) > ?
          AND dp.trade_date >= 20250101
        ORDER BY dp.trade_date
    """, (CA_CHANGE_THRESHOLD,)).fetchall()

    events_by_inscode = defaultdict(list)
    for inscode, symbol, trade_date, close_p, yest_p, chg in rows:
        events_by_inscode[inscode].append({
            "symbol": symbol,
            "date": trade_date,
            "close": close_p,
            "yesterday": yest_p,
            "change": chg,
            "is_nominal": yest_p == CA_NOMINAL_YESTERDAY,
        })
    return events_by_inscode


# ============================================================================
# Breadth
# ============================================================================
def build_breadth(data):
    daily = defaultdict(dict)
    for inscode, item in data.items():
        dates = item["dates"]
        closes = item["closes"]
        for i in range(1, len(dates)):
            prev, curr = closes[i - 1], closes[i]
            if prev > 0:
                daily[dates[i]][inscode] = (curr - prev) / prev

    breadth = {}
    for date, changes in daily.items():
        if not changes:
            continue
        positive = sum(1 for c in changes.values() if c > 0)
        breadth[date] = {"breadth": positive / len(changes)}
    return breadth


# ============================================================================
# شبیه‌سازی Backtest با تشخیص CA
# ============================================================================
def run_diagnostic(conn):
    print("Loading data...")
    data = load_data(conn)
    print(f"  → {len(data)} symbols with valid data")

    print("Loading CA events...")
    ca_events = load_ca_events(conn)
    total_ca = sum(len(v) for v in ca_events.values())
    print(f"  → {total_ca} CA events across "
          f"{len(ca_events)} symbols (2025-2026)")
    print()

    print("Building breadth...")
    breadth = build_breadth(data)
    print(f"  → breadth for {len(breadth)} dates")
    print()

    print("Running backtest + CA detection...")
    trades = []
    symbol_count = 0

    for inscode, item in data.items():
        symbol_count += 1
        dates = item["dates"]
        closes = item["closes"]
        highs = item["highs"]
        lows = item["lows"]
        volumes = item["volumes"]

        ca_dates = [e["date"] for e in ca_events.get(inscode, [])]

        for i in range(MIN_HISTORY, len(dates) - 1):
            signal = technical_signal(
                closes[:i + 1], highs[:i + 1], lows[:i + 1],
                volumes[:i + 1], item["gap_before"][:i + 1],
            )
            if signal is None or not signal["eligible"]:
                continue

            signal_date = dates[i]
            market = breadth.get(signal_date)
            if market is None or market["breadth"] < 0.42:
                continue

            entry_index = i + 1
            if entry_index >= len(dates):
                continue
            entry_date = dates[entry_index]

            # فقط 2026 — مطابق خروجی Production
            if entry_date < 20260101 or entry_date > 20261231:
                continue

            entry = closes[entry_index]
            atr14 = signal["atr"]
            stop = entry - (1.5 * atr14)
            target = entry + (3.0 * atr14)
            if stop <= 0 or target <= entry:
                continue

            last_index = min(entry_index + MAX_HOLD_DAYS, len(dates) - 1)
            exit_price = closes[last_index]
            exit_date = dates[last_index]
            exit_reason = "TIME"

            for j in range(entry_index + 1, last_index + 1):
                day_low, day_high = lows[j], highs[j]
                hit_stop = day_low <= stop
                hit_target = day_high >= target
                if hit_stop and hit_target:
                    exit_price = stop
                    exit_date = dates[j]
                    exit_reason = "STOP_AND_TARGET_SAME_DAY"
                    break
                if hit_stop:
                    exit_price = stop
                    exit_date = dates[j]
                    exit_reason = "STOP"
                    break
                if hit_target:
                    exit_price = target
                    exit_date = dates[j]
                    exit_reason = "TARGET"
                    break

            gross_return = (exit_price - entry) / entry
            net_return = gross_return - ROUND_TRIP_COST

            # تشخیص CA در پنجره
            ca_in_window = []
            for ca_d in ca_dates:
                if in_window(ca_d, signal_date, exit_date,
                             CA_LOOKBACK_DAYS, CA_LOOKAHEAD_DAYS):
                    ca_in_window.append(ca_d)

            ca_details = [
                e for e in ca_events.get(inscode, [])
                if e["date"] in ca_in_window
            ]

            trades.append({
                "symbol": item["symbol"],
                "inscode": inscode,
                "signal_date": signal_date,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "entry": entry,
                "exit": exit_price,
                "return_pct": net_return * 100,
                "quality": signal["quality"],
                "reason": exit_reason,
                "atr": atr14,
                "stop": stop,
                "target": target,
                "ca_dates": ca_in_window,
                "ca_details": ca_details,
            })

        if symbol_count % 100 == 0:
            print(f"  ... {symbol_count}/{len(data)} symbols processed, "
                  f"{len(trades)} candidate trades found")

    return trades, ca_events


# ============================================================================
# گزارش
# ============================================================================
def print_report(trades, ca_events):
    print()
    print("=" * 100)
    print("DIAGNOSTIC REPORT — CA Impact on V5B.1 SAFE Backtest (2026)")
    print("=" * 100)
    print()

    clean = [t for t in trades if not t["ca_dates"]]
    affected = [t for t in trades if t["ca_dates"]]

    # جدا کردن دو نوع CA
    nominal_affected = [
        t for t in affected
        if any(e["is_nominal"] for e in t["ca_details"])
    ]
    real_ca_affected = [
        t for t in affected
        if not any(e["is_nominal"] for e in t["ca_details"])
    ]

    print(f"Total trades found:                 {len(trades)}")
    print(f"├─ Clean (no CA in window):         {len(clean)}")
    print(f"└─ Affected by CA:                  {len(affected)}")
    print(f"   ├─ Nominal reopening (1000):     {len(nominal_affected)}")
    print(f"   └─ Real Corporate Action:        {len(real_ca_affected)}")
    print()

    # آمار بازده
    def stats(lst, label):
        if not lst:
            print(f"{label:<35} (empty)")
            return
        returns = [t["return_pct"] for t in lst]
        print(f"{label:<35} n={len(lst):<4} "
              f"avg={mean(returns):+7.2f}%  "
              f"median={median(returns):+7.2f}%  "
              f"sum={sum(returns):+8.2f}%")

    print("-" * 100)
    print("RETURN STATISTICS (per-trade, not portfolio-level)")
    print("-" * 100)
    stats(clean, "Clean trades")
    stats(real_ca_affected, "Affected by REAL CA")
    stats(nominal_affected, "Affected by NOMINAL reopening")
    stats(affected, "All affected")
    stats(trades, "All trades")
    print()

    # سهم CA در بازده کل
    total_sum = sum(t["return_pct"] for t in trades)
    affected_sum = sum(t["return_pct"] for t in affected)
    if total_sum != 0:
        contribution = affected_sum / total_sum * 100
        print(f"Contribution of CA-affected trades to total return: "
              f"{contribution:+.1f}%")
    print()

    # جدول معاملات آلوده
    print("-" * 100)
    print("AFFECTED TRADES — DETAIL")
    print("-" * 100)
    print(f"{'Symbol':<12} {'Signal':<10} {'Entry':<10} {'Exit':<10} "
          f"{'Return':>9}  {'Reason':<26}  CA Info")
    print("-" * 130)
    for t in sorted(affected, key=lambda x: x["entry_date"]):
        ca_str = ", ".join(
            f"{e['date']}({e['change']*100:+.1f}%{'|nom' if e['is_nominal'] else ''})"
            for e in t["ca_details"]
        )
        print(f"{t['symbol']:<12} {t['signal_date']:<10} {t['entry_date']:<10} "
              f"{t['exit_date']:<10} {t['return_pct']:>+8.2f}%  "
              f"{t['reason']:<26}  {ca_str}")
    print()

    # جدول معاملات پاک (نمونه)
    print("-" * 100)
    print("CLEAN TRADES — SAMPLE (first 20 by entry date)")
    print("-" * 100)
    print(f"{'Symbol':<12} {'Signal':<10} {'Entry':<10} {'Exit':<10} "
          f"{'Return':>9}  {'Reason':<26}")
    print("-" * 130)
    for t in sorted(clean, key=lambda x: x["entry_date"])[:20]:
        print(f"{t['symbol']:<12} {t['signal_date']:<10} {t['entry_date']:<10} "
              f"{t['exit_date']:<10} {t['return_pct']:>+8.2f}%  "
              f"{t['reason']:<26}")
    print()

    # جمع‌بندی نهایی
    print("=" * 100)
    print("SUMMARY & INTERPRETATION")
    print("=" * 100)
    print()

    if len(affected) == 0:
        print("✅ هیچ معامله‌ای در همسایگی CAها نبوده.")
        print("   Backtest V5B.1 SAFE از این نظر پاک است.")
    elif len(affected) <= 5:
        print(f"⚠️  فقط {len(affected)} معامله ({len(affected)/len(trades)*100:.1f}%) آلوده است.")
        print("   تأثیر احتمالاً کم است (< 5% از بازده کل).")
        print("   Fix اختیاری — می‌توان با آن زندگی کرد.")
    elif len(affected) <= 15:
        print(f"🟡 {len(affected)} معامله ({len(affected)/len(trades)*100:.1f}%) آلوده است.")
        print("   تأثیر معنادار است. Fix توصیه می‌شود.")
    else:
        print(f"🔴 {len(affected)} معامله ({len(affected)/len(trades)*100:.1f}%) آلوده است.")
        print("   تأثیر جدی است. Fix الزامی است.")
        print("   نتیجه Backtest فعلی را نمی‌توان معتبر دانست.")

    print()
    print("نکته: این گزارش فقط در سطح per-trade است.")
    print("برای اثر portfolio-level، باید شبیه‌سازی کامل اجرا شود.")
    print()


# ============================================================================
# Main
# ============================================================================
def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        trades, ca_events = run_diagnostic(conn)
        print_report(trades, ca_events)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
