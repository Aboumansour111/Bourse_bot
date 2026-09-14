import sqlite3
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

DB_PATH = "/opt/bourse-bot/data/bourse.db"
GATEWAY_URL = "http://127.0.0.1:18080"

BOT_TOKEN = "8858312738:AAGUSqXdk-tXipz99QogrtENoVBOAMuYxaU"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def format_price(value):
    if value is None:
        return "-"
    return f"{float(value):,.0f}"


def get_current_price(inscode):
    """
    دریافت مستقیم آخرین معامله از Gateway.
    pDrCotVal = آخرین قیمت معامله‌شده
    """
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ربات بورس فعال است.\n\n"
        "/signals - پیشنهادهای معاملاتی"
    )


async def signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()

    rows = conn.execute("""
        SELECT
            rank_position,
            inscode,
            symbol,
            entry_quality,
            risk_level,
            close_price,
            stop_loss,
            target1,
            target2,
            allocation,
            quantity,
            position_value
        FROM top_picks
        ORDER BY rank_position
        LIMIT 3
    """).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "در حال حاضر سیگنال خریدی وجود ندارد."
        )
        return

    lines = [
        "📊 پیشنهاد معاملاتی امروز",
        "",
    ]

    for row in rows:
        current_price = get_current_price(row["inscode"])

        lines.extend([
            f"#{row['rank_position']} {row['symbol']}",
            f"کیفیت ورود: {row['entry_quality']:.1f}",
            f"ریسک: {row['risk_level']}",
            f"قیمت مرجع: {format_price(row['close_price'])}",
            f"قیمت آخرین معامله: {format_price(current_price)}",
            f"حد ضرر: {format_price(row['stop_loss'])}",
            f"هدف ۱: {format_price(row['target1'])}",
            f"هدف ۲: {format_price(row['target2'])}",
            f"مبلغ پیشنهادی: {format_price(row['allocation'])}",
            f"تعداد: {int(row['quantity'])}",
            f"ارزش موقعیت: {format_price(row['position_value'])}",
            "",
        ])

    await update.message.reply_text("\n".join(lines))


def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("signals", signals))

    application.run_polling()


if __name__ == "__main__":
    main()
