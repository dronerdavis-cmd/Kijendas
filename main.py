import os
import sqlite3
import random
import string
import logging
from datetime import datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InputMediaPhoto
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

# ---------------- DATABASE ----------------

def init_db():
    conn = sqlite3.connect("reports.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS reports(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_code TEXT,
        user_id INTEGER,
        name TEXT,
        card TEXT,
        username TEXT,
        phone TEXT,
        amount TEXT,
        description TEXT,
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS photos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_code TEXT,
        file_id TEXT
    )
    """)

    conn.commit()
    conn.close()


# ---------------- KEYBOARDS ----------------

def main_menu():
    return ReplyKeyboardMarkup(
        [["📝 ثبت گزارش جدید"]],
        resize_keyboard=True
    )


def form_keyboard():

    return ReplyKeyboardMarkup(
        [
            ["👤 نام", "💳 شماره کارت"],
            ["🆔 یوزرنیم", "📞 تلفن"],
            ["💰 مبلغ کلاهبرداری"],
            ["📝 شرح گزارش"],
            ["📎 ارسال مدارک"],
            ["✅ ثبت نهایی", "❌ لغو"]
        ],
        resize_keyboard=True
    )


# ---------------- REVIEW TEXT ----------------

def build_review(data):

    return f"""
📄 پیش‌نویس گزارش

👤 نام: {data['name'] or '—'}

💳 شماره کارت: {data['card'] or '—'}

🆔 یوزرنیم تلگرام: {data['username'] or '—'}

📞 شماره تلفن: {data['phone'] or '—'}

💰 مبلغ کلاهبرداری: {data['amount'] or '—'}

📝 شرح گزارش:
{data['desc'] or '—'}

📎 مدارک: {len(data['photos'])}
"""


# ---------------- START ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "به ربات گزارش کلاهبرداری خوش آمدید.",
        reply_markup=main_menu()
    )


# ---------------- START REPORT ----------------

async def start_report(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["report"] = {
        "name": None,
        "card": None,
        "username": None,
        "phone": None,
        "amount": None,
        "desc": None,
        "photos": []
    }

    context.user_data["waiting_for"] = None

    review = await update.message.reply_text(
        build_review(context.user_data["report"])
    )

    context.user_data["review_msg_id"] = review.message_id

    await update.message.reply_text(
        "یکی از بخش‌های گزارش را انتخاب کنید:",
        reply_markup=form_keyboard()
    )


# ---------------- FIELD SELECTION ----------------

async def choose_field(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text

    mapping = {
        "👤 نام": ("name", "نام کامل متهم را وارد کنید"),
        "💳 شماره کارت": ("card", "شماره کارت ۱۶ رقمی را وارد کنید"),
        "🆔 یوزرنیم": ("username", "یوزرنیم تلگرام را وارد کنید"),
        "📞 تلفن": ("phone", "شماره تلفن را وارد کنید"),
        "💰 مبلغ کلاهبرداری": ("amount", "مبلغ کلاهبرداری را وارد کنید"),
        "📝 شرح گزارش": ("desc", "شرح کامل کلاهبرداری را بنویسید"),
    }

    if text not in mapping:
        return

    field, question = mapping[text]

    prompt = await update.message.reply_text(question)

    context.user_data["waiting_for"] = field
    context.user_data["prompt_msg_id"] = prompt.message_id


# ---------------- RECEIVE VALUE ----------------

async def receive_value(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("waiting_for"):
        return

    field = context.user_data["waiting_for"]

    context.user_data["report"][field] = update.message.text

    # delete user message
    await update.message.delete()

    # delete question
    try:
        await context.bot.delete_message(
            update.effective_chat.id,
            context.user_data["prompt_msg_id"]
        )
    except:
        pass

    # update review
    await context.bot.edit_message_text(
        build_review(context.user_data["report"]),
        update.effective_chat.id,
        context.user_data["review_msg_id"]
    )

    context.user_data["waiting_for"] = None


# ---------------- PHOTOS ----------------

async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message.photo is None:
        return

    photo_id = update.message.photo[-1].file_id

    context.user_data["report"]["photos"].append(photo_id)

    await update.message.delete()

    await context.bot.edit_message_text(
        build_review(context.user_data["report"]),
        update.effective_chat.id,
        context.user_data["review_msg_id"]
    )


# ---------------- FINALIZE ----------------

def generate_case():

    return "CASE-" + "".join(random.choices(string.digits, k=6))


async def finalize(update: Update, context: ContextTypes.DEFAULT_TYPE):

    data = context.user_data["report"]

    if not data["card"] or not data["desc"]:
        await update.message.reply_text("حداقل شماره کارت و شرح گزارش باید ثبت شود.")
        return

    case_code = generate_case()

    conn = sqlite3.connect("reports.db")
    c = conn.cursor()

    c.execute("""
    INSERT INTO reports
    (case_code,user_id,name,card,username,phone,amount,description,created_at)
    VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        case_code,
        update.effective_user.id,
        data["name"],
        data["card"],
        data["username"],
        data["phone"],
        data["amount"],
        data["desc"],
        datetime.now().isoformat()
    ))

    for p in data["photos"]:
        c.execute(
            "INSERT INTO photos (case_code,file_id) VALUES (?,?)",
            (case_code, p)
        )

    conn.commit()
    conn.close()

    final_text = f"""
✅ گزارش ثبت شد

شماره پرونده:
{case_code}

👤 نام: {data['name']}
💳 کارت: {data['card']}
🆔 یوزرنیم: {data['username']}
📞 تلفن: {data['phone']}
💰 مبلغ: {data['amount']}

📝 شرح:
{data['desc']}
"""

    await context.bot.delete_message(
        update.effective_chat.id,
        context.user_data["review_msg_id"]
    )

    if data["photos"]:

        media = []

        media.append(
            InputMediaPhoto(
                data["photos"][0],
                caption=final_text
            )
        )

        for p in data["photos"][1:10]:
            media.append(InputMediaPhoto(p))

        await context.bot.send_media_group(
            update.effective_chat.id,
            media
        )

    else:

        await update.message.reply_text(final_text)

    await update.message.reply_text(
        "گزارش شما با موفقیت ثبت شد.",
        reply_markup=main_menu()
    )


# ---------------- CANCEL ----------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    try:
        await context.bot.delete_message(
            update.effective_chat.id,
            context.user_data["review_msg_id"]
        )
    except:
        pass

    context.user_data.clear()

    await update.message.reply_text(
        "گزارش لغو شد.",
        reply_markup=main_menu()
    )


# ---------------- MAIN ----------------

def main():

    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(MessageHandler(
        filters.Regex("^📝 ثبت گزارش جدید$"),
        start_report
    ))

    app.add_handler(MessageHandler(
        filters.Regex("^(👤 نام|💳 شماره کارت|🆔 یوزرنیم|📞 تلفن|💰 مبلغ کلاهبرداری|📝 شرح گزارش)$"),
        choose_field
    ))

    app.add_handler(MessageHandler(
        filters.Regex("^✅ ثبت نهایی$"),
        finalize
    ))

    app.add_handler(MessageHandler(
        filters.Regex("^❌ لغو$"),
        cancel
    ))

    app.add_handler(MessageHandler(
        filters.PHOTO,
        receive_photo
    ))

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        receive_value
    ))

    app.run_polling()


if __name__ == "__main__":
    main()
