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
    ConversationHandler,
    filters
)

# =========================
# Config
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]

DB = "database.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# =========================
# States
# =========================

(
    NAME,
    PHONE,
    TG,
    CARD,
    DESC,
    PHOTO,
    PREVIEW
) = range(7)

# =========================
# Database Layer
# =========================

def db():
    return sqlite3.connect(DB)


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


# =========================
# Helpers
# =========================

def case_code():
    return "RPT-" + "".join(random.choices(string.digits, k=6))


def main_menu(uid):

    kb = [
        ["📝 ثبت گزارش جدید"],
        ["🔎 استعلام کارت"],
        ["👤 پروفایل من"]
    ]

    if uid in ADMIN_IDS:
        kb.insert(0, ["🛡 پنل مدیریت"])

    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


def clean_card(card):
    return card.replace(" ", "").replace("-", "")


# =========================
# Start
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "به ربات گزارش کلاهبرداری خوش آمدید.",
        reply_markup=main_menu(update.effective_user.id)
    )


# =========================
# Report Wizard
# =========================

async def start_report(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["report"] = {
        "cards": [],
        "photos": []
    }

    await update.message.reply_text("نام فرد کلاهبردار را ارسال کنید:")

    return NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["report"]["name"] = update.message.text

    await update.message.reply_text("شماره تلفن را ارسال کنید:")

    return PHONE


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["report"]["phone"] = update.message.text

    await update.message.reply_text("آیدی یا یوزرنیم تلگرام:")

    return TG


async def get_tg(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["report"]["tg"] = update.message.text

    await update.message.reply_text(
        "شماره کارت را ارسال کنید.\n"
        "برای پایان ارسال /done بزنید."
    )

    return CARD


async def get_card(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text

    if text == "/done":
        await update.message.reply_text("شرح کامل کلاهبرداری را بنویسید:")
        return DESC

    card = clean_card(text)

    if len(card) != 16 or not card.isdigit():
        await update.message.reply_text("شماره کارت معتبر نیست.")
        return CARD

    context.user_data["report"]["cards"].append(card)

    await update.message.reply_text("کارت ثبت شد. کارت بعدی یا /done")

    return CARD


async def get_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["report"]["desc"] = update.message.text

    await update.message.reply_text(
        "مدارک را ارسال کنید (حداکثر ۱۰ عکس)\n"
        "برای پایان /done بزنید."
    )

    return PHOTO


async def get_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message.text == "/done":

        data = context.user_data["report"]

        text = (
            "پیش نمایش گزارش\n\n"
            f"نام: {data['name']}\n"
            f"تلفن: {data['phone']}\n"
            f"تلگرام: {data['tg']}\n"
            f"کارت‌ها: {', '.join(data['cards'])}\n\n"
            f"شرح:\n{data['desc']}"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تایید", callback_data="confirm")],
            [InlineKeyboardButton("❌ لغو", callback_data="cancel")]
        ])

        await update.message.reply_text(text, reply_markup=kb)

        return PREVIEW

    if update.message.photo:

        if len(context.user_data["report"]["photos"]) >= 10:
            await update.message.reply_text("حداکثر ۱۰ عکس مجاز است.")
            return PHOTO

        file_id = update.message.photo[-1].file_id

        context.user_data["report"]["photos"].append(file_id)

        await update.message.reply_text("عکس ثبت شد.")

    return PHOTO


# =========================
# Submit Report
# =========================

async def submit(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("گزارش لغو شد.")
        return ConversationHandler.END

    data = context.user_data["report"]

    code = case_code()

    conn = db()
    c = conn.cursor()

    c.execute("""
    INSERT INTO reports
    (case_code,reporter_id,name,phone,tg_id,description,status,created_at)
    VALUES (?,?,?,?,?,?,?,?)
    """,(
        code,
        query.from_user.id,
        data["name"],
        data["phone"],
        data["tg"],
        data["desc"],
        "pending",
        datetime.now().isoformat()
    ))

    rid = c.lastrowid

    for card in data["cards"]:
        c.execute("INSERT INTO cards(report_id,card_number) VALUES (?,?)",(rid,card))

    for photo in data["photos"]:
        c.execute("INSERT INTO evidence(report_id,file_id) VALUES (?,?)",(rid,photo))

    conn.commit()
    conn.close()

    await query.edit_message_text(
        f"✅ گزارش ثبت شد\n\nکد پیگیری:\n{code}"
    )

    return ConversationHandler.END


# =========================
# Card Inquiry
# =========================

async def inquiry(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text("شماره کارت را ارسال کنید:")

    return 100


async def do_inquiry(update: Update, context: ContextTypes.DEFAULT_TYPE):

    card = clean_card(update.message.text)

    conn = db()
    c = conn.cursor()

    c.execute("""
    SELECT reports.case_code,reports.description
    FROM cards
    JOIN reports
    ON cards.report_id = reports.id
    WHERE card_number=?
    AND status='approved'
    """,(card,))

    rows = c.fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text("گزارشی یافت نشد.")
    else:

        txt="⚠️ گزارش یافت شد:\n\n"

        for r in rows:
            txt += f"{r[0]}\n{r[1]}\n\n"

        await update.message.reply_text(txt)

    return ConversationHandler.END


# =========================
# Profile
# =========================

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):

    uid = update.effective_user.id

    conn = db()
    c = conn.cursor()

    c.execute("SELECT case_code,status FROM reports WHERE reporter_id=?",(uid,))
    rows=c.fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text("گزارشی ثبت نکرده‌اید.")
        return

    txt="گزارش‌های شما:\n\n"

    for r in rows:
        txt+=f"{r[0]} — {r[1]}\n"

    await update.message.reply_text(txt)


# =========================
# Admin Panel
# =========================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id not in ADMIN_IDS:
        return

    conn=db()
    c=conn.cursor()

    c.execute("SELECT id,case_code FROM reports WHERE status='pending'")
    rows=c.fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text("پرونده معلقی وجود ندارد.")
        return

    for r in rows:

        kb=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ تایید",callback_data=f"approve_{r[0]}"),
                InlineKeyboardButton("❌ رد",callback_data=f"reject_{r[0]}")
            ]
        ])

        await update.message.reply_text(
            f"گزارش {r[1]}",
            reply_markup=kb
        )


async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query=update.callback_query
    await query.answer()

    action, rid = query.data.split("_")

    conn=db()
    c=conn.cursor()

    status="approved" if action=="approve" else "rejected"

    c.execute("UPDATE reports SET status=? WHERE id=?",(status,rid))

    conn.commit()
    conn.close()

    await query.edit_message_text(f"وضعیت به {status} تغییر کرد.")


# =========================
# Main
# =========================

def main():

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    report_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("ثبت گزارش"), start_report)],
        states={
            NAME:[MessageHandler(filters.TEXT, get_name)],
            PHONE:[MessageHandler(filters.TEXT, get_phone)],
            TG:[MessageHandler(filters.TEXT, get_tg)],
            CARD:[MessageHandler(filters.TEXT, get_card)],
            DESC:[MessageHandler(filters.TEXT, get_desc)],
            PHOTO:[
                MessageHandler(filters.PHOTO | filters.TEXT, get_photo)
            ],
            PREVIEW:[
                CallbackQueryHandler(submit)
            ]
        },
        fallbacks=[]
    )

    inquiry_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("استعلام"), inquiry)],
        states={
            100:[MessageHandler(filters.TEXT, do_inquiry)]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(report_conv)
    app.add_handler(inquiry_conv)

    app.add_handler(MessageHandler(filters.Regex("پروفایل"), profile))
    app.add_handler(MessageHandler(filters.Regex("پنل مدیریت"), admin))

    app.add_handler(CallbackQueryHandler(admin_action,pattern="approve_|reject_"))

    app.run_polling()


if __name__ == "__main__":
    main()
