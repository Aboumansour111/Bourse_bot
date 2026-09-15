import os
import sqlite3
import requests

from dotenv import load_dotenv
from position_manager import initialize_position_after_buy
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

DB_PATH = "/opt/bourse-bot/data/bourse.db"
GATEWAY_URL = "http://127.0.0.1:18080"


def get_current_price(inscode):
    """
    دریافت آخرین معامله مستقیم از Gateway گوشی.
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


load_dotenv("/opt/bourse-bot/.env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_CHAT_ID = os.getenv("ALLOWED_CHAT_ID")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def allowed(update):
    if not ALLOWED_CHAT_ID:
        return True

    return str(update.effective_chat.id) == str(ALLOWED_CHAT_ID)


def is_allowed(update):
    if not ALLOWED_CHAT_ID:
        return True

    if update.effective_chat is None:
        return False

    return str(update.effective_chat.id) == str(ALLOWED_CHAT_ID)


async def deny(update):
    await update.message.reply_text("دسترسی غیرمجاز.")


def format_price(value):
    if value is None:
        return "-"
    return f"{value:,.0f}"


def format_decimal(value, digits=2):
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def action_label(action):
    return {
        "BUY": "🟢 خرید",
        "ADD": "🟢 افزایش",
        "HOLD": "🟡 نگهداری",
        "WATCH": "🔵 زیر نظر",
        "REDUCE": "🟠 کاهش",
        "EXIT": "🔴 فروش کامل",
        "AVOID": "⚪ عدم ورود",
    }.get(action, action)


def risk_label(risk):
    return {
        "LOW": "کم",
        "MEDIUM": "متوسط",
        "HIGH": "زیاد",
    }.get(risk, risk or "-")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return await deny(update)

    await update.message.reply_text(
        "ربات تحلیل بورس فعال است.\n\n"
        "/signals - پیشنهادهای معاملاتی\n"
        "/market - وضعیت بازار\n"
        "/top - 10 سهم برتر\n"
        "/analyze SYMBOL - تحلیل یک نماد\n"
        "/portfolio - وضعیت پرتفوی\n"
        "/cash - موجودی نقد\n"
        "/buy نماد تعداد قیمت - ثبت خرید\n"
        "/sell نماد تعداد قیمت - ثبت فروش\n"
        "/help - راهنما"
    )


async def help_command(update, context):
    if not allowed(update):
        return await deny(update)

    await start(update, context)


async def signals(update, context):
    if not allowed(update):
        return await deny(update)

    conn = get_db()

    market = conn.execute("""
        SELECT
            market_state,
            breadth,
            positive,
            negative,
            unchanged
        FROM market_context
        ORDER BY trade_date DESC
        LIMIT 1
    """).fetchone()

    picks = conn.execute("""
        SELECT
            rank_position,
            inscode,
            symbol,
            entry_quality,
            risk_level,
            close_price,
            last_price,
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

    held = conn.execute("""
        SELECT
            d.symbol,
            d.action,
            d.score,
            d.risk_level
        FROM decision_results d
        JOIN portfolio p
            ON p.inscode = d.inscode
        WHERE p.quantity > 0
          AND d.action IN ('ADD', 'HOLD', 'REDUCE', 'EXIT')
        ORDER BY
            CASE d.action
                WHEN 'EXIT' THEN 1
                WHEN 'REDUCE' THEN 2
                WHEN 'ADD' THEN 3
                WHEN 'HOLD' THEN 4
                ELSE 5
            END,
            d.score ASC
        LIMIT 20
    """).fetchall()

    conn.close()

    lines = ["📊 پیشنهاد معاملاتی امروز"]

    if market:
        lines.extend([
            "",
            f"وضعیت بازار: {market['market_state']}",
            f"مثبت: {market['positive']} | "
            f"منفی: {market['negative']} | "
            f"بدون تغییر: {market['unchanged']}",
            f"Breadth: {market['breadth']:.2%}",
        ])

    lines.extend([
        "",
        "🟢 انتخاب‌های اصلی خرید"
    ])

    if picks:
        for row in picks:
            lines.extend([
                "",
                f"{row['rank_position']}. {row['symbol']}",
                f"کیفیت ورود: {row['entry_quality']:.1f}/100",
                f"ریسک: {risk_label(row['risk_level'])}",
                f"قیمت مرجع: {format_price(row['close_price'])}",
                f"قیمت آخرین معامله: "
                f"{format_price(get_current_price(row['inscode']))}",
                f"مبلغ پیشنهادی: {format_price(row['allocation'])}",
                f"تعداد پیشنهادی: {row['quantity']:,}",
                f"ارزش خرید: {format_price(row['position_value'])}",
                f"حد ضرر: {format_price(row['stop_loss'])}",
                f"هدف ۱: {format_price(row['target1'])}",
                f"هدف ۲: {format_price(row['target2'])}",
            ])
    else:
        lines.append("فعلاً گزینه‌ای برای خرید نهایی وجود ندارد.")

    if held:
        lines.extend([
            "",
            "📌 وضعیت سهام موجود در پرتفوی"
        ])

        for row in held:
            lines.append(
                f"{row['symbol']} → "
                f"{action_label(row['action'])} | "
                f"Score {row['score']:.1f} | "
                f"ریسک {risk_label(row['risk_level'])}"
            )
    else:
        lines.extend([
            "",
            "📌 پرتفوی",
            "هنوز سهمی در پرتفوی ثبت نشده."
        ])

    lines.extend([
        "",
        "⚠️ اعداد ورود، حد ضرر و اهداف خروجی مدل هستند "
        "و سفارش واقعی ثبت نمی‌کنند."
    ])

    text = "\n".join(lines)

    max_length = 3900

    for start_index in range(0, len(text), max_length):
        await update.message.reply_text(
            text[start_index:start_index + max_length]
        )


async def market(update, context):
    if not allowed(update):
        return await deny(update)

    conn = get_db()

    row = conn.execute("""
        SELECT *
        FROM market_context
        ORDER BY trade_date DESC
        LIMIT 1
    """).fetchone()

    conn.close()

    if not row:
        await update.message.reply_text(
            "اطلاعات بازار موجود نیست."
        )
        return

    await update.message.reply_text(
        f"وضعیت بازار: {row['market_state']}\n"
        f"سهام بررسی‌شده: {row['total_shares']}\n"
        f"مثبت: {row['positive']}\n"
        f"منفی: {row['negative']}\n"
        f"بدون تغییر: {row['unchanged']}\n"
        f"میانگین تغییر: {row['average_change_pct']:.2f}%\n"
        f"Breadth: {row['breadth']:.2%}"
    )


async def top(update, context):
    if not allowed(update):
        return await deny(update)

    conn = get_db()

    rows = conn.execute("""
        SELECT
            rank_position,
            symbol,
            final_score,
            decision
        FROM final_ranking
        ORDER BY rank_position
        LIMIT 10
    """).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "رتبه‌بندی موجود نیست."
        )
        return

    lines = ["10 سهم برتر فعلی:"]

    for row in rows:
        lines.append(
            f"{row['rank_position']}. "
            f"{row['symbol']} | "
            f"{row['final_score']:.1f} | "
            f"{row['decision']}"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


async def analyze(update, context):
    if not allowed(update):
        return await deny(update)

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/analyze فولاد"
        )
        return

    symbol = context.args[0].strip()

    conn = get_db()

    row = conn.execute("""
        SELECT
            d.*,
            s.name
        FROM decision_results d
        LEFT JOIN symbols s
            ON s.inscode = d.inscode
        WHERE d.symbol = ?
        LIMIT 1
    """, (symbol,)).fetchone()

    conn.close()

    if not row:
        await update.message.reply_text(
            f"نماد {symbol} پیدا نشد."
        )
        return

    text = (
        f"{row['symbol']}\n"
        f"{row['name'] or ''}\n\n"
        f"تصمیم: {action_label(row['action'])}\n"
        f"امتیاز: {row['score']:.1f}/100\n"
        f"ریسک: {risk_label(row['risk_level'])}\n"
        f"وضعیت بازار: {row['market_state']}\n\n"
        f"قیمت: {format_price(row['close_price'])}\n"
        f"RSI: {format_decimal(row['rsi14'])}\n"
        f"MACD: {format_decimal(row['macd_hist'])}\n"
        f"Volume Ratio: {format_decimal(row['volume_ratio'])}\n"
        f"Buyer Power: {format_decimal(row['buyer_power'])}\n"
        f"Real Flow: {format_decimal(row['real_flow_ratio'], 3)}\n"
    )

    if row["stop_loss"] is not None:
        text += (
            f"\nحد ضرر: {format_price(row['stop_loss'])}\n"
            f"هدف ۱: {format_price(row['target1'])}\n"
            f"هدف ۲: {format_price(row['target2'])}\n"
        )

    text += f"\nدلیل:\n{row['reason'] or '-'}"

    await update.message.reply_text(text)


async def portfolio(update, context):
    if not allowed(update):
        return await deny(update)

    conn = get_db()

    rows = conn.execute("""
        SELECT
            p.symbol,
            p.quantity,
            p.average_price,
            COALESCE(t.close, p.average_price) AS market_price
        FROM portfolio p
        LEFT JOIN technical_analysis t
            ON t.inscode = p.inscode
        WHERE p.quantity > 0
        ORDER BY p.symbol
    """).fetchall()

    cash_row = conn.execute(
        "SELECT amount FROM cash_balance WHERE id = 1"
    ).fetchone()

    conn.close()

    cash = float(cash_row["amount"]) if cash_row else 0.0

    if not rows:
        await update.message.reply_text(
            f"پرتفوی خالی است.\n"
            f"نقد: {cash:,.0f}"
        )
        return

    lines = [
        f"نقد: {cash:,.0f}",
        "",
        "پرتفوی:"
    ]

    total_value = cash

    for row in rows:
        value = (
            row["quantity"]
            * row["market_price"]
        )

        total_value += value

        lines.append(
            f"{row['symbol']} | "
            f"{row['quantity']} سهم | "
            f"میانگین {row['average_price']:,.0f} | "
            f"قیمت {row['market_price']:,.0f}"
        )

    lines.extend([
        "",
        f"ارزش کل تقریبی: {total_value:,.0f}",
    ])

    await update.message.reply_text(
        "\n".join(lines)
    )


async def cash(update, context):
    if not is_allowed(update):
        return await deny(update)

    if context.args:
        try:
            millions = float(context.args[0])

            if millions < 0:
                raise ValueError

            amount = millions * 1_000_000

            conn = get_db()

            conn.execute(
                """
                INSERT INTO cash_balance (
                    id,
                    amount,
                    updated_at
                )
                VALUES (1, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id)
                DO UPDATE SET
                    amount = excluded.amount,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (amount,),
            )

            conn.commit()
            conn.close()

            await update.message.reply_text(
                f"موجودی نقد ثبت شد: {millions:g} میلیون تومان\n"
                f"معادل: {amount:,.0f} تومان"
            )
            return

        except ValueError:
            await update.message.reply_text(
                "فرمت صحیح:\n"
                "/cash 5\n"
                "/cash 5.2\n"
                "/cash 12.5"
            )
            return

    conn = get_db()

    row = conn.execute(
        "SELECT amount FROM cash_balance WHERE id = 1"
    ).fetchone()

    conn.close()

    amount = float(row["amount"]) if row else 0.0
    millions = amount / 1_000_000

    await update.message.reply_text(
        f"موجودی نقد: {millions:g} میلیون تومان\n"
        f"معادل: {amount:,.0f} تومان\n\n"
        "برای تغییر:\n"
        "/cash مقدار-به-میلیون"
    )


async def buy_command(update, context):
    if not allowed(update):
        return await deny(update)

    if len(context.args) < 3:
        await update.message.reply_text(
            "فرمت:\n"
            "/buy نماد تعداد قیمت\n\n"
            "مثال:\n"
            "/buy غمهرا 100 19130"
        )
        return

    symbol = context.args[0].strip()

    try:
        quantity = int(context.args[1])
        price = float(context.args[2])

        if quantity <= 0 or price <= 0:
            raise ValueError

    except ValueError:
        await update.message.reply_text(
            "تعداد و قیمت باید عدد مثبت باشند."
        )
        return

    try:
        conn = get_db()

        stock = conn.execute(
            """
            SELECT inscode, symbol
            FROM symbols
            WHERE symbol = ?
              AND active = 1
            ORDER BY inscode
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()

        if not stock:
            conn.close()
            await update.message.reply_text(
                f"نماد {symbol} پیدا نشد."
            )
            return

        inscode = int(stock["inscode"])
        actual_symbol = stock["symbol"]

        cash_row = conn.execute(
            "SELECT amount FROM cash_balance WHERE id = 1"
        ).fetchone()

        cash = float(cash_row["amount"]) if cash_row else 0.0

        total_cost = quantity * price

        if total_cost > cash:
            conn.close()
            await update.message.reply_text(
                f"موجودی کافی نیست.\n"
                f"نیاز: {total_cost:,.0f}\n"
                f"موجودی: {cash:,.0f}"
            )
            return

        position = conn.execute(
            """
            SELECT quantity, average_price
            FROM portfolio
            WHERE inscode = ?
            """,
            (inscode,),
        ).fetchone()

        old_qty = int(position["quantity"]) if position else 0
        old_avg = float(position["average_price"]) if position else 0.0

        new_qty = old_qty + quantity

        new_avg = (
            (old_qty * old_avg) + (quantity * price)
        ) / new_qty

        conn.execute(
            """
            INSERT INTO portfolio (
                inscode,
                symbol,
                quantity,
                average_price
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(inscode)
            DO UPDATE SET
                symbol = excluded.symbol,
                quantity = excluded.quantity,
                average_price = excluded.average_price,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                inscode,
                actual_symbol,
                new_qty,
                new_avg,
            ),
        )

        conn.execute(
            """
            INSERT INTO portfolio_transactions (
                inscode,
                symbol,
                side,
                quantity,
                price,
                fee,
                trade_date
            )
            VALUES (?, ?, 'BUY', ?, ?, 0, ?)
            """,
            (
                inscode,
                actual_symbol,
                quantity,
                price,
                int(
                    __import__("datetime")
                    .datetime
                    .now()
                    .strftime("%Y%m%d")
                ),
            ),
        )

        new_cash = cash - total_cost

        conn.execute(
            """
            UPDATE cash_balance
            SET amount = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (new_cash,),
        )

        conn.commit()
        conn.close()

        # اگر این اولین خرید باشد، position_levels ساخته می‌شود.
        # اگر قبلاً وجود داشته باشد، سطوح قبلی حفظ می‌شوند.
        initialize_position_after_buy(
            inscode=inscode,
            symbol=actual_symbol,
            quantity=new_qty,
            average_price=new_avg,
        )

        await update.message.reply_text(
            f"✅ خرید ثبت شد\n\n"
            f"{actual_symbol}\n"
            f"تعداد: {new_qty:,}\n"
            f"میانگین خرید: {new_avg:,.0f}\n"
            f"هزینه خرید جدید: {total_cost:,.0f}\n"
            f"موجودی نقد: {new_cash:,.0f}"
        )

    except Exception as exc:
        await update.message.reply_text(
            f"خطا در ثبت خرید:\n{exc}"
        )


async def sell_command(update, context):
    if not allowed(update):
        return await deny(update)

    if len(context.args) < 3:
        await update.message.reply_text(
            "فرمت:\n"
            "/sell نماد تعداد قیمت\n\n"
            "مثال:\n"
            "/sell غمهرا 100 20500"
        )
        return

    symbol = context.args[0].strip()

    try:
        quantity = int(context.args[1])
        price = float(context.args[2])

        if quantity <= 0 or price <= 0:
            raise ValueError

    except ValueError:
        await update.message.reply_text(
            "تعداد و قیمت باید عدد مثبت باشند."
        )
        return

    try:
        conn = get_db()

        stock = conn.execute(
            """
            SELECT inscode, symbol
            FROM symbols
            WHERE symbol = ?
              AND active = 1
            ORDER BY inscode
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()

        if not stock:
            conn.close()
            await update.message.reply_text(
                f"نماد {symbol} پیدا نشد."
            )
            return

        inscode = int(stock["inscode"])
        actual_symbol = stock["symbol"]

        position = conn.execute(
            """
            SELECT quantity, average_price
            FROM portfolio
            WHERE inscode = ?
            """,
            (inscode,),
        ).fetchone()

        if not position:
            conn.close()
            await update.message.reply_text(
                f"از {actual_symbol} چیزی در پرتفوی ثبت نشده."
            )
            return

        old_qty = int(position["quantity"])
        avg_price = float(position["average_price"])

        if quantity > old_qty:
            conn.close()
            await update.message.reply_text(
                f"تعداد قابل فروش: {old_qty:,}"
            )
            return

        proceeds = quantity * price
        new_qty = old_qty - quantity
        realized_pnl = quantity * (price - avg_price)

        if new_qty == 0:
            conn.execute(
                "DELETE FROM portfolio WHERE inscode = ?",
                (inscode,),
            )

            # موقعیت کاملاً بسته شده؛
            # سطوح قبلی نباید برای خرید بعدی باقی بمانند.
            conn.execute(
                "DELETE FROM position_levels WHERE inscode = ?",
                (inscode,),
            )

        else:
            conn.execute(
                """
                UPDATE portfolio
                SET quantity = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE inscode = ?
                """,
                (new_qty, inscode),
            )

        conn.execute(
            """
            INSERT INTO portfolio_transactions (
                inscode,
                symbol,
                side,
                quantity,
                price,
                fee,
                trade_date
            )
            VALUES (?, ?, 'SELL', ?, ?, 0, ?)
            """,
            (
                inscode,
                actual_symbol,
                quantity,
                price,
                int(
                    __import__("datetime")
                    .datetime
                    .now()
                    .strftime("%Y%m%d")
                ),
            ),
        )

        cash_row = conn.execute(
            "SELECT amount FROM cash_balance WHERE id = 1"
        ).fetchone()

        cash = float(cash_row["amount"]) if cash_row else 0.0
        new_cash = cash + proceeds

        conn.execute(
            """
            UPDATE cash_balance
            SET amount = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (new_cash,),
        )

        conn.commit()
        conn.close()

        await update.message.reply_text(
            f"✅ فروش ثبت شد\n\n"
            f"{actual_symbol}\n"
            f"فروش: {quantity:,}\n"
            f"باقی‌مانده: {new_qty:,}\n"
            f"مبلغ فروش: {proceeds:,.0f}\n"
            f"سود/زیان تحقق‌یافته: {realized_pnl:,.0f}\n"
            f"موجودی نقد: {new_cash:,.0f}"
        )

    except Exception as exc:
        await update.message.reply_text(
            f"خطا در ثبت فروش:\n{exc}"
        )


async def error_handler(update, context):
    print("Telegram error:", context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing in /opt/bourse-bot/.env"
        )

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("signals", signals))
    app.add_handler(CommandHandler("market", market))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("portfolio", portfolio))
    app.add_handler(CommandHandler("cash", cash))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("sell", sell_command))

    app.add_error_handler(error_handler)

    print("Telegram bot started.")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
