import os
import logging
import sqlite3
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ۱. تنظیمات لاگ (برای اینکه در Railway بفهمیم چه اتفاقی می‌افتد)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ۲. توابع دیتابیس (برای ذخیره گزارش‌ها)
def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            identifier TEXT,
            report_text TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

# ۳. تابع دستور /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! به ربات گزارش کلاهبرداری خوش آمدید.\n\n"
        "ثبت گزارش:\n/report [شماره کارت] [متن گزارش]\n\n"
        "جستجو:\n/search [شماره کارت]"
    )

# ۴. تابع ثبت گزارش (/report)
async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("لطفاً به این صورت وارد کنید:\n/report شماره_کارت متن_گزارش")
        return
    
    id_to_report = context.args[0]
    text = " ".join(context.args[1:])
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reports (identifier, report_text, created_at) VALUES (?, ?, ?)", 
                   (id_to_report, text, datetime.now().strftime("%Y-%m-%d")))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ گزارش برای شناسه‌ی {id_to_report} با موفقیت ثبت شد.")

# ۵. تابع جستجو (/search)
async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("لطفاً شماره کارت یا شناسه را وارد کنید.\nمثال: /search 1234")
        return
    
    search_id = context.args[0]
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT report_text, created_at FROM reports WHERE identifier = ?", (search_id,))
    results = cursor.fetchall()
    conn.close()
    
    if not results:
        await update.message.reply_text("❌ هیچ گزارشی برای این شناسه یافت نشد.")
    else:
        response = f"🔍 تعداد {len(results)} گزارش یافت شد:\n\n"
        for msg, date in results:
            response += f"🚩 گزارش: {msg}\n📅 تاریخ: {date}\n"
            response += "-"*15 + "\n"
        await update.message.reply_text(response)

# ۶. بخش اصلی اجراکننده ربات
def main():
    # گرفتن توکن از متغیرهای Railway
    token = os.getenv("BOT_TOKEN")
    
    if not token:
        print("خطا: BOT_TOKEN تنظیم نشده است!")
        return

    init_db() # ساخت دیتابیس در صورت عدم وجود
    
    # ساخت اپلیکیشن ربات
    app = Application.builder().token(token).build()

    # اتصال دستورات به تابع‌ها
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("search", search))

    print("ربات روشن شد و آماده به کار است...")
    app.run_polling()

if __name__ == '__main__':
    main()
