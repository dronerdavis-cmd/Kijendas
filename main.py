import sqlite3
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
Application,
CommandHandler,
MessageHandler,
ConversationHandler,
ContextTypes,
filters
)

TOKEN = "PUT_BOT_TOKEN"
ADMIN_IDS = [123456789]

logging.basicConfig(level=logging.INFO)

(
MAIN_MENU,
REPORT_FORM,
WAITING_INPUT,
ADDING_CARDS,
ADDING_EVIDENCE,
CONFIRM_REPORT,
SEARCH_INPUT,
ADMIN_PANEL,
ADMIN_PENDING,
ADMIN_REVIEW
) = range(10)

# ---------------- DATABASE ----------------

def db():
    return sqlite3.connect("bot.db")

def init_db():

    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
    telegram_id INTEGER PRIMARY KEY,
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
    card TEXT
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
        ["🔎 جستجوی کلاهبردار"],
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
        [f"{s(data.get('evidence'))} ارسال مدرک"],
        ["✅ ثبت نهایی گزارش"],
        ["❌ لغو"]
    ]

    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ---------------- START ----------------

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    conn = db()
    cur = conn.cursor()

    cur.execute(
    "INSERT OR IGNORE INTO users VALUES(?,?)",
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

        context.user_data["report"]={
            "cards":[],
            "evidence":[]
        }

        await update.message.reply_text(
        "فرم گزارش را تکمیل کنید",
        reply_markup=report_keyboard(context.user_data["report"])
        )

        return REPORT_FORM

    if text == "🔎 جستجوی کلاهبردار":

        await update.message.reply_text(
        "نام / کارت / آیدی را ارسال کنید"
        )

        return SEARCH_INPUT

    if text == "🛡 پنل مدیریت":

        if update.effective_user.id not in ADMIN_IDS:
            return MAIN_MENU

        kb=[["📂 گزارش‌های در انتظار"],["⬅️ بازگشت"]]

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
        await update.message.reply_text("نام را ارسال کنید")
        return WAITING_INPUT

    if "شماره کارت" in text:

        await update.message.reply_text("شماره کارت را ارسال کنید\nبرای پایان /done")
        return ADDING_CARDS

    if "آیدی" in text:

        context.user_data["field"]="telegram_id"
        await update.message.reply_text("آیدی تلگرام")
        return WAITING_INPUT

    if "توضیحات" in text:

        context.user_data["field"]="description"
        await update.message.reply_text("شرح ماجرا")
        return WAITING_INPUT

    if "مدرک" in text:

        await update.message.reply_text("تصویر ارسال کنید\nپایان /done")
        return ADDING_EVIDENCE

    if text == "✅ ثبت نهایی گزارش":

        await update.message.reply_text(
        "آیا گزارش ارسال شود؟",
        reply_markup=ReplyKeyboardMarkup(
        [["✅ بله ارسال شود"],["✏️ ویرایش گزارش"],["❌ لغو"]],
        resize_keyboard=True
        )
        )

        return CONFIRM_REPORT

    if text == "❌ لغو":

        return await cancel(update,context)

    return REPORT_FORM

# ---------------- FIELD INPUT ----------------

async def field_input(update:Update,context:ContextTypes.DEFAULT_TYPE):

    field=context.user_data["field"]
    context.user_data["report"][field]=update.message.text

    await update.message.reply_text(
    "ثبت شد",
    reply_markup=report_keyboard(context.user_data["report"])
    )

    return REPORT_FORM

# ---------------- ADD CARD ----------------

async def add_card(update:Update,context:ContextTypes.DEFAULT_TYPE):

    text=update.message.text

    if text=="/done":

        await update.message.reply_text(
        "ثبت کارت‌ها پایان یافت",
        reply_markup=report_keyboard(context.user_data["report"])
        )

        return REPORT_FORM

    context.user_data["report"]["cards"].append(text)

    await update.message.reply_text("کارت ثبت شد\nکارت بعدی یا /done")

    return ADDING_CARDS

# ---------------- ADD EVIDENCE ----------------

async def add_evidence(update:Update,context:ContextTypes.DEFAULT_TYPE):

    if update.message.text=="/done":

        await update.message.reply_text(
        "ارسال مدارک پایان یافت",
        reply_markup=report_keyboard(context.user_data["report"])
        )

        return REPORT_FORM

    photo=update.message.photo[-1].file_id

    context.user_data["report"]["evidence"].append(photo)

    await update.message.reply_text("مدرک ثبت شد")

    return ADDING_EVIDENCE

# ---------------- CONFIRM ----------------

async def confirm(update:Update,context:ContextTypes.DEFAULT_TYPE):

    text=update.message.text

    if text!="✅ بله ارسال شود":
        return MAIN_MENU

    data=context.user_data["report"]

    conn=db()
    cur=conn.cursor()

    cur.execute("""
    INSERT INTO reports(name,telegram_id,description,reporter,status)
    VALUES(?,?,?,?,?)
    """,(
    data.get("name"),
    data.get("telegram_id"),
    data.get("description"),
    update.effective_user.id,
    "pending"
    ))

    report_id=cur.lastrowid

    for c in data["cards"]:
        cur.execute(
        "INSERT INTO cards(report_id,card) VALUES(?,?)",
        (report_id,c)
        )

    for e in data["evidence"]:
        cur.execute(
        "INSERT INTO evidence(report_id,file_id) VALUES(?,?)",
        (report_id,e)
        )

    conn.commit()
    conn.close()

    await update.message.reply_text(
    "✅ گزارش شما ثبت شد و در انتظار بررسی است",
    reply_markup=main_menu(update.effective_user.id)
    )

    return MAIN_MENU

# ---------------- SEARCH ----------------

async def search(update:Update,context:ContextTypes.DEFAULT_TYPE):

    query=update.message.text

    conn=db()
    cur=conn.cursor()

    cur.execute("""
    SELECT reports.id,reports.name,reports.description
    FROM reports
    LEFT JOIN cards ON reports.id=cards.report_id
    WHERE reports.status='approved'
    AND (
    reports.name LIKE ?
    OR reports.telegram_id LIKE ?
    OR cards.card LIKE ?
    )
    """,(f"%{query}%",f"%{query}%",f"%{query}%"))

    rows=cur.fetchall()

    if not rows:

        await update.message.reply_text("موردی یافت نشد")

        return MAIN_MENU

    msg="⚠️ این مورد قبلا گزارش شده\n\n"

    for r in rows:
        msg+=f"📄 گزارش #{r[0]}\nنام: {r[1]}\nشرح: {r[2]}\n\n"

    await update.message.reply_text(msg)

    return MAIN_MENU

# ---------------- ADMIN PANEL ----------------

async def admin_panel(update:Update,context:ContextTypes.DEFAULT_TYPE):

    if update.message.text=="📂 گزارش‌های در انتظار":

        conn=db()
        cur=conn.cursor()

        cur.execute(
        "SELECT id,name FROM reports WHERE status='pending'"
        )

        rows=cur.fetchall()

        kb=[]

        for r in rows:
            kb.append([f"📄 #{r[0]} | {r[1]}"])

        kb.append(["⬅️ بازگشت"])

        await update.message.reply_text(
        "گزارش‌ها",
        reply_markup=ReplyKeyboardMarkup(kb,resize_keyboard=True)
        )

        return ADMIN_PENDING

    return ADMIN_PANEL

# ---------------- ADMIN SELECT REPORT ----------------

async def admin_pending(update:Update,context:ContextTypes.DEFAULT_TYPE):

    text=update.message.text

    if not text.startswith("📄"):
        return ADMIN_PENDING

    report_id=int(text.split("#")[1].split("|")[0])

    context.user_data["review"]=report_id

    conn=db()
    cur=conn.cursor()

    cur.execute(
    "SELECT name,description FROM reports WHERE id=?",
    (report_id,)
    )

    r=cur.fetchone()

    cur.execute(
    "SELECT card FROM cards WHERE report_id=?",
    (report_id,)
    )

    cards=cur.fetchall()

    msg=f"📄 گزارش #{report_id}\n\nنام: {r[0]}\n\n"

    msg+="کارت‌ها:\n"

    for c in cards:
        msg+=c[0]+"\n"

    msg+=f"\nشرح:\n{r[1]}"

    kb=[
    ["✅ تایید گزارش","❌ رد گزارش"],
    ["🗑 حذف کامل"],
    ["🖼 مشاهده مدارک"],
    ["⬅️ بازگشت"]
    ]

    await update.message.reply_text(
    msg,
    reply_markup=ReplyKeyboardMarkup(kb,resize_keyboard=True)
    )

    return ADMIN_REVIEW

# ---------------- ADMIN ACTION ----------------

async def admin_review(update:Update,context:ContextTypes.DEFAULT_TYPE):

    text=update.message.text
    report_id=context.user_data["review"]

    conn=db()
    cur=conn.cursor()

    if text=="✅ تایید گزارش":

        cur.execute(
        "UPDATE reports SET status='approved' WHERE id=?",
        (report_id,)
        )

    elif text=="❌ رد گزارش":

        cur.execute(
        "UPDATE reports SET status='rejected' WHERE id=?",
        (report_id,)
        )

    elif text=="🗑 حذف کامل":

        cur.execute("DELETE FROM reports WHERE id=?",(report_id,))

    elif text=="🖼 مشاهده مدارک":

        cur.execute(
        "SELECT file_id FROM evidence WHERE report_id=?",
        (report_id,)
        )

        files=cur.fetchall()

        for f in files:
            await update.message.reply_photo(f[0])

        return ADMIN_REVIEW

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

    app=Application.builder().token(TOKEN).build()

    conv=ConversationHandler(

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
    MessageHandler(filters.PHOTO | filters.TEXT,add_evidence)
    ],

    CONFIRM_REPORT:[
    MessageHandler(filters.TEXT,confirm)
    ],

    SEARCH_INPUT:[
    MessageHandler(filters.TEXT,search)
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

    print("Bot Started...")

    app.run_polling()

if __name__=="__main__":
    main()
