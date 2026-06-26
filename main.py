import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# تنظیمات لاگ برای دیدن خطاها در Railway
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

def main():
    # خواندن توکن از تنظیمات Railway
    token = os.getenv("BOT_TOKEN")
    
    if not token:
        print("خطا: توکن در تنظیمات Railway پیدا نشد!")
        return

    print("ربات در حال راه اندازی است...")
    app = Application.builder().token(token).build()

    # دستور ساده برای تست
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("سلام! ربات با موفقیت بالا آمد.")

    app.add_handler(CommandHandler("start", start))

    # شروع به کار ربات
    app.run_polling()

if __name__ == '__main__':
    main()
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
