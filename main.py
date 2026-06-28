import sqlite3
import logging
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
Application,
CommandHandler,
MessageHandler,
ConversationHandler,
ContextTypes,
filters
)

TOKEN = "PUT_YOUR_BOT_TOKEN"

ADMIN_IDS = [123456789]

logging.basicConfig(level=logging.INFO)

(
MAIN_MENU,
REPORT_FORM,
WAITING_INPUT,
ADDING_CARDS,
ADDING_EVIDENCE,
CONFIRM_REPORT,
ADMIN_PANEL,
ADMIN_PENDING,
ADMIN_REVIEW,
SEARCH_INPUT
) = range(10)

# ---------------- DATABASE ----------------

def init_db():

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    username TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    telegram_id TEXT,
    phone TEXT,
    amount TEXT,
    description TEXT,
    reporter INTEGER,
    status TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS cards(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER,
    card_number TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS evidence(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER,
    file_id TEXT
    )
    """)

    conn.commit()
    conn.close()

# ---------------- KEYBOARDS ----------------

def main_menu(user_id):

    kb = [
        ["🔎 جستجو"],
        ["📝 ثبت گزارش"],
        ["👤 حساب من"]
    ]

    if user_id in ADMIN_IDS:
        kb.append(["🛡 پنل مدیریت"])

    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


def report_keyboard(data):

    def s(v):
        return "✅" if v else "⬜"

    kb = [
        [f"{s(data.get('name'))} نام", f"{s(data.get('cards'))} شماره کارت"],
        [f"{s(data.get('telegram_id'))} آیدی تلگرام"],
        [f"{s(data.get('description'))} توضیحات"],
        ["📎 ارسال مدرک"],
        ["✅ ثبت نهایی"],
        ["❌ لغو"]
    ]

    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ---------------- START ----------------

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    cur.execute(
    "INSERT INTO users(telegram_id,username) VALUES(?,?)",
    (user.id,user.username)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
    "به ربات گزارش کلاهبرداری خوش آمدید",
    reply_markup=main_menu(user.id)
    )

    return MAIN_MENU

# ---------------- MAIN MENU ----------------

async def main_menu_handler(update:Update,context:ContextTypes.DEFAULT_TYPE):

    text = update.message.text

    if text == "📝 ثبت گزارش":

        context.user_data["report"] = {
            "cards":[],
            "evidence":[]
        }

        await update.message.reply_text(
        "فرم گزارش را تکمیل کنید",
        reply_markup=report_keyboard(context.user_data["report"])
        )

        return REPORT_FORM

    if text == "🔎 جستجو":

        await update.message.reply_text("عبارت جستجو را ارسال کنید")

        return SEARCH_INPUT

    if text == "🛡 پنل مدیریت":

        if update.effective_user.id not in ADMIN_IDS:
            return MAIN_MENU

        kb = [["📂 گزارش های در انتظار"],["⬅️ بازگشت"]]

        await update.message.reply_text(
        "پنل مدیریت",
        reply_markup=ReplyKeyboardMarkup(kb,resize_keyboard=True)
        )

        return ADMIN_PANEL

    return MAIN_MENU

# ---------------- REPORT FORM ----------------

async def report_form(update:Update,context:ContextTypes.DEFAULT_TYPE):

    text = update.message.text
    data = context.user_data["report"]

    if "نام" in text:

        context.user_data["field"]="name"
        await update.message.reply_text("نام را وارد کنید")
        return WAITING_INPUT

    if "شماره کارت" in text:

        await update.message.reply_text("شماره کارت را ارسال کنید")
        return ADDING_CARDS

    if "آیدی تلگرام" in text:

        context.user_data["field"]="telegram_id"
        await update.message.reply_text("آیدی تلگرام")
        return WAITING_INPUT

    if "توضیحات" in text:

        context.user_data["field"]="description"
        await update.message.reply_text("شرح ماجرا")
        return WAITING_INPUT

    if text == "📎 ارسال مدرک":

        await update.message.reply_text("تصویر ارسال کنید")
        return ADDING_EVIDENCE

    if text == "✅ ثبت نهایی":

        await update.message.reply_text(
        "آیا ارسال شود؟",
        reply_markup=ReplyKeyboardMarkup(
        [["✅ بله"],["❌ لغو"]],
        resize_keyboard=True)
        )

        return CONFIRM_REPORT

    if text == "❌ لغو":

        return await cancel(update,context)

    return REPORT_FORM

# ---------------- INPUT FIELD ----------------

async def field_input(update:Update,context:ContextTypes.DEFAULT_TYPE):

    field = context.user_data["field"]
    context.user_data["report"][field]=update.message.text

    await update.message.reply_text(
    "ثبت شد",
    reply_markup=report_keyboard(context.user_data["report"])
    )

    return REPORT_FORM

# ---------------- ADD CARD ----------------

async def add_card(update:Update,context:ContextTypes.DEFAULT_TYPE):

    card = update.message.text

    context.user_data["report"]["cards"].append(card)

    await update.message.reply_text("کارت ثبت شد\nکارت بعدی یا پایان")

    return ADDING_CARDS

# ---------------- ADD EVIDENCE ----------------

async def add_evidence(update:Update,context:ContextTypes.DEFAULT_TYPE):

    photo = update.message.photo[-1].file_id

    context.user_data["report"]["evidence"].append(photo)

    await update.message.reply_text("مدرک ثبت شد")

    return ADDING_EVIDENCE

# ---------------- CONFIRM ----------------

async def confirm(update:Update,context:ContextTypes.DEFAULT_TYPE):

    if update.message.text == "✅ بله":

        data = context.user_data["report"]

        conn = sqlite3.connect("bot.db")
        cur = conn.cursor()

        cur.execute(
        "INSERT INTO reports(name,telegram_id,description,reporter,status) VALUES(?,?,?,?,?)",
        (
        data.get("name"),
        data.get("telegram_id"),
        data.get("description"),
        update.effective_user.id,
        "pending"
        )
        )

        report_id = cur.lastrowid

        for c in data["cards"]:
            cur.execute(
            "INSERT INTO cards(report_id,card_number) VALUES(?,?)",
            (report_id,c)
            )

        for e in data["evidence"]:
            cur.execute(
            "INSERT INTO evidence(report_id,file_id) VALUES(?,?)",
            (report_id,e)
            )

        conn.commit()
        conn.close()

        await update.message.reply_text("✅ گزارش ثبت شد")

        return MAIN_MENU

    return MAIN_MENU

# ---------------- ADMIN PANEL ----------------

async def admin_panel(update:Update,context:ContextTypes.DEFAULT_TYPE):

    if update.message.text == "📂 گزارش های در انتظار":

        conn = sqlite3.connect("bot.db")
        cur = conn.cursor()

        cur.execute(
        "SELECT id,name FROM reports WHERE status='pending'"
        )

        rows = cur.fetchall()

        kb = []

        for r in rows:
            kb.append([f"📄 #{r[0]} | {r[1]}"])

        kb.append(["⬅️ بازگشت"])

        await update.message.reply_text(
        "گزارش ها",
        reply_markup=ReplyKeyboardMarkup(kb,resize_keyboard=True)
        )

        return ADMIN_PENDING

    return ADMIN_PANEL

# ---------------- ADMIN REVIEW ----------------

async def admin_pending(update:Update,context:ContextTypes.DEFAULT_TYPE):

    text = update.message.text

    if text.startswith("📄"):

        report_id = int(text.split("#")[1].split("|")[0])

        context.user_data["review_id"]=report_id

        conn = sqlite3.connect("bot.db")
        cur = conn.cursor()

        cur.execute(
        "SELECT name,description FROM reports WHERE id=?",
        (report_id,)
        )

        r = cur.fetchone()

        await update.message.reply_text(
        f"گزارش #{report_id}\n\nنام:{r[0]}\n\nشرح:{r[1]}",
        reply_markup=ReplyKeyboardMarkup(
        [
        ["✅ تایید","❌ رد"],
        ["🗑 حذف"],
        ["⬅️ بازگشت"]
        ],
        resize_keyboard=True
        )
        )

        return ADMIN_REVIEW

    return ADMIN_PENDING

async def admin_review(update:Update,context:ContextTypes.DEFAULT_TYPE):

    report_id = context.user_data["review_id"]
    text = update.message.text

    conn = sqlite3.connect("bot.db")
    cur = conn.cursor()

    if text == "✅ تایید":

        cur.execute(
        "UPDATE reports SET status='approved' WHERE id=?",
        (report_id,)
        )

    if text == "❌ رد":

        cur.execute(
        "UPDATE reports SET status='rejected' WHERE id=?",
        (report_id,)
        )

    if text == "🗑 حذف":

        cur.execute("DELETE FROM reports WHERE id=?",(report_id,))

    conn.commit()
    conn.close()

    await update.message.reply_text("عملیات انجام شد")

    return ADMIN_PANEL

# ---------------- CANCEL ----------------

async def cancel(update:Update,context:ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
    "لغو شد",
    reply_markup=main_menu(update.effective_user.id)
    )

    return MAIN_MENU

# ---------------- MAIN ----------------

def main():

    init_db()

    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(

    entry_points=[CommandHandler("start",start)],

    states={

    MAIN_MENU:[
    MessageHandler(filters.TEXT,main_menu_handler)
    ],

    REPORT_FORM:[
    MessageHandler(filters.TEXT,report_form)
    ],

    WAITING_INPUT:[
    MessageHandler(filters.TEXT,field_input)
    ],

    ADDING_CARDS:[
    MessageHandler(filters.TEXT,add_card)
    ],

    ADDING_EVIDENCE:[
    MessageHandler(filters.PHOTO,add_evidence)
    ],

    CONFIRM_REPORT:[
    MessageHandler(filters.TEXT,confirm)
    ],

    ADMIN_PANEL:[
    MessageHandler(filters.TEXT,admin_panel)
    ],

    ADMIN_PENDING:[
    MessageHandler(filters.TEXT,admin_pending)
    ],

    ADMIN_REVIEW:[
    MessageHandler(filters.TEXT,admin_review)
    ]

    },

    fallbacks=[CommandHandler("cancel",cancel)]

    )

    app.add_handler(conv)

    app.run_polling()

if __name__ == "__main__":
    main()
