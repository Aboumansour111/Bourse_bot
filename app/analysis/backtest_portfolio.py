import sqlite3
import math
import csv
from collections import defaultdict
from datetime import datetime

DB_PATH = "/opt/bourse-bot/data/bourse.db"

# =========================
# CONFIG
# =========================

INITIAL_CAPITAL = 5_200_000.0

CASH_RESERVE_PCT = 0.20
MAX_POSITIONS = 3

ROUND_TRIP_COST = 0.007
ENTRY_COST = ROUND_TRIP_COST / 2
EXIT_COST = ROUND_TRIP_COST / 2

MAX_HOLD_DAYS = 10

STOP_ATR_MULT = 1.5
TARGET_ATR_MULT = 2.0

MIN_HISTORY = 200

MIN_BREADTH = 0.42

# اگر ارزش معامله از این کمتر باشد، معامله انجام نمی‌شود
MIN_TRADE_VALUE = 100_000.0

# =========================
# INDICATORS
# =========================


def sma(values, period):
    if len(values) < period:
        return None

    return sum(values[-period:]) / period


def ema_series(values, period):
    if len(values) < period:
        return []

    multiplier = 2 / (period + 1)

    ema = sum(values[:period]) / period
    result = [ema]

    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
        result.append(ema)

    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]

        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def macd_histogram(values):
    if len(values) < 35:
        return None

    ema12 = ema_series(values, 12)
    ema26 = ema_series(values, 26)

    if not ema12 or not ema26:
        return None

    # Align EMA12 with EMA26
    offset = len(ema12) - len(ema26)

    if offset < 0:
        return None

    macd_line = []

    for i in range(len(ema26)):
        macd_line.append(
            ema12[i + offset] - ema26[i]
        )

    if len(macd_line) < 9:
        return None

    signal = ema_series(macd_line, 9)

    if not signal:
        return None

    macd_value = macd_line[-1]
    signal_value = signal[-1]

    return macd_value - signal_value


def atr(highs, lows, closes, period=14):
    if len(closes) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(closes)):
        high = highs[i]
        low = lows[i]
        previous_close = closes[i - 1]

        tr = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )

        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    return sum(true_ranges[-period:]) / period


def volume_ratio(volumes, period=20):
    if len(volumes) < period + 1:
        return None

    average_volume = sum(volumes[-period - 1:-1]) / period

    if average_volume <= 0:
        return None

    return volumes[-1] / average_volume


# =========================
# TECHNICAL SIGNAL
# =========================


def technical_signal(closes, highs, lows, volumes):
    if len(closes) < MIN_HISTORY:
        return None

    sma20 = sma(closes, 20)
    sma50 = sma(closes, 50)
    sma200 = sma(closes, 200)

    ema20_series = ema_series(closes, 20)
    ema50_series = ema_series(closes, 50)

    if (
        sma20 is None
        or sma50 is None
        or sma200 is None
        or not ema20_series
        or not ema50_series
    ):
        return None

    ema20 = ema20_series[-1]
    ema50 = ema50_series[-1]

    current_price = closes[-1]

    trend_score = 0

    if current_price > sma20:
        trend_score += 1

    if current_price > sma50:
        trend_score += 1

    if current_price > sma200:
        trend_score += 1

    if ema20 > ema50:
        trend_score += 1

    current_rsi = rsi(closes, 14)

    if current_rsi is None:
        return None

    current_macd = macd_histogram(closes)

    if current_macd is None:
        return None

    current_volume_ratio = volume_ratio(volumes)

    if current_volume_ratio is None:
        return None

    current_atr = atr(
        highs,
        lows,
        closes,
        14,
    )

    if current_atr is None or current_atr <= 0:
        return None

    quality = 0

    # Trend / 25
    if trend_score >= 4:
        quality += 25
    elif trend_score == 3:
        quality += 20
    elif trend_score == 2:
        quality += 10

    # RSI / 20
    if 50 <= current_rsi <= 65:
        quality += 20
    elif 65 < current_rsi <= 70:
        quality += 14
    elif 70 < current_rsi <= 75:
        quality += 7
    elif current_rsi > 75:
        quality -= 5
    else:
        quality += 3

    # MACD / 20
    if current_macd > 0:
        quality += 20
    else:
        quality -= 5

    # Volume / 15
    if 1.2 <= current_volume_ratio <= 3:
        quality += 15
    elif 1 <= current_volume_ratio < 1.2:
        quality += 10
    elif 3 < current_volume_ratio <= 5:
        quality += 10
    elif 5 < current_volume_ratio <= 8:
        quality += 4
    elif current_volume_ratio > 8:
        quality -= 5
    else:
        quality += 2

    # Eligibility
    if trend_score < 3:
        return None

    if current_macd <= 0:
        return None

    if current_rsi >= 75:
        return None

    if current_volume_ratio < 1 or current_volume_ratio > 5:
        return None

    if quality < 70:
        return None

    return {
        "quality": float(max(0, min(100, quality))),
        "rsi": current_rsi,
        "macd": current_macd,
        "volume_ratio": current_volume_ratio,
        "atr": current_atr,
        "trend_score": trend_score,
        "price": current_price,
    }


# =========================
# DATABASE
# =========================


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_symbols(conn):
    rows = conn.execute(
        """
        SELECT inscode, symbol
        FROM symbols
        WHERE active = 1
        ORDER BY symbol
        """
    ).fetchall()

    return [
        {
            "inscode": str(row["inscode"]),
            "symbol": row["symbol"],
        }
        for row in rows
    ]


def load_prices(conn):
    rows = conn.execute(
        """
        SELECT
            inscode,
            trade_date,
            close_price,
            high_price,
            low_price,
            volume
        FROM daily_prices
        ORDER BY trade_date, inscode
        """
    ).fetchall()

    data = defaultdict(list)

    for row in rows:
        inscode = str(row["inscode"])

        close = float(row["close_price"] or 0)

        if close <= 0:
            continue

        high = float(row["high_price"] or 0)
        low = float(row["low_price"] or 0)
        volume = float(row["volume"] or 0)

        # بعضی داده‌های TSETMC high/low = 0 دارند.
        # در این حالت close را جایگزین می‌کنیم.
        if high <= 0:
            high = close

        if low <= 0:
            low = close

        data[inscode].append(
            {
                "date": str(row["trade_date"]),
                "close": close,
                "high": high,
                "low": low,
                "volume": volume,
            }
        )

    return data


# =========================
# MARKET BREADTH
# =========================


def build_breadth_map(price_data):
    daily = defaultdict(
        lambda: {
            "positive": 0,
            "negative": 0,
            "unchanged": 0,
        }
    )

    for rows in price_data.values():

        for i in range(1, len(rows)):

            today = rows[i]
            yesterday = rows[i - 1]

            current = today["close"]
            previous = yesterday["close"]

            if previous <= 0:
                continue

            if current > previous:
                daily[today["date"]]["positive"] += 1

            elif current < previous:
                daily[today["date"]]["negative"] += 1

            else:
                daily[today["date"]]["unchanged"] += 1

    result = {}

    for date, values in daily.items():

        positive = values["positive"]
        negative = values["negative"]
        unchanged = values["unchanged"]

        total = positive + negative + unchanged

        if total == 0:
            continue

        breadth = positive / total

        result[date] = {
            "positive": positive,
            "negative": negative,
            "unchanged": unchanged,
            "breadth": breadth,
        }

    return result


# =========================
# CANDIDATE GENERATION
# =========================


def generate_candidates(price_data, symbols_by_code, breadth_map):

    candidates = defaultdict(list)

    total_symbols = len(price_data)
    processed = 0

    print()
    print("Generating historical candidates...")
    print()

    for inscode, rows in price_data.items():

        processed += 1

        symbol = symbols_by_code.get(
            inscode,
            inscode,
        )

        if len(rows) < MIN_HISTORY + 2:
            continue

        for i in range(MIN_HISTORY, len(rows)):

            signal_date = rows[i]["date"]

            breadth = breadth_map.get(signal_date)

            if not breadth:
                continue

            if breadth["breadth"] < MIN_BREADTH:
                continue

            history = rows[: i + 1]

            closes = [x["close"] for x in history]
            highs = [x["high"] for x in history]
            lows = [x["low"] for x in history]
            volumes = [x["volume"] for x in history]

            signal = technical_signal(
                closes,
                highs,
                lows,
                volumes,
            )

            if not signal:
                continue

            candidates[signal_date].append(
                {
                    "inscode": inscode,
                    "symbol": symbol,
                    "date": signal_date,
                    "price": signal["price"],
                    "quality": signal["quality"],
                    "atr": signal["atr"],
                    "rsi": signal["rsi"],
                    "macd": signal["macd"],
                    "volume_ratio": signal["volume_ratio"],
                    "trend_score": signal["trend_score"],
                }
            )

        if processed % 50 == 0 or processed == total_symbols:
            print(
                f"\rProcessed: {processed}/{total_symbols}",
                end="",
                flush=True,
            )

    print()
    print(
        f"Candidate dates: {len(candidates)}"
    )

    return candidates


# =========================
# POSITION SIZING
# =========================


def calculate_position_size(
    cash,
    equity,
    available_slots,
    candidate,
):
    if available_slots <= 0:
        return 0.0

    reserve = equity * CASH_RESERVE_PCT

    investable_cash = cash - reserve

    if investable_cash <= 0:
        return 0.0

    # وزن کیفیت
    quality = max(
        0.0,
        min(
            100.0,
            candidate["quality"],
        ),
    )

    # ریسک
    atr_pct = (
        candidate["atr"] / candidate["price"]
        if candidate["price"] > 0
        else 1
    )

    if atr_pct <= 0.02:
        risk_factor = 1.0
    elif atr_pct <= 0.04:
        risk_factor = 0.90
    elif atr_pct <= 0.06:
        risk_factor = 0.75
    elif atr_pct <= 0.10:
        risk_factor = 0.60
    else:
        risk_factor = 0.40

    quality_factor = 0.75 + (
        quality / 100.0
    ) * 0.25

    # سهم پایه از سرمایه قابل سرمایه‌گذاری
    base_allocation = investable_cash / available_slots

    allocation = (
        base_allocation
        * quality_factor
        * risk_factor
    )

    # بیشتر از پول موجود خرج نکن
    allocation = min(
        allocation,
        investable_cash,
        cash - reserve,
    )

    if allocation < MIN_TRADE_VALUE:
        return 0.0

    return allocation


# =========================
# PORTFOLIO ENGINE
# =========================


def run_backtest(
    price_data,
    candidates,
    symbols_by_code,
    breadth_map,
):

    # date -> code -> row
    market_by_date = defaultdict(dict)

    all_dates = set()

    for inscode, rows in price_data.items():

        for row in rows:
            market_by_date[row["date"]][inscode] = row
            all_dates.add(row["date"])

    dates = sorted(all_dates)

    cash = INITIAL_CAPITAL

    positions = {}

    trades = []

    equity_curve = []

    peak_equity = INITIAL_CAPITAL
    max_drawdown = 0.0

    max_positions_seen = 0

    total_buy_count = 0
    total_sell_count = 0

    for day_index, date in enumerate(dates):

        day_market = market_by_date.get(
            date,
            {},
        )

        # =========================
        # EXIT POSITIONS
        # =========================

        for inscode in list(positions.keys()):

            position = positions[inscode]

            row = day_market.get(inscode)

            if not row:
                continue

            close = row["close"]
            high = row["high"]
            low = row["low"]

            position["days_held"] += 1

            exit_reason = None
            exit_price = None

            # Stop/Target
            stop_hit = low <= position["stop"]
            target_hit = high >= position["target"]

            if stop_hit and target_hit:
                # محافظه‌کارانه:
                # اگر هر دو در یک روز اتفاق افتادند،
                # Stop را اول فرض می‌کنیم.
                exit_reason = "STOP_AND_TARGET_SAME_DAY"
                exit_price = position["stop"]

            elif stop_hit:
                exit_reason = "STOP"
                exit_price = position["stop"]

            elif target_hit:
                exit_reason = "TARGET"
                exit_price = position["target"]

            elif position["days_held"] >= MAX_HOLD_DAYS:
                exit_reason = "TIME"
                exit_price = close

            if exit_reason is None:
                continue

            gross_sell_value = (
                position["quantity"]
                * exit_price
            )

            exit_fee = (
                gross_sell_value
                * EXIT_COST
            )

            net_sell_value = (
                gross_sell_value
                - exit_fee
            )

            cash += net_sell_value

            invested = position["total_cost"]

            pnl = (
                net_sell_value
                - invested
            )

            return_pct = (
                pnl / invested * 100
                if invested > 0
                else 0
            )

            trades.append(
                {
                    "symbol": position["symbol"],
                    "inscode": inscode,
                    "entry_date": position["entry_date"],
                    "exit_date": date,
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "quantity": position["quantity"],
                    "gross_entry_value": position["gross_entry_value"],
                    "entry_fee": position["entry_fee"],
                    "gross_exit_value": gross_sell_value,
                    "exit_fee": exit_fee,
                    "total_cost": invested,
                    "pnl": pnl,
                    "return_pct": return_pct,
                    "quality": position["quality"],
                    "atr": position["atr"],
                    "stop": position["stop"],
                    "target": position["target"],
                    "days_held": position["days_held"],
                    "exit_reason": exit_reason,
                }
            )

            del positions[inscode]

            total_sell_count += 1

        # =========================
        # NEW ENTRIES
        # =========================

        day_candidates = candidates.get(
            date,
            [],
        )

        # قبلاً نگهداری شده‌ها را حذف کن
        day_candidates = [
            x
            for x in day_candidates
            if x["inscode"] not in positions
        ]

        # بهترین‌ها اول
        day_candidates.sort(
            key=lambda x: (
                x["quality"],
                -(
                    x["atr"] / x["price"]
                    if x["price"] > 0
                    else 999
                ),
            ),
            reverse=True,
        )

        available_slots = (
            MAX_POSITIONS
            - len(positions)
        )

        for candidate in day_candidates:

            if available_slots <= 0:
                break

            # محدودیت تعداد پوزیشن
            if candidate["inscode"] in positions:
                continue

            current_row = day_market.get(
                candidate["inscode"]
            )

            if not current_row:
                continue

            entry_price = current_row["close"]

            if entry_price <= 0:
                continue

            # ATR مربوط به همان روز سیگنال
            atr_value = candidate["atr"]

            stop = (
                entry_price
                - STOP_ATR_MULT * atr_value
            )

            target = (
                entry_price
                + TARGET_ATR_MULT * atr_value
            )

            if stop <= 0:
                continue

            equity_before = cash

            for code, pos in positions.items():
                row = day_market.get(code)

                if row:
                    equity_before += (
                        pos["quantity"]
                        * row["close"]
                    )

            allocation = calculate_position_size(
                cash=cash,
                equity=equity_before,
                available_slots=available_slots,
                candidate=candidate,
            )

            if allocation <= 0:
                continue

            # مقدار خرید
            quantity = math.floor(
                allocation / entry_price
            )

            if quantity <= 0:
                continue

            gross_entry_value = (
                quantity * entry_price
            )

            entry_fee = (
                gross_entry_value
                * ENTRY_COST
            )

            total_cost = (
                gross_entry_value
                + entry_fee
            )

            if total_cost > cash:
                continue

            if gross_entry_value < MIN_TRADE_VALUE:
                continue

            cash -= total_cost

            positions[candidate["inscode"]] = {
                "symbol": candidate["symbol"],
                "entry_date": date,
                "entry_price": entry_price,
                "quantity": quantity,
                "gross_entry_value": gross_entry_value,
                "entry_fee": entry_fee,
                "total_cost": total_cost,
                "quality": candidate["quality"],
                "atr": atr_value,
                "stop": stop,
                "target": target,
                "days_held": 0,
            }

            total_buy_count += 1

            available_slots -= 1

        # =========================
        # DAILY EQUITY
        # =========================

        market_value = 0.0

        for inscode, position in positions.items():

            row = day_market.get(inscode)

            if row:
                market_value += (
                    position["quantity"]
                    * row["close"]
                )
            else:
                market_value += (
                    position["quantity"]
                    * position["entry_price"]
                )

        equity = cash + market_value

        peak_equity = max(
            peak_equity,
            equity,
        )

        drawdown = (
            (equity - peak_equity)
            / peak_equity
            if peak_equity > 0
            else 0
        )

        max_drawdown = min(
            max_drawdown,
            drawdown,
        )

        max_positions_seen = max(
            max_positions_seen,
            len(positions),
        )

        exposure = (
            market_value / equity
            if equity > 0
            else 0
        )

        equity_curve.append(
            {
                "date": date,
                "cash": cash,
                "market_value": market_value,
                "equity": equity,
                "drawdown_pct": drawdown * 100,
                "positions": len(positions),
                "exposure_pct": exposure * 100,
            }
        )

        if day_index % 100 == 0:
            print(
                f"\rBacktest: {day_index + 1}/{len(dates)} "
                f"| {date} "
                f"| Equity: {equity:,.0f} "
                f"| Positions: {len(positions)}",
                end="",
                flush=True,
            )

    print()

    # =========================
    # FORCE CLOSE REMAINING
    # =========================

    if dates:

        final_date = dates[-1]
        final_market = market_by_date.get(
            final_date,
            {},
        )

        for inscode in list(positions.keys()):

            position = positions[inscode]

            row = final_market.get(
                inscode
            )

            if row:
                exit_price = row["close"]
            else:
                exit_price = position["entry_price"]

            gross_sell_value = (
                position["quantity"]
                * exit_price
            )

            exit_fee = (
                gross_sell_value
                * EXIT_COST
            )

            net_sell_value = (
                gross_sell_value
                - exit_fee
            )

            cash += net_sell_value

            pnl = (
                net_sell_value
                - position["total_cost"]
            )

            return_pct = (
                pnl
                / position["total_cost"]
                * 100
                if position["total_cost"] > 0
                else 0
            )

            trades.append(
                {
                    "symbol": position["symbol"],
                    "inscode": inscode,
                    "entry_date": position["entry_date"],
                    "exit_date": final_date,
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "quantity": position["quantity"],
                    "gross_entry_value": position["gross_entry_value"],
                    "entry_fee": position["entry_fee"],
                    "gross_exit_value": gross_sell_value,
                    "exit_fee": exit_fee,
                    "total_cost": position["total_cost"],
                    "pnl": pnl,
                    "return_pct": return_pct,
                    "quality": position["quality"],
                    "atr": position["atr"],
                    "stop": position["stop"],
                    "target": position["target"],
                    "days_held": position["days_held"],
                    "exit_reason": "END_OF_BACKTEST",
                }
            )

            del positions[inscode]

    final_equity = cash

    return (
        trades,
        equity_curve,
        final_equity,
        max_drawdown,
        max_positions_seen,
        total_buy_count,
        total_sell_count,
    )


# =========================
# METRICS
# =========================


def calculate_metrics(
    trades,
    equity_curve,
    final_equity,
    max_drawdown,
):

    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0,
            "avg_return": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "profit_factor": 0,
            "expectancy": 0,
            "total_pnl": final_equity - INITIAL_CAPITAL,
            "total_return": (
                (final_equity / INITIAL_CAPITAL - 1)
                * 100
            ),
            "max_drawdown": max_drawdown * 100,
        }

    wins = [
        t for t in trades
        if t["pnl"] > 0
    ]

    losses = [
        t for t in trades
        if t["pnl"] < 0
    ]

    gross_profit = sum(
        t["pnl"]
        for t in wins
    )

    gross_loss = abs(
        sum(
            t["pnl"]
            for t in losses
        )
    )

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    win_rate = (
        len(wins)
        / len(trades)
        * 100
    )

    avg_return = (
        sum(
            t["return_pct"]
            for t in trades
        )
        / len(trades)
    )

    avg_win = (
        sum(
            t["return_pct"]
            for t in wins
        )
        / len(wins)
        if wins
        else 0
    )

    avg_loss = (
        sum(
            t["return_pct"]
            for t in losses
        )
        / len(losses)
        if losses
        else 0
    )

    expectancy = (
        win_rate / 100 * avg_win
        + (1 - win_rate / 100) * avg_loss
    )

    total_pnl = (
        final_equity
        - INITIAL_CAPITAL
    )

    total_return = (
        final_equity
        / INITIAL_CAPITAL
        - 1
    ) * 100

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "avg_return": avg_return,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "total_pnl": total_pnl,
        "total_return": total_return,
        "max_drawdown": max_drawdown * 100,
    }


# =========================
# CSV OUTPUT
# =========================


def save_csv(filename, rows):

    if not rows:
        return

    with open(
        filename,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=list(rows[0].keys()),
        )

        writer.writeheader()
        writer.writerows(rows)


# =========================
# REPORT
# =========================


def print_report(
    metrics,
    trades,
    equity_curve,
    max_positions_seen,
    total_buy_count,
    total_sell_count,
):

    print()
    print("=" * 70)
    print("PORTFOLIO BACKTEST")
    print("=" * 70)

    print(
        f"Initial capital:     "
        f"{INITIAL_CAPITAL:,.0f} Toman"
    )

    print(
        f"Final equity:        "
        f"{INITIAL_CAPITAL + metrics['total_pnl']:,.0f} Toman"
    )

    print(
        f"Total P&L:           "
        f"{metrics['total_pnl']:,.0f} Toman"
    )

    print(
        f"Total return:        "
        f"{metrics['total_return']:.2f}%"
    )

    print()

    print(
        f"Trades:              "
        f"{metrics['trades']}"
    )

    print(
        f"Wins:                "
        f"{metrics['wins']}"
    )

    print(
        f"Losses:              "
        f"{metrics['losses']}"
    )

    print(
        f"Win rate:            "
        f"{metrics['win_rate']:.2f}%"
    )

    print(
        f"Average return:      "
        f"{metrics['avg_return']:.2f}%"
    )

    print(
        f"Average win:         "
        f"{metrics['avg_win']:.2f}%"
    )

    print(
        f"Average loss:        "
        f"{metrics['avg_loss']:.2f}%"
    )

    print(
        f"Profit factor:       "
        f"{metrics['profit_factor']:.2f}"
    )

    print(
        f"Expectancy/trade:    "
        f"{metrics['expectancy']:.2f}%"
    )

    print(
        f"Max drawdown:        "
        f"{metrics['max_drawdown']:.2f}%"
    )

    print()

    print(
        f"Max concurrent:      "
        f"{max_positions_seen}"
    )

    print(
        f"Buy transactions:    "
        f"{total_buy_count}"
    )

    print(
        f"Sell transactions:   "
        f"{total_sell_count}"
    )

    print()

    if equity_curve:

        max_equity = max(
            x["equity"]
            for x in equity_curve
        )

        min_equity = min(
            x["equity"]
            for x in equity_curve
        )

        avg_exposure = (
            sum(
                x["exposure_pct"]
                for x in equity_curve
            )
            / len(equity_curve)
        )

        print(
            f"Peak equity:         "
            f"{max_equity:,.0f}"
        )

        print(
            f"Lowest equity:       "
            f"{min_equity:,.0f}"
        )

        print(
            f"Average exposure:    "
            f"{avg_exposure:.2f}%"
        )

    print()
    print("Exit reasons:")

    reasons = defaultdict(int)

    for trade in trades:
        reasons[
            trade["exit_reason"]
        ] += 1

    for reason, count in sorted(
        reasons.items(),
        key=lambda x: x[1],
        reverse=True,
    ):
        print(
            f"  {reason}: {count}"
        )

    print()
    print("Best trades:")

    for trade in sorted(
        trades,
        key=lambda x: x["return_pct"],
        reverse=True,
    )[:10]:

        print(
            f"  {trade['symbol']} | "
            f"{trade['entry_date']} -> "
            f"{trade['exit_date']} | "
            f"{trade['return_pct']:.2f}% | "
            f"{trade['exit_reason']}"
        )

    print()
    print("Worst trades:")

    for trade in sorted(
        trades,
        key=lambda x: x["return_pct"],
    )[:10]:

        print(
            f"  {trade['symbol']} | "
            f"{trade['entry_date']} -> "
            f"{trade['exit_date']} | "
            f"{trade['return_pct']:.2f}% | "
            f"{trade['exit_reason']}"
        )

    print()
    print("=" * 70)


# =========================
# MAIN
# =========================


def main():

    started = datetime.now()

    print("=" * 70)
    print("REAL CAPITAL PORTFOLIO BACKTEST")
    print("=" * 70)

    print(
        f"Initial capital: {INITIAL_CAPITAL:,.0f}"
    )

    print(
        f"Cash reserve: {CASH_RESERVE_PCT * 100:.0f}%"
    )

    print(
        f"Max positions: {MAX_POSITIONS}"
    )

    print(
        f"Round trip cost: {ROUND_TRIP_COST * 100:.2f}%"
    )

    print(
        f"Stop: {STOP_ATR_MULT} ATR"
    )

    print(
        f"Target: {TARGET_ATR_MULT} ATR"
    )

    print(
        f"Max hold: {MAX_HOLD_DAYS} sessions"
    )

    conn = get_connection()

    print()
    print("Loading symbols...")

    symbols = load_symbols(conn)

    symbols_by_code = {
        x["inscode"]: x["symbol"]
        for x in symbols
    }

    print(
        f"Active symbols: {len(symbols)}"
    )

    print()
    print("Loading daily prices...")

    price_data = load_prices(conn)

    print(
        f"Symbols with price data: "
        f"{len(price_data)}"
    )

    conn.close()

    print()
    print("Building historical market breadth...")

    breadth_map = build_breadth_map(
        price_data
    )

    print(
        f"Breadth dates: "
        f"{len(breadth_map)}"
    )

    candidates = generate_candidates(
        price_data,
        symbols_by_code,
        breadth_map,
    )

    total_candidates = sum(
        len(x)
        for x in candidates.values()
    )

    print()
    print(
        f"Total historical candidates: "
        f"{total_candidates}"
    )

    (
        trades,
        equity_curve,
        final_equity,
        max_drawdown,
        max_positions_seen,
        total_buy_count,
        total_sell_count,
    ) = run_backtest(
        price_data,
        candidates,
        symbols_by_code,
        breadth_map,
    )

    metrics = calculate_metrics(
        trades,
        equity_curve,
        final_equity,
        max_drawdown,
    )

    print_report(
        metrics,
        trades,
        equity_curve,
        max_positions_seen,
        total_buy_count,
        total_sell_count,
    )

    save_csv(
        "/opt/bourse-bot/data/backtest_portfolio_trades.csv",
        trades,
    )

    save_csv(
        "/opt/bourse-bot/data/backtest_portfolio_equity.csv",
        equity_curve,
    )

    elapsed = (
        datetime.now()
        - started
    ).total_seconds()

    print()
    print(
        f"Trades CSV: "
        f"/opt/bourse-bot/data/backtest_portfolio_trades.csv"
    )

    print(
        f"Equity CSV: "
        f"/opt/bourse-bot/data/backtest_portfolio_equity.csv"
    )

    print(
        f"Elapsed: {elapsed:.1f} seconds"
    )

    print()


if __name__ == "__main__":
    main()
