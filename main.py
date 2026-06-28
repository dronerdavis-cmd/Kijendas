import os
import logging
import sqlite3
from datetime import datetime
from telegram import (
    Update, 
    ReplyKeyboardMarkup, 
    ReplyKeyboardRemove, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

# --- پیکربندی سیستم ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(i.strip()) for i in os.getenv("ADMIN_IDS", "").split(",") if i.strip().isdigit()]

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- وضعیت‌های گفتگو ---
(
    MENU,
    GET_CARDS,
    GET_NAME,
    GET_TG_ID,
    GET_DESC,
    GET_EVIDENCE,
    CONFIRM_REPORT,
    SEARCHING
) = range(8)

# --- دیتابیس ---
def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS reports 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER, name TEXT, 
                  tg_id TEXT, description TEXT, status TEXT, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS cards 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, report_id INTEGER, card_number TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS evidence 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, report_id INTEGER, file_id TEXT)''')
    conn.commit()
    conn.close()

# --- توابع کمکی ---
def get_main_keyboard(user_id):
    buttons = [["📝 ثبت گزارش کلاهبرداری"], ["🔎 جستجوی استعلام"], ["👤 پروفایل من"]]
    if user_id in ADMIN_IDS:
        buttons.insert(0, ["🛡 پنل مدیریت"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# --- شروع بات ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
    user = update.effective_user
    await update.message.reply_text(
        f"سلام {user.first_name} عزیز به سامانه مرکزی ثبت گزارشات کلاهبرداری خوش آمدید.\n\n"
        "لطفاً از منوی زیر اقدام کنید:",
        reply_markup=get_main_keyboard(user.id)
    )
    return MENU

# --- جریان ثبت گزارش ---
async def start_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['report'] = {
        'cards': [],
        'name': None,
        'tg_id': None,
        'desc': None,
        'evidence': []
    }
    await update.message.reply_text(
        "💳 لطفاً شماره کارت(های) فرد کلاهبردار را وارد کنید.\n"
        "می‌توانید بیش از یک کارت وارد کنید. پس از پایان، دکمه «بعدی ➡️» را بزنید.",
        reply_markup=ReplyKeyboardMarkup([["بعدی ➡️"], ["❌ انصراف"]], resize_keyboard=True)
    )
    return GET_CARDS

async def handle_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "بعدی ➡️":
        await update.message.reply_text("👤 نام یا نام مستعار فرد (در صورت اطلاع) را وارد کنید یا دکمه «بعدی ➡️» را بزنید:")
        return GET_NAME
    
    # حذف خط تیره و فاصله برای تمیز کردن شماره کارت
    clean_card = text.replace("-", "").replace(" ", "")
    if clean_card.isdigit() and len(clean_card) == 16:
        context.user_data['report']['cards'].append(clean_card)
        await update.message.reply_text(f"✅ شماره کارت {clean_card} ثبت شد. کارت دیگری دارید؟ در غیر این صورت «بعدی ➡️» را بزنید.")
    else:
        await update.message.reply_text("⚠️ شماره کارت باید ۱۶ رقم باشد. دوباره تلاش کنید یا «بعدی ➡️» را بزنید.")
    return GET_CARDS

async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text != "بعدی ➡️":
        context.user_data['report']['name'] = text
    
    await update.message.reply_text("🆔 آیدی تلگرام فرد را وارد کنید (مثلاً @username) یا دکمه «بعدی ➡️» را بزنید:")
    return GET_TG_ID

async def handle_tg_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text != "بعدی ➡️":
        context.user_data['report']['tg_id'] = text
    
    await update.message.reply_text("📝 شرح کلاهبرداری را بنویسید (این بخش اجباری است):", reply_markup=ReplyKeyboardMarkup([["❌ انصراف"]], resize_keyboard=True))
    return GET_DESC

async def handle_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['report']['desc'] = update.message.text
    await update.message.reply_text(
        "🖼 اسکرین‌شات‌ها یا مدارک خود را ارسال کنید (حداکثر ۱۰ مورد).\n"
        "پس از اتمام ارسال، دکمه «پایان و بازبینی ✅» را بزنید.",
        reply_markup=ReplyKeyboardMarkup([["پایان و بازبینی ✅"], ["❌ انصراف"]], resize_keyboard=True)
    )
    return GET_EVIDENCE

async def handle_evidence(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        if len(context.user_data['report']['evidence']) < 10:
            file_id = update.message.photo[-1].file_id
            context.user_data['report']['evidence'].append(file_id)
            await update.message.reply_text(f"✅ مدرک شماره {len(context.user_data['report']['evidence'])} دریافت شد.")
        else:
            await update.message.reply_text("⚠️ ظرفیت مدارک پر شده است (حداکثر ۱۰ تصویر).")
        return GET_EVIDENCE
    
    if update.message.text == "پایان و بازبینی ✅":
        data = context.user_data['report']
        # چک کردن شرط حداقل اطلاعات
        if not (data['cards'] or data['name'] or data['tg_id']):
            await update.message.reply_text("⚠️ خطا: شما باید حداقل یکی از موارد (شماره کارت، نام یا آیدی) را وارد کنید تا گزارش معتبر باشد. فرآیند را از ابتدا شروع کنید.")
            return await cancel(update, context)

        summary = (
            "📋 <b>خلاصه گزارش شما:</b>\n\n"
            f"💳 کارت‌ها: {', '.join(data['cards']) if data['cards'] else 'وارد نشده'}\n"
            f"👤 نام: {data['name'] or 'وارد نشده'}\n"
            f"🆔 آیدی: {data['tg_id'] or 'وارد نشده'}\n"
            f"📝 شرح: {data['desc']}\n"
            f"🖼 تعداد مدارک: {len(data['evidence'])}\n\n"
            "آیا از ارسال این گزارش اطمینان دارید؟"
        )
        await update.message.reply_text(summary, parse_mode=ParseMode.HTML, 
                                       reply_markup=ReplyKeyboardMarkup([["🚀 تایید و ارسال نهایی"], ["❌ انصراف"]], resize_keyboard=True))
        return CONFIRM_REPORT

async def final_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data['report']
    uid = update.effective_user.id
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("INSERT INTO reports (reporter_id, name, tg_id, description, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
              (uid, data['name'], data['tg_id'], data['desc'], "pending", now))
    report_id = c.lastrowid
    
    for card in data['cards']:
        c.execute("INSERT INTO cards (report_id, card_number) VALUES (?, ?)", (report_id, card))
    for photo in data['evidence']:
        c.execute("INSERT INTO evidence (report_id, file_id) VALUES (?, ?)", (report_id, photo))
    
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ گزارش شما با موفقیت ثبت شد و در صف بررسی ادمین قرار گرفت.", reply_markup=get_main_keyboard(uid))
    
    # اطلاع به ادمین‌ها
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, f"📥 گزارش جدید ثبت شد!\nکد گزارش: {report_id}\nبرای بررسی به پنل مدیریت بروید.")
        except: pass
        
    return MENU

# --- سیستم جستجو ---
async def start_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔎 شماره کارت یا آیدی تلگرام مورد نظر را جهت استعلام وارد کنید:", 
                                   reply_markup=ReplyKeyboardMarkup([["🔙 بازگشت"]], resize_keyboard=True))
    return SEARCHING

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    if query == "🔙 بازگشت":
        return await cancel(update, context)
    
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    # جستجو در کارت‌ها یا آیدی‌ها (فقط گزارش‌های تایید شده)
    c.execute('''SELECT reports.id, reports.description FROM reports 
                 LEFT JOIN cards ON reports.id = cards.report_id 
                 WHERE (cards.card_number = ? OR reports.tg_id = ?) AND reports.status = 'approved' ''', (query, query))
    results = c.fetchall()
    conn.close()

    if results:
        msg = f"❌ <b>هشدار: {len(results)} سابقه کلاهبرداری یافت شد!</b>\n\n"
        for res in results:
            msg += f"🚩 گزارش شماره {res[0]}:\n{res[1][:100]}...\n\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("✅ نتیجه استعلام: موردی در لیست سیاه یافت نشد.\n(همیشه احتیاط کنید)")
    
    return SEARCHING

# --- پنل مدیریت ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return MENU
    
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT id, name FROM reports WHERE status = 'pending'")
    pending = c.fetchall()
    conn.close()

    if not pending:
        await update.message.reply_text("هیچ گزارش در انتظاری وجود ندارد.")
        return MENU

    for rep in pending:
        keyboard = [[InlineKeyboardButton("✅ تایید", callback_data=f"app_{rep[0]}"),
                     InlineKeyboardButton("❌ رد", callback_data=f"rej_{rep[0]}"),
                     InlineKeyboardButton("🗑 حذف", callback_data=f"del_{rep[0]}")]]
        await update.message.reply_text(f"📄 گزارش ID: {rep[0]}\nنام: {rep[1]}", 
                                       reply_markup=InlineKeyboardMarkup(keyboard))
    return MENU

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    action, r_id = data.split("_")
    
    status = "approved" if action == "app" else "rejected"
    
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    if action == "del":
        c.execute("DELETE FROM reports WHERE id = ?", (r_id,))
    else:
        c.execute("UPDATE reports SET status = ? WHERE id = ?", (status, r_id))
    conn.commit()
    conn.close()
    
    await query.answer(f"عملیات {action} با موفقیت انجام شد.")
    await query.edit_message_text(f"✅ پرونده {r_id} تعیین تکلیف شد.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد. به منوی اصلی بازگشتیم.", reply_markup=get_main_keyboard(update.effective_user.id))
    return MENU

# --- اجرا ---
def main():
    if not TOKEN:
        print("خطا: BOT_TOKEN یافت نشد!")
        return

    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), 
                      MessageHandler(filters.Regex("^📝 ثبت گزارش کلاهبرداری$"), start_report),
                      MessageHandler(filters.Regex("^🔎 جستجوی استعلام$"), start_search),
                      MessageHandler(filters.Regex("^🛡 پنل مدیریت$"), admin_panel)],
        states={
            MENU: [MessageHandler(filters.Regex("^📝 ثبت گزارش کلاهبرداری$"), start_report),
                   MessageHandler(filters.Regex("^🔎 جستجوی استعلام$"), start_search),
                   MessageHandler(filters.Regex("^🛡 پنل مدیریت$"), admin_panel)],
            GET_CARDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cards)],
            GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
            GET_TG_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tg_id)],
            GET_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_desc)],
            GET_EVIDENCE: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, handle_evidence)],
            CONFIRM_REPORT: [MessageHandler(filters.Regex("^🚀 تایید و ارسال نهایی$"), final_submit)],
            SEARCHING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search)],
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ انصراف$"), cancel), CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(admin_callback))
    
    print("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
