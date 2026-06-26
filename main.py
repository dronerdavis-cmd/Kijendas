import os
import re
import sqlite3
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

DB_NAME = "database.db"

MENU, REPORT_INPUT, SEARCH_INPUT = range(3)

REPORT_STEPS = [
    {
        "key": "card",
        "title": "💳 شماره کارت",
        "prompt": "💳 شماره کارت فرد موردنظر را وارد کنید:",
        "skip": "ثبت نشده",
    },
    {
        "key": "name",
        "title": "👤 نام و نام خانوادگی",
        "prompt": "👤 نام و نام خانوادگی فرد موردنظر را وارد کنید:",
        "skip": "ثبت نشده",
    },
    {
        "key": "phone",
        "title": "📞 شماره تماس",
        "prompt": "📞 شماره تماس فرد موردنظر را وارد کنید:",
        "skip": "ثبت نشده",
    },
    {
        "key": "username",
        "title": "🆔 آیدی تلگرام",
        "prompt": "🆔 آیدی تلگرام فرد موردنظر را وارد کنید:",
        "skip": "ثبت نشده",
    },
    {
        "key": "amount",
        "title": "💰 مبلغ",
        "prompt": "💰 مبلغ تقریبی را به تومان وارد کنید:",
        "skip": "ثبت نشده",
    },
    {
        "key": "text",
        "title": "📝 شرح گزارش",
        "prompt": "📝 شرح کوتاهی از اتفاق را بنویسید:",
        "skip": "ثبت نشده",
    },
]


def fa_to_en_digits(text: str) -> str:
    if not text:
        return ""

    fa_digits = "۰۱۲۳۴۵۶۷۸۹"
    ar_digits = "٠١٢٣٤٥٦٧٨٩"
    en_digits = "0123456789"

    result = text
    for fa_digit, en_digit in zip(fa_digits, en_digits):
        result = result.replace(fa_digit, en_digit)
    for ar_digit, en_digit in zip(ar_digits, en_digits):
        result = result.replace(ar_digit, en_digit)

    return result


def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = fa_to_en_digits(text)
    text = text.strip().lower()
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_identifier(text: str) -> str:
    if not text:
        return ""

    text = fa_to_en_digits(text)
    text = text.lower().strip()
    text = text.replace("@", "")
    text = re.sub(r"[\s\-_+()]", "", text)
    return text


def calculate_risk_score(report: dict) -> int:
    score = 0

    if report.get("card") and report.get("card") != "ثبت نشده":
        score += 25
    if report.get("phone") and report.get("phone") != "ثبت نشده":
        score += 20
    if report.get("username") and report.get("username") != "ثبت نشده":
        score += 15
    if report.get("amount") and report.get("amount") != "ثبت نشده":
        score += 15
    if report.get("text") and report.get("text") != "ثبت نشده":
        score += 25

    return min(score, 100)


def risk_label(score: int) -> str:
    if score >= 75:
        return "🔴 بالا"
    if score >= 45:
        return "🟠 متوسط"
    return "🟡 پایین"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_number TEXT,
            card_normalized TEXT,
            full_name TEXT,
            name_normalized TEXT,
            phone TEXT,
            phone_normalized TEXT,
            username TEXT,
            username_normalized TEXT,
            amount TEXT,
            report_text TEXT,
            risk_score INTEGER,
            created_at TEXT
        )
        """
    )

    cursor.execute("PRAGMA table_info(reports)")
    existing_columns = {row[1] for row in cursor.fetchall()}

    required_columns = {
        "card_normalized": "TEXT",
        "name_normalized": "TEXT",
        "phone_normalized": "TEXT",
        "username_normalized": "TEXT",
        "risk_score": "INTEGER",
    }

    for column_name, column_type in required_columns.items():
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE reports ADD COLUMN {column_name} {column_type}")

    conn.commit()
    conn.close()


def main_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 ثبت گزارش", callback_data="menu:report")],
            [InlineKeyboardButton("🔎 جستجو", callback_data="menu:search")],
            [InlineKeyboardButton("ℹ️ راهنما", callback_data="menu:help")],
        ]
    )


def report_keyboard(step_index: int):
    buttons = []

    if step_index > 0:
        buttons.append(
            InlineKeyboardButton("🔙 مرحله قبل", callback_data="report:back")
        )

    buttons.append(
        InlineKeyboardButton("⏭ رد کردن", callback_data="report:skip")
    )

    return InlineKeyboardMarkup(
        [
            buttons,
            [InlineKeyboardButton("❌ لغو", callback_data="report:cancel")],
        ]
    )


def back_to_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:home")],
        ]
    )


def search_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("❌ لغو و ریست", callback_data="search:cancel")],
        ]
    )


def mask_value(key: str, value: str) -> str:
    if not value or value == "ثبت نشده":
        return "هنوز وارد نشده"

    if key == "card":
        digits = fa_to_en_digits(value)
        digits_only = re.sub(r"\D", "", digits)
        if len(digits_only) >= 8:
            return f"{digits_only[:4]}********{digits_only[-4:]}"
        return value

    return value


def build_progress_bar(current_step: int, total_steps: int) -> str:
    filled = current_step
    empty = total_steps - filled
    return f"[{'█' * filled}{'░' * empty}] {current_step}/{total_steps}"


def build_report_form_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    report = context.user_data.get("report", {})
    step_index = context.user_data.get("step_index", 0)

    current_step = REPORT_STEPS[step_index]
    total_steps = len(REPORT_STEPS)

    lines = [
        "📝 ثبت گزارش جدید",
        "",
        f"📍 مرحله {step_index + 1} از {total_steps}",
        build_progress_bar(step_index, total_steps),
        "",
        "🔹 سوال فعلی:",
        current_step["prompt"],
        "",
        "📋 وضعیت فرم:",
    ]

    for idx, step in enumerate(REPORT_STEPS, start=1):
        value = report.get(step["key"])

        if value and value != "ثبت نشده":
            shown_value = mask_value(step["key"], value)
            prefix = "✅"
        else:
            shown_value = "هنوز وارد نشده"
            prefix = "⬜"

        if idx - 1 == step_index:
            lines.append(f"{prefix} {idx}. {step['title']}: {shown_value} ← مرحله فعلی")
        else:
            lines.append(f"{prefix} {idx}. {step['title']}: {shown_value}")

    lines.append("")
    lines.append("✍️ پاسخ همین سؤال را در پیام بعدی ارسال کنید.")

    return "\n".join(lines)


def build_report_summary(report: dict, risk_score: int) -> str:
    return (
        "✅ گزارش با موفقیت ثبت شد.\n\n"
        "📋 خلاصه گزارش:\n"
        f"💳 کارت: {report.get('card', 'ثبت نشده')}\n"
        f"👤 نام: {report.get('name', 'ثبت نشده')}\n"
        f"📞 تماس: {report.get('phone', 'ثبت نشده')}\n"
        f"🆔 آیدی: {report.get('username', 'ثبت نشده')}\n"
        f"💰 مبلغ: {report.get('amount', 'ثبت نشده')}\n"
        f"📝 شرح: {report.get('text', 'ثبت نشده')}\n\n"
        f"⚠️ سطح ریسک: {risk_label(risk_score)} ({risk_score}/100)"
    )


async def safe_delete_user_message(update: Update):
    if not update.message:
        return

    try:
        await update.message.delete()
    except TelegramError:
        pass


async def edit_or_send_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup=None,
):
    chat_id = update.effective_chat.id
    message_id = context.user_data.get("bot_message_id")

    if update.callback_query:
        query = update.callback_query
        try:
            await query.edit_message_text(text=text, reply_markup=reply_markup)
            context.user_data["bot_message_id"] = query.message.message_id
            return
        except BadRequest as error:
            if "Message is not modified" in str(error):
                return

    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return
        except TelegramError:
            pass

    sent_message = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
    )
    context.user_data["bot_message_id"] = sent_message.message_id


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    old_message_id = context.user_data.get("bot_message_id")
    context.user_data.clear()

    if old_message_id:
        context.user_data["bot_message_id"] = old_message_id

    await edit_or_send_message(
        update,
        context,
        "👋 به ربات ثبت گزارش خوش آمدید.\n\nیکی از گزینه‌های زیر را انتخاب کنید:",
        main_menu_keyboard(),
    )
    return MENU


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_delete_user_message(update)
    return await show_main_menu(update, context)


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "menu:home":
        return await show_main_menu(update, context)

    if data == "menu:help":
        await edit_or_send_message(
            update,
            context,
            "ℹ️ راهنما\n\n"
            "از بخش «ثبت گزارش» می‌توانید اطلاعات فرد موردنظر را مرحله‌به‌مرحله تکمیل کنید.\n"
            "در فرم، همه سؤال‌ها از ابتدا نمایش داده می‌شوند و هر پاسخ در همان فرم ثبت می‌شود.\n"
            "از بخش «جستجو» می‌توانید با شماره کارت، شماره تماس، نام یا آیدی تلگرام جستجو کنید.\n\n"
            "⚠️ این ربات فقط برای ثبت گزارش کاربران است و نتیجه آن حکم قطعی یا قضایی نیست.",
            back_to_menu_keyboard(),
        )
        return MENU

    if data == "menu:report":
        context.user_data["report"] = {}
        context.user_data["step_index"] = 0

        await edit_or_send_message(
            update,
            context,
            build_report_form_text(context),
            report_keyboard(0),
        )
        return REPORT_INPUT

    if data == "menu:search":
        await edit_or_send_message(
            update,
            context,
            "🔎 عبارت موردنظر را وارد کنید:\n\n"
            "می‌توانید شماره کارت، شماره تماس، نام یا آیدی تلگرام را بفرستید.",
            search_keyboard(),
        )
        return SEARCH_INPUT

    return MENU


async def report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    step_index = context.user_data.get("step_index", 0)
    report = context.user_data.setdefault("report", {})

    if data == "report:cancel":
        return await show_main_menu(update, context)

    if data == "report:back":
        context.user_data["step_index"] = max(step_index - 1, 0)
        await edit_or_send_message(
            update,
            context,
            build_report_form_text(context),
            report_keyboard(context.user_data["step_index"]),
        )
        return REPORT_INPUT

    if data == "report:skip":
        current_step = REPORT_STEPS[step_index]
        report[current_step["key"]] = current_step["skip"]
        return await go_to_next_report_step(update, context)

    return REPORT_INPUT


async def report_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step_index = context.user_data.get("step_index", 0)

    if step_index >= len(REPORT_STEPS):
        await safe_delete_user_message(update)
        return REPORT_INPUT

    step = REPORT_STEPS[step_index]
    user_text = update.message.text.strip()

    context.user_data.setdefault("report", {})[step["key"]] = user_text

    await safe_delete_user_message(update)
    return await go_to_next_report_step(update, context)


async def go_to_next_report_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step_index = context.user_data.get("step_index", 0)
    next_step_index = step_index + 1

    if next_step_index < len(REPORT_STEPS):
        context.user_data["step_index"] = next_step_index
        await edit_or_send_message(
            update,
            context,
            build_report_form_text(context),
            report_keyboard(next_step_index),
        )
        return REPORT_INPUT

    report = context.user_data.get("report", {})
    risk_score = calculate_risk_score(report)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO reports (
            card_number,
            card_normalized,
            full_name,
            name_normalized,
            phone,
            phone_normalized,
            username,
            username_normalized,
            amount,
            report_text,
            risk_score,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            report.get("card", "ثبت نشده"),
            normalize_identifier(report.get("card", "")),
            report.get("name", "ثبت نشده"),
            normalize_text(report.get("name", "")),
            report.get("phone", "ثبت نشده"),
            normalize_identifier(report.get("phone", "")),
            report.get("username", "ثبت نشده"),
            normalize_identifier(report.get("username", "")),
            report.get("amount", "ثبت نشده"),
            report.get("text", "ثبت نشده"),
            risk_score,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        ),
    )
    conn.commit()
    conn.close()

    bot_message_id = context.user_data.get("bot_message_id")
    context.user_data.clear()
    context.user_data["bot_message_id"] = bot_message_id

    await edit_or_send_message(
        update,
        context,
        build_report_summary(report, risk_score),
        back_to_menu_keyboard(),
    )
    return MENU


async def search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "search:cancel":
        return await show_main_menu(update, context)

    return SEARCH_INPUT


async def search_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_text = update.message.text.strip()
    normalized_query = normalize_identifier(query_text)
    normalized_name = normalize_text(query_text)

    await safe_delete_user_message(update)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            card_number,
            full_name,
            phone,
            username,
            amount,
            report_text,
            risk_score,
            created_at
        FROM reports
        WHERE
            card_normalized LIKE ?
            OR phone_normalized LIKE ?
            OR username_normalized LIKE ?
            OR name_normalized LIKE ?
        ORDER BY id DESC
        LIMIT 5
        """,
        (
            f"%{normalized_query}%",
            f"%{normalized_query}%",
            f"%{normalized_query}%",
            f"%{normalized_name}%",
        ),
    )
    results = cursor.fetchall()
    conn.close()

    if not results:
        await edit_or_send_message(
            update,
            context,
            "❌ نتیجه‌ای پیدا نشد.\n\n"
            f"عبارت جستجو: {query_text}",
            back_to_menu_keyboard(),
        )
        return MENU

    lines = [
        f"🔎 نتیجه جستجو برای: {query_text}",
        f"✅ تعداد نتایج نمایش‌داده‌شده: {len(results)}",
    ]

    for index, result in enumerate(results, start=1):
        card, name, phone, username, amount, report_text, risk_score, created_at = result
        risk_score = risk_score or 0

        lines.append(
            "\n"
            f"📌 نتیجه {index}\n"
            f"💳 کارت: {card or 'ثبت نشده'}\n"
            f"👤 نام: {name or 'ثبت نشده'}\n"
            f"📞 تماس: {phone or 'ثبت نشده'}\n"
            f"🆔 آیدی: {username or 'ثبت نشده'}\n"
            f"💰 مبلغ: {amount or 'ثبت نشده'}\n"
            f"⚠️ ریسک: {risk_label(risk_score)} ({risk_score}/100)\n"
            f"🗓 تاریخ ثبت: {created_at or 'نامشخص'}\n"
            f"📝 شرح: {report_text or 'ثبت نشده'}"
        )

    await edit_or_send_message(
        update,
        context,
        "\n".join(lines),
        back_to_menu_keyboard(),
    )
    return MENU


def main():
    token = os.getenv("BOT_TOKEN")

    if not token:
        raise RuntimeError("BOT_TOKEN is not set")

    init_db()

    app = Application.builder().token(token).build()

    conversation = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MENU: [
                CallbackQueryHandler(menu_callback, pattern="^menu:"),
            ],
            REPORT_INPUT: [
                CallbackQueryHandler(report_callback, pattern="^report:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, report_text_input),
            ],
            SEARCH_INPUT: [
                CallbackQueryHandler(search_callback, pattern="^search:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_text_input),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CallbackQueryHandler(menu_callback, pattern="^menu:"),
        ],
        allow_reentry=True,
    )

    app.add_handler(conversation)
    app.run_polling()


if __name__ == "__main__":
    main()
