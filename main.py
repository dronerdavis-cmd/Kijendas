import os
import re
import sqlite3
import logging
from datetime import datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InputMediaPhoto,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

DB_NAME = "database.db"

(
    MENU,
    REPORT_CARD,
    REPORT_NAME,
    REPORT_PHONE,
    REPORT_USERNAME,
    REPORT_AMOUNT,
    REPORT_TEXT,
    REPORT_PROFILE_PHOTO,
    REPORT_SCREENSHOT,
    REPORT_CONFIRM,
    SEARCH_INPUT,
) = range(11)


def fa_to_en_digits(text: str) -> str:
    if not text:
        return text

    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    english_digits = "0123456789"

    for i in range(10):
        text = text.replace(persian_digits[i], english_digits[i])
        text = text.replace(arabic_digits[i], english_digits[i])

    return text


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = fa_to_en_digits(text)
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_identifier(text: str) -> str:
    text = normalize_text(text)
    text = text.replace("-", "").replace("_", "").replace(" ", "")
    return text


def normalize_phone(text: str) -> str:
    text = normalize_identifier(text)
    return text


def normalize_card(text: str) -> str:
    text = normalize_identifier(text)
    return text


def normalize_username(text: str) -> str:
    text = normalize_text(text)
    if text.startswith("@"):
        text = text[1:]
    return text.lower()


def parse_amount(text: str) -> int | None:
    if not text:
        return None
    text = fa_to_en_digits(text)
    text = text.replace(",", "").replace("،", "").replace(" ", "")
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def format_amount(amount: int | None) -> str:
    if amount is None:
        return "نامشخص"
    return f"{amount:,} تومان"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_number TEXT,
            full_name TEXT,
            phone TEXT,
            username TEXT,
            amount INTEGER,
            report_text TEXT,
            profile_photo_file_id TEXT,
            screenshot_file_id TEXT,
            reporter_user_id TEXT,
            reporter_username TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def get_main_keyboard():
    keyboard = [
        ["📝 ثبت گزارش", "🔎 جستجو"],
        ["ℹ️ راهنما", "❌ لغو"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_skip_keyboard():
    keyboard = [
        ["⏭ رد کردن", "❌ لغو"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def calculate_risk(report_count: int, total_amount: int, has_images: bool) -> tuple[str, str]:
    score = 0

    if report_count >= 4:
        score += 3
    elif report_count >= 2:
        score += 2
    elif report_count >= 1:
        score += 1

    if total_amount >= 50000000:
        score += 3
    elif total_amount >= 10000000:
        score += 2
    elif total_amount > 0:
        score += 1

    if has_images:
        score += 1

    if score >= 6:
        return "🔴 بالا", "ریسک بالا"
    elif score >= 3:
        return "🟠 متوسط", "ریسک متوسط"
    else:
        return "🟡 پایین", "ریسک پایین"


def build_report_preview(data: dict) -> str:
    return (
        "📋 پیش‌نمایش گزارش:\n\n"
        f"💳 شماره کارت: {data.get('card_number') or 'وارد نشده'}\n"
        f"👤 نام: {data.get('full_name') or 'وارد نشده'}\n"
        f"📞 تلفن: {data.get('phone') or 'وارد نشده'}\n"
        f"🆔 آیدی: @{data.get('username')}" if data.get('username') else "🆔 آیدی: وارد نشده"
    ) + (
        f"\n💰 مبلغ: {format_amount(data.get('amount'))}\n"
        f"📝 متن گزارش: {data.get('report_text') or 'وارد نشده'}\n"
        f"🖼 تصویر پروفایل: {'دارد' if data.get('profile_photo_file_id') else 'ندارد'}\n"
        f"📷 اسکرین‌شات: {'دارد' if data.get('screenshot_file_id') else 'ندارد'}\n"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 سلام، خوش آمدید.\n\n"
        "این ربات برای ثبت و جستجوی گزارش‌های مرتبط طراحی شده است.\n"
        "از منوی زیر استفاده کنید:"
    )
    await update.message.reply_text(text, reply_markup=get_main_keyboard())
    return MENU


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "ℹ️ راهنما\n\n"
        "📝 ثبت گزارش: ثبت اطلاعات مورد نظر به صورت مرحله‌ای\n"
        "🔎 جستجو: جستجو با شماره کارت، تلفن، نام یا آیدی\n\n"
        "نکته:\n"
        "- اعداد فارسی هم پشتیبانی می‌شوند.\n"
        "- برای رد کردن هر مرحله از دکمه «⏭ رد کردن» استفاده کنید.\n"
        "- برای لغو عملیات، «❌ لغو» را بزنید."
    )
    await update.message.reply_text(text, reply_markup=get_main_keyboard())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("report_data", None)
    await update.message.reply_text(
        "❌ عملیات لغو شد.",
        reply_markup=get_main_keyboard()
    )
    return MENU


async def report_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["report_data"] = {}
    await update.message.reply_text(
        "📝 ثبت گزارش شروع شد.\n\n"
        "💳 شماره کارت را وارد کنید.\n"
        "اگر ندارید، «⏭ رد کردن» را بزنید.",
        reply_markup=get_skip_keyboard()
    )
    return REPORT_CARD


async def report_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text != "⏭ رد کردن":
        card = normalize_card(text)
        context.user_data["report_data"]["card_number"] = card

    await update.message.reply_text(
        "👤 نام فرد را وارد کنید.\n"
        "اگر ندارید، «⏭ رد کردن» را بزنید.",
        reply_markup=get_skip_keyboard()
    )
    return REPORT_NAME


async def report_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text != "⏭ رد کردن":
        context.user_data["report_data"]["full_name"] = normalize_text(text)

    await update.message.reply_text(
        "📞 شماره تلفن را وارد کنید.\n"
        "اگر ندارید، «⏭ رد کردن» را بزنید.",
        reply_markup=get_skip_keyboard()
    )
    return REPORT_PHONE


async def report_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text != "⏭ رد کردن":
        context.user_data["report_data"]["phone"] = normalize_phone(text)

    await update.message.reply_text(
        "🆔 آیدی یا یوزرنیم را وارد کنید.\n"
        "مثال: @example\n"
        "اگر ندارید، «⏭ رد کردن» را بزنید.",
        reply_markup=get_skip_keyboard()
    )
    return REPORT_USERNAME


async def report_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text != "⏭ رد کردن":
        context.user_data["report_data"]["username"] = normalize_username(text)

    await update.message.reply_text(
        "💰 مبلغ کلاهبرداری را وارد کنید.\n"
        "مثال: 2500000\n"
        "اگر ندارید، «⏭ رد کردن» را بزنید.",
        reply_markup=get_skip_keyboard()
    )
    return REPORT_AMOUNT


async def report_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text != "⏭ رد کردن":
        amount = parse_amount(text)
        if amount is None:
            await update.message.reply_text(
                "⚠️ مبلغ معتبر نیست. دوباره وارد کنید یا «⏭ رد کردن» را بزنید.",
                reply_markup=get_skip_keyboard()
            )
            return REPORT_AMOUNT
        context.user_data["report_data"]["amount"] = amount

    await update.message.reply_text(
        "📝 متن گزارش را وارد کنید.\n"
        "اگر ندارید، «⏭ رد کردن» را بزنید.",
        reply_markup=get_skip_keyboard()
    )
    return REPORT_TEXT


async def report_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text != "⏭ رد کردن":
        context.user_data["report_data"]["report_text"] = normalize_text(text)

    await update.message.reply_text(
        "🖼 اگر تصویر پروفایل دارید، ارسال کنید.\n"
        "اگر ندارید، «⏭ رد کردن» را بزنید.",
        reply_markup=get_skip_keyboard()
    )
    return REPORT_PROFILE_PHOTO


async def report_profile_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data["report_data"]["profile_photo_file_id"] = file_id
    elif update.message.text and update.message.text.strip() != "⏭ رد کردن":
        await update.message.reply_text(
            "⚠️ لطفاً عکس ارسال کنید یا «⏭ رد کردن» را بزنید.",
            reply_markup=get_skip_keyboard()
        )
        return REPORT_PROFILE_PHOTO

    await update.message.reply_text(
        "📷 اگر اسکرین‌شات دارید، ارسال کنید.\n"
        "اگر ندارید، «⏭ رد کردن» را بزنید.",
        reply_markup=get_skip_keyboard()
    )
    return REPORT_SCREENSHOT


async def report_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data["report_data"]["screenshot_file_id"] = file_id
    elif update.message.text and update.message.text.strip() != "⏭ رد کردن":
        await update.message.reply_text(
            "⚠️ لطفاً عکس ارسال کنید یا «⏭ رد کردن» را بزنید.",
            reply_markup=get_skip_keyboard()
        )
        return REPORT_SCREENSHOT

    data = context.user_data.get("report_data", {})
    preview = (
        "📋 پیش‌نمایش گزارش:\n\n"
        f"💳 شماره کارت: {data.get('card_number') or 'وارد نشده'}\n"
        f"👤 نام: {data.get('full_name') or 'وارد نشده'}\n"
        f"📞 تلفن: {data.get('phone') or 'وارد نشده'}\n"
        f"🆔 آیدی: {'@' + data.get('username') if data.get('username') else 'وارد نشده'}\n"
        f"💰 مبلغ: {format_amount(data.get('amount'))}\n"
        f"📝 متن گزارش: {data.get('report_text') or 'وارد نشده'}\n"
        f"🖼 تصویر پروفایل: {'دارد' if data.get('profile_photo_file_id') else 'ندارد'}\n"
        f"📷 اسکرین‌شات: {'دارد' if data.get('screenshot_file_id') else 'ندارد'}\n\n"
        "اگر تأیید می‌کنید، کلمه «ثبت» را بفرستید.\n"
        "اگر نمی‌خواهید، «❌ لغو» را بزنید."
    )

    await update.message.reply_text(preview, reply_markup=ReplyKeyboardMarkup([["ثبت", "❌ لغو"]], resize_keyboard=True))
    return REPORT_CONFIRM


async def report_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text != "ثبت":
        await update.message.reply_text(
            "ثبت گزارش لغو شد.",
            reply_markup=get_main_keyboard()
        )
        context.user_data.pop("report_data", None)
        return MENU

    data = context.user_data.get("report_data", {})
    user = update.effective_user

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reports (
            card_number, full_name, phone, username, amount, report_text,
            profile_photo_file_id, screenshot_file_id,
            reporter_user_id, reporter_username, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("card_number"),
        data.get("full_name"),
        data.get("phone"),
        data.get("username"),
        data.get("amount"),
        data.get("report_text"),
        data.get("profile_photo_file_id"),
        data.get("screenshot_file_id"),
        str(user.id) if user else "",
        user.username if user and user.username else "",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ))
    conn.commit()
    conn.close()

    context.user_data.pop("report_data", None)

    await update.message.reply_text(
        "✅ گزارش با موفقیت ثبت شد.",
        reply_markup=get_main_keyboard()
    )
    return MENU


async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔎 مقدار مورد نظر برای جستجو را وارد کنید.\n\n"
        "می‌توانید یکی از این‌ها را وارد کنید:\n"
        "- شماره کارت\n"
        "- نام\n"
        "- تلفن\n"
        "- آیدی\n"
        "- حتی اعداد فارسی\n",
        reply_markup=ReplyKeyboardMarkup([["❌ لغو"]], resize_keyboard=True)
    )
    return SEARCH_INPUT


async def search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_query = update.message.text.strip()

    if raw_query == "❌ لغو":
        return await cancel(update, context)

    normalized_general = normalize_text(raw_query)
    normalized_card = normalize_card(raw_query)
    normalized_phone = normalize_phone(raw_query)
    normalized_username = normalize_username(raw_query)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id, card_number, full_name, phone, username, amount, report_text,
            profile_photo_file_id, screenshot_file_id, created_at
        FROM reports
        WHERE
            card_number = ?
            OR phone = ?
            OR lower(full_name) LIKE lower(?)
            OR lower(username) = lower(?)
            OR lower(username) LIKE lower(?)
            OR lower(report_text) LIKE lower(?)
        ORDER BY id DESC
    """, (
        normalized_card,
        normalized_phone,
        f"%{normalized_general}%",
        normalized_username,
        f"%{normalized_username}%",
        f"%{normalized_general}%"
    ))

    results = cursor.fetchall()
    conn.close()

    if not results:
        await update.message.reply_text(
            "❌ هیچ گزارشی پیدا نشد.",
            reply_markup=get_main_keyboard()
        )
        return MENU

    report_count = len(results)
    total_amount = sum([row[5] for row in results if row[5] is not None])
    has_images = any(row[7] or row[8] for row in results)

    risk_emoji, risk_text = calculate_risk(report_count, total_amount, has_images)

    header = (
        "📊 نتیجه جستجو\n\n"
        f"📁 تعداد گزارش‌های مرتبط: {report_count}\n"
        f"💰 مجموع مبالغ ثبت‌شده: {format_amount(total_amount)}\n"
        f"⚠️ سطح ریسک: {risk_emoji} {risk_text}\n\n"
    )

    await update.message.reply_text(header, reply_markup=get_main_keyboard())

    for idx, row in enumerate(results[:10], start=1):
        (
            report_id, card_number, full_name, phone, username, amount,
            report_text, profile_photo_file_id, screenshot_file_id, created_at
        ) = row

        msg = (
            f"🔹 گزارش #{idx}\n"
            f"💳 شماره کارت: {card_number or 'ندارد'}\n"
            f"👤 نام: {full_name or 'ندارد'}\n"
            f"📞 تلفن: {phone or 'ندارد'}\n"
            f"🆔 آیدی: {'@' + username if username else 'ندارد'}\n"
            f"💰 مبلغ: {format_amount(amount)}\n"
            f"📝 متن گزارش: {report_text or 'ندارد'}\n"
            f"🕒 تاریخ: {created_at}\n"
        )

        await update.message.reply_text(msg)

        media = []
        if profile_photo_file_id:
            media.append(("🖼 تصویر پروفایل", profile_photo_file_id))
        if screenshot_file_id:
            media.append(("📷 اسکرین‌شات", screenshot_file_id))

        for caption, file_id in media:
            try:
                await update.message.reply_photo(photo=file_id, caption=caption)
            except Exception as e:
                logging.error(f"Error sending photo: {e}")

    if len(results) > 10:
        await update.message.reply_text("نمایش فقط ۱۰ نتیجه اول انجام شد.")

    return MENU


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "📝 ثبت گزارش":
        return await report_start(update, context)
    elif text == "🔎 جستجو":
        return await search_start(update, context)
    elif text == "ℹ️ راهنما":
        await help_command(update, context)
        return MENU
    elif text == "❌ لغو":
        return await cancel(update, context)
    else:
        await update.message.reply_text(
            "لطفاً از دکمه‌های منو استفاده کنید.",
            reply_markup=get_main_keyboard()
        )
        return MENU


def main():
    token = os.getenv("BOT_TOKEN")

    if not token:
        print("خطا: BOT_TOKEN تنظیم نشده است!")
        return

    init_db()

    app = Application.builder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("help", help_command),
            MessageHandler(filters.Regex("^📝 ثبت گزارش$"), report_start),
            MessageHandler(filters.Regex("^🔎 جستجو$"), search_start),
        ],
        states={
            REPORT_CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_card)],
            REPORT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_name)],
            REPORT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_phone)],
            REPORT_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_username)],
            REPORT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_amount)],
            REPORT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_text_handler)],
            REPORT_PROFILE_PHOTO: [
                MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, report_profile_photo)
            ],
            REPORT_SCREENSHOT: [
                MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, report_screenshot)
            ],
            REPORT_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_confirm)],
            SEARCH_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_input)],
            MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, text_router)],
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ لغو$"), cancel)],
        per_chat=True,
        per_user=True,
        per_message=False,
    )

    app.add_handler(conv_handler)

    print("ربات روشن شد و آماده کار است...")
    app.run_polling()


if __name__ == "__main__":
    main()
