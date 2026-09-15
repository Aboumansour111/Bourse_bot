import argparse
import os
import sqlite3

import requests
from dotenv import load_dotenv


DB_PATH = "/opt/bourse-bot/data/bourse.db"
GATEWAY_URL = "http://127.0.0.1:18080"

load_dotenv("/opt/bourse-bot/.env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_CHAT_ID = os.getenv("ALLOWED_CHAT_ID")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_current_price(inscode):
    try:
        response = requests.get(
            f"{GATEWAY_URL}/quote/{inscode}",
            timeout=10,
        )
        response.raise_for_status()

        result = response.json()

        if result.get("status") != "ok":
            return None

        data = result.get("data") or {}
        price = data.get("pDrCotVal")

        if price is None:
            return None

        return float(price)

    except Exception as exc:
        print(f"Gateway quote error for {inscode}: {exc}")
        return None


def get_positions():
    conn = get_conn()

    rows = conn.execute("""
        SELECT
            p.inscode,
            p.symbol,
            p.quantity,
            p.average_price
        FROM portfolio p
        WHERE p.quantity > 0
        ORDER BY p.symbol
    """).fetchall()

    conn.close()

    return rows


def get_decision(inscode):
    conn = get_conn()

    row = conn.execute("""
        SELECT
            symbol,
            action,
            market_state,
            risk_level,
            close_price,
            stop_loss,
            target1,
            target2,
            reason
        FROM decision_results
        WHERE inscode = ?
        ORDER BY trade_date DESC, updated_at DESC
        LIMIT 1
    """, (inscode,)).fetchone()

    conn.close()

    return row


def get_position_level(inscode):
    conn = get_conn()

    row = conn.execute("""
        SELECT *
        FROM position_levels
        WHERE inscode = ?
    """, (inscode,)).fetchone()

    conn.close()

    return row


def save_position_level(
    inscode,
    symbol,
    quantity,
    average_price,
    stop_loss,
    target1,
    target2,
    last_state="INIT",
):
    conn = get_conn()

    conn.execute("""
        INSERT INTO position_levels (
            inscode,
            symbol,
            entry_quantity,
            entry_average_price,
            stop_loss,
            target1,
            target2,
            last_state,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(inscode)
        DO UPDATE SET
            symbol = excluded.symbol,
            entry_quantity = excluded.entry_quantity,
            entry_average_price = excluded.entry_average_price,
            stop_loss = excluded.stop_loss,
            target1 = excluded.target1,
            target2 = excluded.target2,
            last_state = excluded.last_state,
            updated_at = CURRENT_TIMESTAMP
    """, (
        inscode,
        symbol,
        quantity,
        average_price,
        stop_loss,
        target1,
        target2,
        last_state,
    ))

    conn.commit()
    conn.close()


def update_state(inscode, state, price):
    conn = get_conn()

    conn.execute("""
        UPDATE position_levels
        SET
            last_state = ?,
            last_price = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE inscode = ?
    """, (
        state,
        price,
        inscode,
    ))

    conn.commit()
    conn.close()


def initialize_position_after_buy(
    inscode,
    symbol,
    quantity,
    average_price,
):
    existing = get_position_level(inscode)

    if existing:
        print(
            f"{symbol}: existing position levels preserved."
        )
        return existing

    decision = get_decision(inscode)

    if not decision:
        print(
            f"{symbol}: no decision_results available; "
            f"position levels will be initialized later."
        )
        return None

    save_position_level(
        inscode=int(inscode),
        symbol=symbol,
        quantity=int(quantity),
        average_price=float(average_price),
        stop_loss=decision["stop_loss"],
        target1=decision["target1"],
        target2=decision["target2"],
        last_state="INIT",
    )

    print(
        f"{symbol}: position levels initialized after buy."
    )

    return get_position_level(inscode)


def determine_state(price, levels, decision):
    stop_loss = levels["stop_loss"]
    target1 = levels["target1"]
    target2 = levels["target2"]

    action = decision["action"] if decision else None

    if stop_loss is not None and price <= float(stop_loss):
        return "STOP_LOSS"

    if target2 is not None and price >= float(target2):
        return "TARGET2"

    if target1 is not None and price >= float(target1):
        return "TARGET1"

    if action == "EXIT":
        return "EXIT"

    if action == "REDUCE":
        return "REDUCE"

    return "HOLD"


def state_label(state):
    return {
        "INIT": "شروع پایش",
        "HOLD": "نگهداری",
        "REDUCE": "کاهش موقعیت",
        "TARGET1": "هدف اول",
        "TARGET2": "هدف دوم",
        "EXIT": "فروش کامل",
        "STOP_LOSS": "حد ضرر",
    }.get(state, state)


def action_text(state):
    return {
        "HOLD": "نگهداری سهم",
        "REDUCE": "کاهش بخشی از موقعیت",
        "TARGET1": "برداشت بخشی از سود",
        "TARGET2": "بررسی فروش بخش عمده/کامل موقعیت",
        "EXIT": "فروش کامل سهم",
        "STOP_LOSS": "فروش به دلیل شکست حد ضرر",
    }.get(state, "بررسی وضعیت")


def format_price(value):
    if value is None:
        return "-"

    return f"{float(value):,.0f}"


def build_message(position, price, levels, decision, state):
    symbol = position["symbol"]
    quantity = int(position["quantity"])
    average = float(position["average_price"])

    pnl = (price - average) * quantity

    pnl_percent = (
        ((price - average) / average) * 100
        if average > 0
        else 0
    )

    action = decision["action"] if decision else "-"
    market_state = decision["market_state"] if decision else "-"
    risk = decision["risk_level"] if decision else "-"

    lines = [
        "📊 هشدار مدیریت موقعیت",
        "",
        f"نماد: {symbol}",
        f"تعداد: {quantity:,}",
        f"میانگین خرید: {format_price(average)}",
        f"قیمت فعلی: {format_price(price)}",
        f"بازدهی: {pnl_percent:+.2f}%",
        f"سود/زیان شناور: {pnl:+,.0f}",
        "",
        f"وضعیت: {state_label(state)}",
        f"➡️ پیشنهاد: {action_text(state)}",
        "",
        f"سیگنال تحلیل: {action}",
        f"وضعیت بازار: {market_state}",
        f"ریسک: {risk}",
        "",
        f"حد ضرر: {format_price(levels['stop_loss'])}",
        f"هدف ۱: {format_price(levels['target1'])}",
        f"هدف ۲: {format_price(levels['target2'])}",
    ]

    if decision and decision["reason"]:
        lines.extend([
            "",
            "دلیل تحلیل:",
            decision["reason"],
        ])

    lines.extend([
        "",
        "⚠️ این پیام فقط پیشنهاد است و هیچ معامله‌ای توسط ربات انجام نمی‌شود.",
    ])

    return "\n".join(lines)


def send_telegram(message):
    if not BOT_TOKEN or not ALLOWED_CHAT_ID:
        print("Telegram configuration missing.")
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": ALLOWED_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )

        response.raise_for_status()

        result = response.json()

        if not result.get("ok"):
            print("Telegram API error:", result)
            return False

        return True

    except Exception as exc:
        print(f"Telegram send error: {exc}")
        return False


def process_position(
    position,
    dry_run=False,
    initialize_only=False,
):
    inscode = int(position["inscode"])
    symbol = position["symbol"]

    decision = get_decision(inscode)

    if not decision:
        print(f"{symbol}: no decision_results")
        return

    levels = get_position_level(inscode)

    initialized = False

    if not levels:
        save_position_level(
            inscode=inscode,
            symbol=symbol,
            quantity=int(position["quantity"]),
            average_price=float(position["average_price"]),
            stop_loss=decision["stop_loss"],
            target1=decision["target1"],
            target2=decision["target2"],
            last_state="INIT",
        )

        levels = get_position_level(inscode)
        initialized = True

        print(
            f"{symbol}: position levels initialized "
            f"from current decision_results."
        )

    price = get_current_price(inscode)

    if price is None:
        print(f"{symbol}: live price unavailable")
        return

    state = determine_state(
        price,
        levels,
        decision,
    )

    previous_state = levels["last_state"]

    print()
    print("=" * 60)
    print(symbol)
    print(f"Live price : {format_price(price)}")
    print(f"Average    : {format_price(position['average_price'])}")
    print(f"Stop       : {format_price(levels['stop_loss'])}")
    print(f"Target 1   : {format_price(levels['target1'])}")
    print(f"Target 2   : {format_price(levels['target2'])}")
    print(f"Decision   : {decision['action']}")
    print(f"State      : {previous_state} -> {state}")
    print("=" * 60)

    if initialized:
        update_state(
            inscode,
            state,
            price,
        )

        print(
            f"{symbol}: initial state recorded; "
            f"no alert sent."
        )

        return

    if initialize_only:
        return

    if state == previous_state:
        update_state(
            inscode,
            state,
            price,
        )

        print(
            f"{symbol}: no state change; no alert."
        )

        return

    message = build_message(
        position,
        price,
        levels,
        decision,
        state,
    )

    if dry_run:
        print()
        print("----- DRY RUN TELEGRAM MESSAGE -----")
        print(message)
        print("----- END DRY RUN -----")
    else:
        if send_telegram(message):
            print(f"{symbol}: Telegram alert sent.")
        else:
            print(f"{symbol}: Telegram alert failed.")

    update_state(
        inscode,
        state,
        price,
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print alerts instead of sending them.",
    )

    parser.add_argument(
        "--initialize-only",
        action="store_true",
        help="Create missing position levels without sending alerts.",
    )

    args = parser.parse_args()

    positions = get_positions()

    if not positions:
        print("Portfolio is empty.")
        return

    print(
        f"Position manager: {len(positions)} position(s)"
    )

    for position in positions:
        process_position(
            position,
            dry_run=args.dry_run,
            initialize_only=args.initialize_only,
        )


if __name__ == "__main__":
    main()
