import os
import sqlite3
import logging
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    ConversationHandler, ContextTypes, filters
)

# تنظیمات لاگ برای عیب‌یابی در Railway
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

DB_NAME = "database.db"

# مراحل گفتگو
(
    MENU,
    REPORT_CARD,
    REPORT_NAME,
    REPORT_PHONE,
    REPORT_USERNAME,
    REPORT_AMOUNT,
    REPORT_TEXT,
    REPORT_PHOTOS,
    SEARCH_INPUT,
) = range(9)

# کیبوردهای کمکی
def get_main_keyboard():
    return ReplyKeyboardMarkup([["📝 ثبت گزارش", "🔎 جستجو"], ["ℹ️ راهنما"]], resize_keyboard=True)

def get_step_keyboard(show_back=True):
    buttons = [["⏭ رد کردن"]]
    if show_back:
        buttons[0].append("🔙 بازگشت")
    buttons.append(["❌ لغو و ریست"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# توابع کمکی دیتابیس
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_number TEXT, full_name TEXT, phone TEXT, 
            username TEXT, amount TEXT, report_text TEXT, created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

# شروع و ریست
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear() # پاکسازی حافظه موقت کاربر
    await update.message.reply_text(
        "👋 به ربات ثبت گزارش خوش آمدید.\nیکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=get_main_keyboard()
    )
    return MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ عملیات لغو شد و به منوی اصلی برگشتیم.", reply_markup=get_main_keyboard())
    return MENU

# --- شروع فرآیند ثبت گزارش ---
async def report_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💳 شماره کارت را وارد کنید:", reply_markup=get_step_keyboard(show_back=False))
    return REPORT_CARD

async def report_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if val == "🔙 بازگشت": return await report_start(update, context) # استثنا برای مرحله اول
    
    context.user_data['card'] = val if val != "⏭ رد کردن" else "ثبت نشده"
    await update.message.reply_text("👤 نام صاحب حساب را وارد کنید:", reply_markup=get_step_keyboard())
    return REPORT_NAME

async def report_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if val == "🔙 بازگشت":
        await update.message.reply_text("💳 مرحله قبل: شماره کارت را وارد کنید:", reply_markup=get_step_keyboard(show_back=False))
        return REPORT_CARD
    
    context.user_data['name'] = val if val != "⏭ رد کردن" else "ثبت نشده"
    await update.message.reply_text("📞 شماره تماس را وارد کنید:", reply_markup=get_step_keyboard())
    return REPORT_PHONE

async def report_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if val == "🔙 بازگشت":
        await update.message.reply_text("👤 مرحله قبل: نام را وارد کنید:", reply_markup=get_step_keyboard())
        return REPORT_NAME
    
    context.user_data['phone'] = val if val != "⏭ رد کردن" else "ثبت نشده"
    await update.message.reply_text("🆔 آیدی تلگرام را وارد کنید:", reply_markup=get_step_keyboard())
    return REPORT_USERNAME

async def report_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if val == "🔙 بازگشت":
        await update.message.reply_text("📞 مرحله قبل: شماره تماس را وارد کنید:", reply_markup=get_step_keyboard())
        return REPORT_PHONE
    
    context.user_data['username'] = val if val != "⏭ رد کردن" else "ثبت نشده"
    await update.message.reply_text("💰 مبلغ (به تومان) را وارد کنید:", reply_markup=get_step_keyboard())
    return REPORT_AMOUNT

async def report_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if val == "🔙 بازگشت":
        await update.message.reply_text("🆔 مرحله قبل: آیدی را وارد کنید:", reply_markup=get_step_keyboard())
        return REPORT_USERNAME
    
    context.user_data['amount'] = val if val != "⏭ رد کردن" else "ثبت نشده"
    await update.message.reply_text("📝 شرح گزارش را بنویسید:", reply_markup=get_step_keyboard())
    return REPORT_TEXT

async def report_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if val == "🔙 بازگشت":
        await update.message.reply_text("💰 مرحله قبل: مبلغ را وارد کنید:", reply_markup=get_step_keyboard())
        return REPORT_AMOUNT
    
    context.user_data['text'] = val if val != "⏭ رد کردن" else "ثبت نشده"
    
    # ذخیره در دیتابیس
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO reports (card_number, full_name, phone, username, amount, report_text, created_at) VALUES (?,?,?,?,?,?,?)",
              (context.user_data.get('card'), context.user_data.get('name'), context.user_data.get('phone'), 
               context.user_data.get('username'), context.user_data.get('amount'), context.user_data.get('text'), 
               datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ گزارش شما با موفقیت ثبت شد.", reply_markup=get_main_keyboard())
    context.user_data.clear()
    return MENU

# --- بخش جستجو ---
async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 شماره کارت، تلفن یا آیدی مورد نظر را بفرستید:", reply_markup=ReplyKeyboardMarkup([["❌ لغو و ریست"]], resize_keyboard=True))
    return SEARCH_INPUT

async def search_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM reports WHERE card_number LIKE ? OR phone LIKE ? OR username LIKE ?", (f'%{query}%', f'%{query}%', f'%{query}%'))
    results = c.fetchall()
    conn.close()

    if not results:
        await update.message.reply_text("❌ نتیجه‌ای یافت نشد.", reply_markup=get_main_keyboard())
    else:
        for r in results:
            text = f"💳 کارت: {r[1]}\n👤 نام: {r[2]}\n📞 تماس: {r[3]}\n🆔 آیدی: {r[4]}\n💰 مبلغ: {r[5]}\n📝 شرح: {r[6]}"
            await update.message.reply_text(text)
        await update.message.reply_text(f"✅ کلاً {len(results)} مورد یافت شد.", reply_markup=get_main_keyboard())
    return MENU

def main():
    token = os.getenv("BOT_TOKEN")
    init_db()
    app = Application.builder().token(token).build()

    handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^📝 ثبت گزارش$"), report_start),
            MessageHandler(filters.Regex("^🔎 جستجو$"), search_start),
        ],
        states={
            MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, start)],
            REPORT_CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_card)],
            REPORT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_name)],
            REPORT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_phone)],
            REPORT_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_username)],
            REPORT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_amount)],
            REPORT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_finish)],
            SEARCH_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_logic)],
        },
        fallbacks=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^❌ لغو و ریست$"), cancel)
        ],
        allow_reentry=True # اجازه شروع مجدد در هر مرحله
    )

    app.add_handler(handler)
    app.run_polling()

if __name__ == "__main__":
    main()
