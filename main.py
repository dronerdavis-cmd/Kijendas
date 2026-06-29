import os
import sqlite3
import logging
import random
import string
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    InputMediaPhoto
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# -----------------------------------
# CONFIG
# -----------------------------------

TOKEN = os.getenv("BOT_TOKEN")

ADMIN_IDS = [
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

logging.basicConfig(level=logging.INFO)

# -----------------------------------
# DATABASE
# -----------------------------------

def db():

    return sqlite3.connect("database.db")


def init_db():

    conn = db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS reports(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_code TEXT,
        reporter_id INTEGER,
        name TEXT,
        phone TEXT,
        tg_id TEXT,
        description TEXT,
        status TEXT,
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS cards(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER,
        card_number TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS evidence(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER,
        file_id TEXT
    )
    """)

    conn.commit()
    conn.close()


# -----------------------------------
# HELPERS
# -----------------------------------

def generate_case_code():

    return "RPT-" + "".join(random.choices(string.digits, k=5))


def main_keyboard(uid):

    kb = [
        ["📝 ثبت گزارش"],
        ["🔎 استعلام سریع"],
        ["👤 پروفایل من"]
    ]

    if uid in ADMIN_IDS:
        kb.insert(0, ["🛡 پنل مدیریت"])

    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


def dashboard_keyboard(rep):

    def c(v):
        return "✅" if v else "⬜"

    def l(v):
        return "✅" if len(v) else "⬜"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{c(rep['name'])} نام",
                callback_data="set_name"
            ),
            InlineKeyboardButton(
                f"{l(rep['cards'])} کارت‌ها",
                callback_data="set_cards"
            )
        ],

        [
            InlineKeyboardButton(
                f"{c(rep['phone'])} تلفن",
                callback_data="set_phone"
            ),
            InlineKeyboardButton(
                f"{c(rep['tg_id'])} تلگرام",
                callback_data="set_tg"
            )
        ],

        [
            InlineKeyboardButton(
                f"{c(rep['desc'])} شرح",
                callback_data="set_desc"
            )
        ],

        [
            InlineKeyboardButton(
                f"{l(rep['evidence'])} مدارک {len(rep['evidence'])}/10",
                callback_data="set_evidence"
            )
        ],

        [
            InlineKeyboardButton(
                "🚀 ثبت نهایی",
                callback_data="final"
            )
        ],

        [
            InlineKeyboardButton(
                "❌ لغو",
                callback_data="cancel"
            )
        ]
    ])


# -----------------------------------
# SEND REPORT (ALBUM)
# -----------------------------------

async def send_report(context, chat_id, rep, case):

    caption = f"""
📂 گزارش کلاهبرداری

🆔 شماره پرونده: {case}

👤 نام: {rep['name'] or "نامشخص"}
📞 تلفن: {rep['phone'] or "نامشخص"}
🆔 تلگرام: {rep['tg_id'] or "نامشخص"}

💳 کارت‌ها:
{",".join(rep['cards']) if rep['cards'] else "ثبت نشده"}

📝 شرح:

{rep['desc']}
"""

    if rep["evidence"]:

        media = []

        media.append(
            InputMediaPhoto(
                rep["evidence"][0],
                caption=caption
            )
        )

        for i in rep["evidence"][1:]:

            media.append(
                InputMediaPhoto(i)
            )

        await context.bot.send_media_group(
            chat_id,
            media
        )

    else:

        await context.bot.send_message(
            chat_id,
            caption
        )


# -----------------------------------
# START
# -----------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    uid = update.effective_user.id

    await update.message.reply_text(

        "به سامانه ثبت گزارش کلاهبرداری خوش آمدید",

        reply_markup=main_keyboard(uid)
    )


# -----------------------------------
# MENU
# -----------------------------------

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text
    uid = update.effective_user.id

    if text == "📝 ثبت گزارش":

        context.user_data["rep"] = {
            "cards": [],
            "name": None,
            "phone": None,
            "tg_id": None,
            "desc": None,
            "evidence": [],
            "step": None
        }

        msg = await update.message.reply_text(

            "📋 داشبورد ثبت گزارش",

            reply_markup=dashboard_keyboard(
                context.user_data["rep"]
            )
        )

        context.user_data["dash"] = msg.message_id

    elif text == "👤 پروفایل من":

        conn = db()
        c = conn.cursor()

        c.execute(

            "SELECT case_code,status FROM reports WHERE reporter_id=?",

            (uid,)
        )

        r = c.fetchall()

        conn.close()

        if not r:

            await update.message.reply_text(
                "گزارشی ندارید"
            )

        else:

            t = ""

            for i in r:

                t += f"{i[0]} | {i[1]}\n"

            await update.message.reply_text(t)

    elif text == "🔎 استعلام سریع":

        await update.message.reply_text(
            "شماره کارت را ارسال کنید"
        )

        context.user_data["search"] = True

    elif text == "🛡 پنل مدیریت" and uid in ADMIN_IDS:

        await admin_panel(update, context)


# -----------------------------------
# SEARCH
# -----------------------------------

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("search"):
        return

    card = update.message.text

    conn = db()
    c = conn.cursor()

    c.execute(
        """
        SELECT reports.case_code
        FROM cards
        JOIN reports
        ON cards.report_id=reports.id
        WHERE cards.card_number=?
        AND reports.status='approved'
        """,
        (card,)
    )

    r = c.fetchall()

    conn.close()

    if r:

        txt = "⚠️ سابقه کلاهبرداری:\n"

        for i in r:

            txt += f"{i[0]}\n"

    else:

        txt = "✅ موردی یافت نشد"

    await update.message.reply_text(txt)

    context.user_data["search"] = False


# -----------------------------------
# DASHBOARD CALLBACK
# -----------------------------------

async def dash(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query

    await q.answer()

    data = q.data

    rep = context.user_data["rep"]

    if data.startswith("set_"):

        context.user_data["rep"]["step"] = data

        msg = await q.message.reply_text(
            "مقدار را ارسال کنید"
        )

        context.user_data["temp"] = msg.message_id

    elif data == "cancel":

        await q.message.delete()

    elif data == "final":

        if not rep["desc"] or not (
            rep["cards"]
            or rep["tg_id"]
            or rep["name"]
        ):

            await q.answer(
                "اطلاعات کافی نیست",
                show_alert=True
            )

            return

        case = generate_case_code()

        conn = db()
        c = conn.cursor()

        c.execute(

            """
            INSERT INTO reports
            (case_code,reporter_id,name,phone,tg_id,description,status,created_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,

            (
                case,
                update.effective_user.id,
                rep["name"],
                rep["phone"],
                rep["tg_id"],
                rep["desc"],
                "pending",
                datetime.now().strftime("%Y-%m-%d")
            )
        )

        rid = c.lastrowid

        for card in rep["cards"]:

            c.execute(
                "INSERT INTO cards(report_id,card_number) VALUES(?,?)",
                (rid, card)
            )

        for img in rep["evidence"]:

            c.execute(
                "INSERT INTO evidence(report_id,file_id) VALUES(?,?)",
                (rid, img)
            )

        conn.commit()
        conn.close()

        await send_report(
            context,
            update.effective_chat.id,
            rep,
            case
        )

        for a in ADMIN_IDS:

            await context.bot.send_message(
                a,
                f"گزارش جدید {case}"
            )


# -----------------------------------
# INPUT HANDLER
# -----------------------------------

async def input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if "rep" not in context.user_data:
        return

    rep = context.user_data["rep"]

    step = rep["step"]

    if not step:
        return

    txt = update.message.text

    if step == "set_name":

        rep["name"] = txt

    elif step == "set_phone":

        rep["phone"] = txt

    elif step == "set_tg":

        rep["tg_id"] = txt

    elif step == "set_desc":

        rep["desc"] = txt

    elif step == "set_cards":

        if len(txt) == 16:

            rep["cards"].append(txt)

    if update.message.photo and step == "set_evidence":

        if len(rep["evidence"]) < 10:

            rep["evidence"].append(
                update.message.photo[-1].file_id
            )

    try:

        await update.message.delete()

    except:
        pass

    try:

        await context.bot.delete_message(
            update.effective_chat.id,
            context.user_data["temp"]
        )

    except:
        pass

    await context.bot.edit_message_reply_markup(

        update.effective_chat.id,

        context.user_data["dash"],

        reply_markup=dashboard_keyboard(rep)
    )


# -----------------------------------
# ADMIN PANEL
# -----------------------------------

async def admin_panel(update, context):

    conn = db()
    c = conn.cursor()

    c.execute(
        "SELECT id,case_code FROM reports WHERE status='pending'"
    )

    r = c.fetchall()

    conn.close()

    if not r:

        await update.message.reply_text(
            "گزارشی نیست"
        )

        return

    for i in r:

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "مشاهده",
                    callback_data=f"view_{i[0]}"
                ),
                InlineKeyboardButton(
                    "تایید",
                    callback_data=f"ok_{i[0]}"
                ),
                InlineKeyboardButton(
                    "رد",
                    callback_data=f"no_{i[0]}"
                )
            ]
        ])

        await update.message.reply_text(
            i[1],
            reply_markup=kb
        )


async def admin_actions(update, context):

    q = update.callback_query

    await q.answer()

    data = q.data

    conn = db()
    c = conn.cursor()

    if data.startswith("view_"):

        rid = data.split("_")[1]

        c.execute(
            "SELECT case_code,name,phone,tg_id,description FROM reports WHERE id=?",
            (rid,)
        )

        r = c.fetchone()

        c.execute(
            "SELECT card_number FROM cards WHERE report_id=?",
            (rid,)
        )

        cards = [i[0] for i in c.fetchall()]

        c.execute(
            "SELECT file_id FROM evidence WHERE report_id=?",
            (rid,)
        )

        imgs = [i[0] for i in c.fetchall()]

        rep = {
            "name": r[1],
            "phone": r[2],
            "tg_id": r[3],
            "desc": r[4],
            "cards": cards,
            "evidence": imgs
        }

        await send_report(
            context,
            update.effective_chat.id,
            rep,
            r[0]
        )

    elif data.startswith("ok_"):

        rid = data.split("_")[1]

        c.execute(
            "UPDATE reports SET status='approved' WHERE id=?",
            (rid,)
        )

        conn.commit()

        await q.edit_message_text("✅ تایید شد")

    elif data.startswith("no_"):

        rid = data.split("_")[1]

        c.execute(
            "UPDATE reports SET status='rejected' WHERE id=?",
            (rid,)
        )

        conn.commit()

        await q.edit_message_text("❌ رد شد")

    conn.close()


# -----------------------------------
# MAIN
# -----------------------------------

def main():

    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        menu
    ))

    app.add_handler(CallbackQueryHandler(
        dash,
        pattern="^(set_|final|cancel)"
    ))

    app.add_handler(CallbackQueryHandler(
        admin_actions,
        pattern="^(view_|ok_|no_)"
    ))

    app.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO,
        input_handler
    ))

    app.add_handler(MessageHandler(
        filters.TEXT,
        search
    ))

    print("BOT RUNNING")

    app.run_polling()


if __name__ == "__main__":

    main()
