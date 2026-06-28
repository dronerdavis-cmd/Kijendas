import sqlite3
import re
import logging
import os
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# دریافت اطلاعات از متغیرهای سیستم (Railway Variables)
TOKEN = os.getenv("BOT_TOKEN")
# تبدیل رشته آیدی‌ها به لیست اعداد
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(i.strip()) for i in ADMIN_IDS_STR.split(",") if i.strip().isdigit()]

MAX_EVIDENCE = 10
DAILY_LIMIT = 5

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

(
    MAIN_MENU,
    REPORT_FORM,
    WAIT_FIELD,
    ADD_CARD,
    ADD_EVIDENCE,
    CONFIRM_REPORT,
    SEARCH,
    ADMIN_PANEL,
    ADMIN_LIST,
    ADMIN_VIEW
) = range(10)

# ---------------- DATABASE ----------------

def db():
    return sqlite3.connect("bot.db")

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY,
        username TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        telegram_id TEXT,
        phone TEXT,
        description TEXT,
        reporter INTEGER,
        status TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS cards(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER,
        card TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS evidence(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER,
        file_id TEXT
    )""")
    conn.commit()
    conn.close()

# ---------------- VALIDATION ----------------

def valid_card(card):
    return re.fullmatch(r"\d{16}", card)

# ---------------- KEYBOARDS ----------------

def main_menu_kb(uid):
    kb = [["🔎 جستجو"], ["📝 ثبت گزارش"], ["👤 حساب من"]]
    if uid in ADMIN_IDS:
        kb.insert(0, ["🛡 پنل مدیریت"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def report_kb(data):
    def s(v): return "✅" if v else "⬜"
    kb = [
        [f"{s(data.get('name'))} نام", f"{s(data.get('cards'))} کارت"],
        [f"{s(data.get('telegram'))} آیدی تلگرام"],
        [f"{s(data.get('desc'))} توضیحات"],
        [f"{s(data.get('evidence'))} مدرک"],
        ["✅ ثبت نهایی"],
        ["❌ لغو"]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ---------------- HANDLERS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users VALUES(?,?)", (user.id, user.username))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"سلام {user.first_name} عزیز، به سامانه گزارش کلاهبرداری خوش آمدید.\nلطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=main_menu_kb(user.id)
    )
    return MAIN_MENU

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id

    if text == "📝 ثبت گزارش":
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM reports WHERE reporter=? AND date(created_at)=date('now')", (uid,))
        if cur.fetchone()[0] >= DAILY_LIMIT:
            await update.message.reply_text("❌ ظرفیت گزارش‌دهی روزانه شما تکمیل شده است.")
            return MAIN_MENU
        
        context.user_data["report"] = {"cards": [], "evidence": []}
        await update.message.reply_text("📋 فرم گزارش را با استفاده از دکمه‌های زیر تکمیل کنید:", 
                                       reply_markup=report_kb(context.user_data["report"]))
        return REPORT_FORM

    elif text == "🔎 جستجو":
        await update.message.reply_text("🔍 نام، آیدی تلگرام یا شماره کارت مورد نظر را ارسال کنید:")
        return SEARCH

    elif text == "🛡 پنل مدیریت" and uid in ADMIN_IDS:
        kb = [["📂 گزارش‌های در انتظار"], ["⬅️ بازگشت"]]
        await update.message.reply_text("🛡 به پنل مدیریت خوش آمدید:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        return ADMIN_PANEL

    return MAIN_MENU

async def report_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    data = context.user_data.get("report", {})

    if "نام" in text:
        context.user_data["field"] = "name"
        await update.message.reply_text("👤 نام و نام خانوادگی فرد کلاهبردار را ارسال کنید:")
        return WAIT_FIELD
    elif "کارت" in text:
        await update.message.reply_text("💳 شماره کارت ۱۶ رقمی را ارسال کنید. (برای اتمام /done را بزنید)")
        return ADD_CARD
    elif "آیدی" in text:
        context.user_data["field"] = "telegram"
        await update.message.reply_text("🆔 آیدی تلگرام (بدون @ یا با @) را ارسال کنید:")
        return WAIT_FIELD
    elif "توضیحات" in text:
        context.user_data["field"] = "desc"
        await update.message.reply_text("✍️ شرح کامل اتفاق را بنویسید:")
        return WAIT_FIELD
    elif "مدرک" in text:
        await update.message.reply_text(f"🖼 تصاویر مدارک (اسکرین‌شات) را ارسال کنید. (تا {MAX_EVIDENCE} مورد / اتمام با /done)")
        return ADD_EVIDENCE
    elif text == "✅ ثبت نهایی":
        if not (data.get("cards") or data.get("telegram") or data.get("name")):
            await update.message.reply_text("⚠️ حداقل باید یکی از موارد (نام، کارت یا آیدی) را پر کنید.")
            return REPORT_FORM
        await update.message.reply_text("آیا از صحت اطلاعات و ارسال گزارش اطمینان دارید؟",
                                       reply_markup=ReplyKeyboardMarkup([["✅ تایید و ارسال"], ["❌ لغو"]], resize_keyboard=True))
        return CONFIRM_REPORT
    elif text == "❌ لغو":
        return await cancel(update, context)

    return REPORT_FORM

async def field_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.get("field")
    context.user_data["report"][field] = update.message.text
    await update.message.reply_text("✅ ثبت شد.", reply_markup=report_kb(context.user_data["report"]))
    return REPORT_FORM

async def add_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "/done":
        await update.message.reply_text("✅ لیست کارت‌ها بسته شد.", reply_markup=report_kb(context.user_data["report"]))
        return REPORT_FORM
    if not valid_card(text):
        await update.message.reply_text("❌ شماره کارت نامعتبر است. باید ۱۶ رقم باشد.")
        return ADD_CARD
    context.user_data["report"]["cards"].append(text)
    await update.message.reply_text(f"✅ کارت {text} اضافه شد. کارت بعدی یا /done:")
    return ADD_CARD

async def add_evidence(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "/done":
        await update.message.reply_text("✅ مدارک ثبت شدند.", reply_markup=report_kb(context.user_data["report"]))
        return REPORT_FORM
    if update.message.photo:
        if len(context.user_data["report"]["evidence"]) >= MAX_EVIDENCE:
            await update.message.reply_text("❌ حد مجاز مدارک پر شده است.")
            return ADD_EVIDENCE
        file_id = update.message.photo[-1].file_id
        context.user_data["report"]["evidence"].append(file_id)
        await update.message.reply_text(f"✅ مدرک شماره {len(context.user_data['report']['evidence'])} دریافت شد. بعدی یا /done:")
    return ADD_EVIDENCE

async def confirm_submission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "✅ تایید و ارسال":
        data = context.user_data["report"]
        conn = db()
        cur = conn.cursor()
        cur.execute("INSERT INTO reports(name, telegram_id, description, reporter, status) VALUES(?,?,?,?,?)",
                    (data.get("name"), data.get("telegram"), data.get("desc"), update.effective_user.id, "pending"))
        rid = cur.lastrowid
        for c in data["cards"]:
            cur.execute("INSERT INTO cards(report_id, card) VALUES(?,?)", (rid, c))
        for e in data["evidence"]:
            cur.execute("INSERT INTO evidence(report_id, file_id) VALUES(?,?)", (rid, e))
        conn.commit()
        conn.close()
        await update.message.reply_text("🚀 گزارش شما با موفقیت ثبت و برای بررسی ادمین ارسال شد.", reply_markup=main_menu_kb(update.effective_user.id))
    else:
        await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=main_menu_kb(update.effective_user.id))
    return MAIN_MENU

async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT r.id, r.name, r.description FROM reports r
        LEFT JOIN cards c ON r.id = c.report_id
        WHERE r.status='approved' AND (r.name LIKE ? OR r.telegram_id LIKE ? OR c.card LIKE ?)
    """, (f"%{query}%", f"%{query}%", f"%{query}%"))
    results = cur.fetchall()
    conn.close()

    if not results:
        await update.message.reply_text("✅ موردی با این مشخصات در لیست سیاه یافت نشد.")
    else:
        msg = f"⚠️ {len(results)} مورد یافت شد:\n\n"
        for r in results:
            msg += f"📎 گزارش شماره {r[0]}\n👤 نام: {r[1] or 'نامشخص'}\n📝 شرح: {r[2][:50]}...\n\n"
        await update.message.reply_text(msg)
    
    return MAIN_MENU

# --- ADMIN FUNCTIONS ---
async def admin_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM reports WHERE status='pending'")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("✅ هیچ گزارش در انتظاری وجود ندارد.")
        return ADMIN_PANEL
    kb = [[f"📄 {r[0]} | {r[1] or 'بدون نام'}"] for r in rows]
    kb.append(["⬅️ بازگشت"])
    await update.message.reply_text("📂 لیست گزارش‌های در انتظار بررسی:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ADMIN_LIST

async def admin_detail_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "📄" not in text: return ADMIN_PANEL
    rid = text.split("|")[0].replace("📄", "").strip()
    context.user_data["current_rid"] = rid
    
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT name, telegram_id, description, reporter FROM reports WHERE id=?", (rid,))
    rep = cur.fetchone()
    cur.execute("SELECT card FROM cards WHERE report_id=?", (rid,))
    cards = [c[0] for c in cur.fetchall()]
    conn.close()

    msg = f"🧐 بررسی گزارش شماره {rid}\n\n👤 نام: {rep[0]}\n🆔 تلگرام: {rep[1]}\n💳 کارت‌ها: {', '.join(cards)}\n📝 توضیحات: {rep[2]}\n👤 گزارش دهنده: {rep[3]}"
    kb = [["✅ تایید", "❌ رد"], ["🖼 مشاهده مدارک"], ["⬅️ بازگشت"]]
    await update.message.reply_text(msg, reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ADMIN_VIEW

async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = update.message.text
    rid = context.user_data.get("current_rid")
    conn = db()
    cur = conn.cursor()

    if action == "✅ تایید":
        cur.execute("UPDATE reports SET status='approved' WHERE id=?", (rid,))
        await update.message.reply_text(f"✅ گزارش {rid} تایید و به لیست سیاه اضافه شد.")
    elif action == "❌ رد":
        cur.execute("UPDATE reports SET status='rejected' WHERE id=?", (rid,))
        await update.message.reply_text(f"❌ گزارش {rid} رد شد.")
    elif action == "🖼 مشاهده مدارک":
        cur.execute("SELECT file_id FROM evidence WHERE report_id=?", (rid,))
        evs = cur.fetchall()
        if not evs: await update.message.reply_text("مدارکی وجود ندارد.")
        for e in evs: await update.message.reply_photo(e[0])
        conn.close()
        return ADMIN_VIEW

    conn.commit()
    conn.close()
    return await admin_pending(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏠 بازگشت به منوی اصلی.", reply_markup=main_menu_kb(update.effective_user.id))
    return MAIN_MENU

def main():
    init_db()
    if not TOKEN:
        print("Error: BOT_TOKEN variable is not set!")
        return

    app = Application.builder().token(TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)],
            REPORT_FORM: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_form)],
            WAIT_FIELD: [MessageHandler(filters.TEXT & ~filters.COMMAND, field_input)],
            ADD_CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_card)],
            ADD_EVIDENCE: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, add_evidence)],
            CONFIRM_REPORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_submission)],
            SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_handler)],
            ADMIN_PANEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_pending)],
            ADMIN_LIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_detail_view)],
            ADMIN_VIEW: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_action)],
        },
        fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex("^⬅️ بازگشت$"), cancel)],
    )

    app.add_handler(conv)
    print("--- Bot is running ---")
    app.run_polling()

if __name__ == "__main__":
    main()
