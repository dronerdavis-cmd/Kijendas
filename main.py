import sqlite3
import re
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

TOKEN = "PUT_BOT_TOKEN"
ADMIN_IDS = [123456789]

MAX_EVIDENCE = 10
DAILY_LIMIT = 5

logging.basicConfig(level=logging.INFO)

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

    conn=db()
    cur=conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY,
    username TEXT
    )
    """)

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

# ---------------- VALIDATION ----------------

def valid_card(card):
    return re.fullmatch(r"\d{16}",card)

def valid_tg(tg):
    return re.fullmatch(r"@?[A-Za-z0-9_]{5,32}",tg)

# ---------------- KEYBOARDS ----------------

def main_menu(uid):

    kb=[
    ["🔎 جستجو"],
    ["📝 ثبت گزارش"],
    ["👤 حساب من"]
    ]

    if uid in ADMIN_IDS:
        kb.append(["🛡 پنل مدیریت"])

    return ReplyKeyboardMarkup(kb,resize_keyboard=True)

def report_kb(data):

    def s(v): return "✅" if v else "⬜"

    kb=[
    [f"{s(data.get('name'))} نام",f"{s(data.get('cards'))} کارت"],
    [f"{s(data.get('telegram'))} آیدی تلگرام"],
    [f"{s(data.get('desc'))} توضیحات"],
    [f"{s(data.get('evidence'))} مدرک"],
    ["✅ ثبت نهایی"],
    ["❌ لغو"]
    ]

    return ReplyKeyboardMarkup(kb,resize_keyboard=True)

# ---------------- START ----------------

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):

    user=update.effective_user

    conn=db()
    cur=conn.cursor()

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

    text=update.message.text

    if text=="📝 ثبت گزارش":

        conn=db()
        cur=conn.cursor()

        cur.execute("""
        SELECT COUNT(*)
        FROM reports
        WHERE reporter=? 
        AND date(created_at)=date('now')
        """,(update.effective_user.id,))

        if cur.fetchone()[0]>=DAILY_LIMIT:

            await update.message.reply_text("حداکثر گزارش روزانه ثبت شده")

            return MAIN_MENU

        context.user_data["report"]={
        "cards":[],
        "evidence":[]
        }

        await update.message.reply_text(
        "فرم گزارش را کامل کنید",
        reply_markup=report_kb(context.user_data["report"])
        )

        return REPORT_FORM

    if text=="🔎 جستجو":

        await update.message.reply_text("نام یا کارت ارسال کنید")

        return SEARCH

    if text=="🛡 پنل مدیریت":

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

    text=update.message.text
    data=context.user_data["report"]

    if "نام" in text:

        context.user_data["field"]="name"
        await update.message.reply_text("نام را ارسال کنید")
        return WAIT_FIELD

    if "کارت" in text:

        await update.message.reply_text("شماره کارت 16 رقمی\nپایان /done")
        return ADD_CARD

    if "آیدی" in text:

        context.user_data["field"]="telegram"
        await update.message.reply_text("آیدی تلگرام")
        return WAIT_FIELD

    if "توضیحات" in text:

        context.user_data["field"]="desc"
        await update.message.reply_text("شرح ماجرا")
        return WAIT_FIELD

    if "مدرک" in text:

        await update.message.reply_text("عکس ارسال کنید\nپایان /done")
        return ADD_EVIDENCE

    if text=="✅ ثبت نهایی":

        await update.message.reply_text(
        "آیا ارسال شود؟",
        reply_markup=ReplyKeyboardMarkup(
        [["✅ ارسال"],["❌ لغو"]],
        resize_keyboard=True)
        )

        return CONFIRM_REPORT

    if text=="❌ لغو":
        return await cancel(update,context)

    return REPORT_FORM

# ---------------- FIELD INPUT ----------------

async def field_input(update:Update,context:ContextTypes.DEFAULT_TYPE):

    field=context.user_data["field"]
    context.user_data["report"][field]=update.message.text

    await update.message.reply_text(
    "ثبت شد",
    reply_markup=report_kb(context.user_data["report"])
    )

    return REPORT_FORM

# ---------------- CARD ----------------

async def add_card(update:Update,context:ContextTypes.DEFAULT_TYPE):

    text=update.message.text

    if text=="/done":

        await update.message.reply_text(
        "پایان کارت‌ها",
        reply_markup=report_kb(context.user_data["report"])
        )

        return REPORT_FORM

    if not valid_card(text):

        await update.message.reply_text("کارت معتبر نیست")

        return ADD_CARD

    context.user_data["report"]["cards"].append(text)

    await update.message.reply_text("ثبت شد")

    return ADD_CARD

# ---------------- EVIDENCE ----------------

async def add_evidence(update:Update,context:ContextTypes.DEFAULT_TYPE):

    if update.message.text=="/done":

        await update.message.reply_text(
        "مدارک ثبت شد",
        reply_markup=report_kb(context.user_data["report"])
        )

        return REPORT_FORM

    if len(context.user_data["report"]["evidence"])>=MAX_EVIDENCE:

        await update.message.reply_text("حداکثر 10 مدرک")

        return ADD_EVIDENCE

    file=update.message.photo[-1].file_id

    context.user_data["report"]["evidence"].append(file)

    await update.message.reply_text("مدرک ذخیره شد")

    return ADD_EVIDENCE

# ---------------- CONFIRM ----------------

async def confirm(update:Update,context:ContextTypes.DEFAULT_TYPE):

    if update.message.text!="✅ ارسال":
        return MAIN_MENU

    data=context.user_data["report"]

    conn=db()
    cur=conn.cursor()

    cur.execute("""
    INSERT INTO reports(name,telegram_id,description,reporter,status)
    VALUES(?,?,?,?,?)
    """,(
    data.get("name"),
    data.get("telegram"),
    data.get("desc"),
    update.effective_user.id,
    "pending"
    ))

    rid=cur.lastrowid

    for c in data["cards"]:
        cur.execute("INSERT INTO cards(report_id,card) VALUES(?,?)",(rid,c))

    for e in data["evidence"]:
        cur.execute("INSERT INTO evidence(report_id,file_id) VALUES(?,?)",(rid,e))

    conn.commit()
    conn.close()

    await update.message.reply_text(
    "✅ گزارش ثبت شد",
    reply_markup=main_menu(update.effective_user.id)
    )

    return MAIN_MENU

# ---------------- SEARCH ----------------

async def search(update:Update,context:ContextTypes.DEFAULT_TYPE):

    q=update.message.text

    conn=db()
    cur=conn.cursor()

    cur.execute("""
    SELECT reports.id,name,description
    FROM reports
    LEFT JOIN cards ON reports.id=cards.report_id
    WHERE status='approved'
    AND (
    name LIKE ?
    OR telegram_id LIKE ?
    OR cards.card LIKE ?
    )
    """,(f"%{q}%",f"%{q}%",f"%{q}%"))

    rows=cur.fetchall()

    if not rows:

        await update.message.reply_text("موردی یافت نشد")

        return MAIN_MENU

    msg="⚠️ گزارش قبلی یافت شد\n\n"

    for r in rows:

        msg+=f"گزارش #{r[0]}\nنام:{r[1]}\n{r[2]}\n\n"

    await update.message.reply_text(msg)

    return MAIN_MENU

# ---------------- ADMIN ----------------

async def admin_panel(update:Update,context:ContextTypes.DEFAULT_TYPE):

    if update.message.text=="📂 گزارش‌های در انتظار":

        conn=db()
        cur=conn.cursor()

        cur.execute("SELECT id,name FROM reports WHERE status='pending'")

        rows=cur.fetchall()

        kb=[[f"📄 {r[0]} | {r[1]}"] for r in rows]

        kb.append(["⬅️ بازگشت"])

        await update.message.reply_text(
        "گزارش‌ها",
        reply_markup=ReplyKeyboardMarkup(kb,resize_keyboard=True)
        )

        return ADMIN_LIST

    return ADMIN_PANEL

async def admin_list(update:Update,context:ContextTypes.DEFAULT_TYPE):

    text=update.message.text

    if not text.startswith("📄"):
        return ADMIN_LIST

    rid=int(text.split()[1])

    context.user_data["rid"]=rid

    conn=db()
    cur=conn.cursor()

    cur.execute("SELECT name,description FROM reports WHERE id=?",(rid,))
    r=cur.fetchone()

    msg=f"گزارش #{rid}\n\nنام:{r[0]}\n\n{r[1]}"

    kb=[
    ["✅ تایید","❌ رد"],
    ["🗑 حذف"],
    ["🖼 مدارک"],
    ["⬅️ بازگشت"]
    ]

    await update.message.reply_text(
    msg,
    reply_markup=ReplyKeyboardMarkup(kb,resize_keyboard=True)
    )

    return ADMIN_VIEW

async def admin_view(update:Update,context:ContextTypes.DEFAULT_TYPE):

    rid=context.user_data["rid"]
    text=update.message.text

    conn=db()
    cur=conn.cursor()

    if text=="✅ تایید":
        cur.execute("UPDATE reports SET status='approved' WHERE id=?",(rid,))

    elif text=="❌ رد":
        cur.execute("UPDATE reports SET status='rejected' WHERE id=?",(rid,))

    elif text=="🗑 حذف":
        cur.execute("DELETE FROM reports WHERE id=?",(rid,))

    elif text=="🖼 مدارک":

        cur.execute("SELECT file_id FROM evidence WHERE report_id=?",(rid,))
        rows=cur.fetchall()

        for r in rows:
            await update.message.reply_photo(r[0])

        return ADMIN_VIEW

    conn.commit()
    conn.close()

    await update.message.reply_text("انجام شد")

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

    MAIN_MENU:[MessageHandler(filters.TEXT,main_menu_handler)],

    REPORT_FORM:[MessageHandler(filters.TEXT,report_form)],

    WAIT_FIELD:[MessageHandler(filters.TEXT,field_input)],

    ADD_CARD:[MessageHandler(filters.TEXT,add_card)],

    ADD_EVIDENCE:[MessageHandler(filters.PHOTO | filters.TEXT,add_evidence)],

    CONFIRM_REPORT:[MessageHandler(filters.TEXT,confirm)],

    SEARCH:[MessageHandler(filters.TEXT,search)],

    ADMIN_PANEL:[MessageHandler(filters.TEXT,admin_panel)],

    ADMIN_LIST:[MessageHandler(filters.TEXT,admin_list)],

    ADMIN_VIEW:[MessageHandler(filters.TEXT,admin_view)]

    },

    fallbacks=[CommandHandler("cancel",cancel)]

    )

    app.add_handler(conv)

    print("Bot Started")

    app.run_polling()

if __name__=="__main__":
    main()
