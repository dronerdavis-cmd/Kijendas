import os
import sqlite3
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")

CARD, TEXT = range(2)

conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_number TEXT,
    report_text TEXT
)
""")
conn.commit()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ربات آماده است\n\n/report ثبت گزارش\n/search جستجو"
    )


async def report_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("شماره کارت را بفرست:")
    return CARD


async def report_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["card"] = update.message.text
    await update.message.reply_text("توضیح را بنویس:")
    return TEXT


async def report_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cursor.execute(
        "INSERT INTO reports(card_number, report_text) VALUES (?, ?)",
        (context.user_data["card"], update.message.text)
    )
    conn.commit()

    await update.message.reply_text("ثبت شد")
    return ConversationHandler.END


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("مثال: /search 1234")
        return

    card = context.args[0]

    cursor.execute("SELECT report_text FROM reports WHERE card_number=?", (card,))
    rows = cursor.fetchall()

    if not rows:
        await update.message.reply_text("چیزی پیدا نشد")
        return

    msg = ""
    for r in rows:
        msg += f"- {r[0]}\n"

    await update.message.reply_text(msg)


app = ApplicationBuilder().token(TOKEN).build()

conv = ConversationHandler(
    entry_points=[CommandHandler("report", report_start)],
    states={
        CARD: [MessageHandler(filters.TEXT, report_card)],
        TEXT: [MessageHandler(filters.TEXT, report_text)],
    },
    fallbacks=[],
)

app.add_handler(CommandHandler("start", start))
app.add_handler(conv)
app.add_handler(CommandHandler("search", search))

app.run_polling()
