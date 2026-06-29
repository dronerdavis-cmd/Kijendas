import os
import sqlite3
import random
import string
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ---------------- CONFIG ----------------

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

DB_FILE = "db.sqlite"

# ---------------- DATABASE ----------------

def db():
    return sqlite3.connect(DB_FILE)


def init_db():
    conn = db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_code TEXT,
        user_id INTEGER,
        name TEXT,
        phone TEXT,
        tg TEXT,
        description TEXT,
        status TEXT,
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER,
        card TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER,
        file_id TEXT
    )
    """)

    conn.commit()
    conn.close()


# ---------------- HELPERS ----------------

def case_code():
    return "RPT-" + "".join(random.choices(string.digits, k=6))


def main_kb(uid):
    kb = [
        ["📝 ثبت گزارش"],
        ["🔎 استعلام"],
        ["👤 پروفایل"],
    ]

    if uid in ADMIN_IDS:
        kb.insert(0, ["🛡 پنل"])

    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


def dash_kb(rep):
    def s(x): return "✅" if x else "⬜"
    def l(x): return "✅" if len(x) else "⬜"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{s(rep['name'])} نام", callback_data="name"),
            InlineKeyboardButton(f"{l(rep['cards'])} کارت({len(rep['cards'])})", callback_data="cards"),
        ],
        [
            InlineKeyboardButton(f"{s(rep['phone'])} تلفن", callback_data="phone"),
            InlineKeyboardButton(f"{s(rep['tg'])} تلگرام", callback_data="tg"),
        ],
        [
            InlineKeyboardButton(f"{s(rep['desc'])} توضیح", callback_data="desc"),
        ],
        [
            InlineKeyboardButton(f"📎 مدارک ({len(rep['evidence'])}/10)", callback_data="evi"),
        ],
        [
            InlineKeyboardButton("🚀 ارسال نهایی", callback_data="submit"),
        ],
        [
            InlineKeyboardButton("❌ لغو", callback_data="cancel"),
        ]
    ])


# ---------------- START ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    await update.message.reply_text(
        "سامانه گزارش کلاهبرداری",
        reply_markup=main_kb(uid)
    )


# ---------------- MENU ----------------

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    uid = update.effective_user.id

    if text == "📝 ثبت گزارش":
        context.user_data["rep"] = {
            "name": None,
            "phone": None,
            "tg": None,
            "desc": None,
            "cards": [],
            "evidence": [],
            "step": None,
        }

        msg = await update.message.reply_text(
            "📂 داشبورد گزارش",
            reply_markup=dash_kb(context.user_data["rep"])
        )

        context.user_data["dash_id"] = msg.message_id

    elif text == "🔎 استعلام":
        context.user_data["search"] = True
        await update.message.reply_text("شماره کارت را ارسال کنید")

    elif text == "👤 پروفایل":
        conn = db()
        c = conn.cursor()
        c.execute("SELECT case_code,status FROM reports WHERE user_id=?", (uid,))
        rows = c.fetchall()
        conn.close()

        if not rows:
            await update.message.reply_text("گزارشی ندارید")
        else:
            txt = "\n".join([f"{r[0]} | {r[1]}" for r in rows])
            await update.message.reply_text(txt)

    elif text == "🛡 پنل" and uid in ADMIN_IDS:
        await admin_panel(update, context)


# ---------------- DASHBOARD ACTIONS ----------------

async def dash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    rep = context.user_data["rep"]

    key = q.data

    fields = {
        "name": "نام",
        "phone": "تلفن",
        "tg": "تلگرام",
        "desc": "توضیح",
        "cards": "کارت",
        "evi": "مدارک",
    }

    if key in fields:
        rep["step"] = key

        msg = await q.message.reply_text(f"✍️ وارد کنید: {fields[key]}")
        context.user_data["tmp"] = msg.message_id

    elif key == "cancel":
        context.user_data.clear()
        await q.message.delete()

    elif key == "submit":
        if not rep["desc"]:
            await q.answer("توضیح اجباری است", show_alert=True)
            return

        if not (rep["name"] or rep["cards"] or rep["tg"]):
            await q.answer("حداقل یک شناسه لازم است", show_alert=True)
            return

        code = case_code()

        conn = db()
        c = conn.cursor()

        c.execute("""
        INSERT INTO reports
        (case_code,user_id,name,phone,tg,description,status,created_at)
        VALUES (?,?,?,?,?,?,?,?)
        """, (
            code,
            update.effective_user.id,
            rep["name"],
            rep["phone"],
            rep["tg"],
            rep["desc"],
            "pending",
            datetime.now().isoformat()
        ))

        rid = c.lastrowid

        for card in rep["cards"]:
            c.execute("INSERT INTO cards(report_id,card) VALUES(?,?)", (rid, card))

        for img in rep["evidence"]:
            c.execute("INSERT INTO evidence(report_id,file_id) VALUES(?,?)", (rid, img))

        conn.commit()
        conn.close()

        await q.message.edit_text(f"✅ ثبت شد: {code}")


# ---------------- INPUT ----------------

async def input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "rep" not in context.user_data:
        return

    rep = context.user_data["rep"]
    step = rep["step"]

    if not step:
        return

    if update.message.photo and step == "evi":
        if len(rep["evidence"]) < 10:
            rep["evidence"].append(update.message.photo[-1].file_id)

    elif update.message.text:

        txt = update.message.text

        if step == "name":
            rep["name"] = txt

        elif step == "phone":
            rep["phone"] = txt

        elif step == "tg":
            rep["tg"] = txt

        elif step == "desc":
            rep["desc"] = txt

        elif step == "cards":
            if txt.isdigit() and len(txt) == 16:
                rep["cards"].append(txt)

    try:
        await update.message.delete()
    except:
        pass

    try:
        await context.bot.delete_message(
            update.effective_chat.id,
            context.user_data.get("tmp")
        )
    except:
        pass

    dash_msg = context.user_data.get("dash_id")

    if dash_msg:
        await context.bot.edit_message_reply_markup(
            chat_id=update.effective_chat.id,
            message_id=dash_msg,
            reply_markup=dash_kb(rep)
        )


# ---------------- ADMIN ----------------

async def admin_panel(update, context):
    conn = db()
    c = conn.cursor()

    c.execute("SELECT id,case_code FROM reports WHERE status='pending'")
    rows = c.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("خالی")
        return

    for r in rows:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("view", callback_data=f"v_{r[0]}"),
            InlineKeyboardButton("ok", callback_data=f"a_{r[0]}"),
            InlineKeyboardButton("no", callback_data=f"r_{r[0]}"),
        ]])

        await update.message.reply_text(r[1], reply_markup=kb)


async def admin_actions(update, context):
    q = update.callback_query
    await q.answer()

    conn = db()
    c = conn.cursor()

    if q.data.startswith("a_"):
        rid = q.data.split("_")[1]
        c.execute("UPDATE reports SET status='approved' WHERE id=?", (rid,))
        conn.commit()
        await q.edit_message_text("approved")

    elif q.data.startswith("r_"):
        rid = q.data.split("_")[1]
        c.execute("UPDATE reports SET status='rejected' WHERE id=?", (rid,))
        conn.commit()
        await q.edit_message_text("rejected")

    conn.close()


# ---------------- APP ----------------

def main():
    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu))

    app.add_handler(CallbackQueryHandler(dash, pattern="^(name|phone|tg|desc|cards|evi|submit|cancel)$"))
    app.add_handler(CallbackQueryHandler(admin_actions, pattern="^(a_|r_|v_)"))

    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, input_handler))

    print("RUNNING")
    app.run_polling()


if __name__ == "__main__":
    main()
