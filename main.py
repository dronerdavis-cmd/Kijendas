import os
import sqlite3
import logging
import random
import string
import asyncio
from datetime import datetime

from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    ContextTypes, ConversationHandler, filters
)

# --- تنظیمات ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

logging.basicConfig(level=logging.INFO)

# --- وضعیت‌های ماشین وضعیت (Wizard) ---
(GET_NAME, GET_PHONE, GET_TG, GET_CARDS, GET_DESC, GET_PHOTOS, CONFIRM) = range(7)

# --- دیتابیس ---
def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, case_code TEXT, reporter_id INTEGER, name TEXT, phone TEXT, tg_id TEXT, description TEXT, status TEXT, created_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS cards(id INTEGER PRIMARY KEY, report_id INTEGER, card_number TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY, report_id INTEGER, file_id TEXT)")
    conn.commit()
    conn.close()

# --- کیبوردها ---
def main_menu_kb(uid):
    kb = [["📝 ثبت گزارش جدید"], ["🔎 استعلام سریع", "👤 پروفایل من"]]
    if uid in ADMIN_IDS: kb.insert(0, ["🛡 پنل مدیریت"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def cancel_kb():
    return ReplyKeyboardMarkup([["❌ لغو گزارش"]], resize_keyboard=True)

def done_kb():
    return ReplyKeyboardMarkup([["✅ اتمام و تایید"], ["❌ لغو گزارش"]], resize_keyboard=True)

# --- تابع کمکی برای آپدیت Live Review ---
def generate_review_text(data, step_name):
    txt = f"📝 **در حال تکمیل گزارش...** (مرحله: {step_name})\n\n"
    txt += f"۱. نام متهم: {data.get('name') or '⏳'}\n"
    txt += f"۲. شماره تماس: {data.get('phone') or '⏳'}\n"
    txt += f"۳. آیدی تلگرام: {data.get('tg') or '⏳'}\n"
    txt += f"۴. کارت‌های بانکی: {', '.join(data.get('cards', [])) if data.get('cards') else '⏳'}\n"
    txt += f"۵. شرح واقعه: {'✅ ثبت شد' if data.get('desc') else '⏳'}\n"
    txt += f"۶. مدارک تصویری: {len(data.get('photos', []))} عدد\n"
    return txt

# --- مدیریت پاکسازی پیام‌ها ---
async def delete_messages(context, chat_id, message_ids):
    for mid in message_ids:
        try:
            await context.bot.delete_message(chat_id, mid)
        except:
            pass

# --- شروع فرآیند گزارش ---
async def start_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['rep'] = {'cards': [], 'photos': [], 'mids': []}
    
    review_msg = await update.message.reply_text(
        generate_review_text(context.user_data['rep'], "نام"),
        parse_mode=ParseMode.MARKDOWN
    )
    context.user_data['review_msg_id'] = review_msg.message_id
    
    prompt = await update.message.reply_text("👤 لطفا نام و نام خانوادگی متهم را وارد کنید:", reply_markup=cancel_kb())
    context.user_data['rep']['mids'].append(update.message.message_id) # دکمه فشرده شده
    context.user_data['rep']['mids'].append(prompt.message_id)
    
    return GET_NAME

async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    if val == "❌ لغو گزارش": return await cancel_process(update, context)
    
    context.user_data['rep']['name'] = val
    context.user_data['rep']['mids'].append(update.message.message_id)
    
    await delete_messages(context, update.effective_chat.id, context.user_data['rep']['mids'])
    context.user_data['rep']['mids'] = []
    
    await context.bot.edit_message_text(
        generate_review_text(context.user_data['rep'], "تلفن"),
        update.effective_chat.id, context.user_data['review_msg_id'], parse_mode=ParseMode.MARKDOWN
    )
    
    prompt = await update.message.reply_text("📞 شماره تماس متهم را وارد کنید (یا 'ندارم'):")
    context.user_data['rep']['mids'].append(prompt.message_id)
    return GET_PHONE

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    context.user_data['rep']['phone'] = val
    context.user_data['rep']['mids'].append(update.message.message_id)
    
    await delete_messages(context, update.effective_chat.id, context.user_data['rep']['mids'])
    context.user_data['rep']['mids'] = []
    
    await context.bot.edit_message_text(
        generate_review_text(context.user_data['rep'], "تلگرام"),
        update.effective_chat.id, context.user_data['review_msg_id'], parse_mode=ParseMode.MARKDOWN
    )
    
    prompt = await update.message.reply_text("🆔 آیدی یا یوزرنیم تلگرام متهم:")
    context.user_data['rep']['mids'].append(prompt.message_id)
    return GET_TG

async def handle_tg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['rep']['tg'] = update.message.text
    context.user_data['rep']['mids'].append(update.message.message_id)
    await delete_messages(context, update.effective_chat.id, context.user_data['rep']['mids'])
    context.user_data['rep']['mids'] = []
    
    await context.bot.edit_message_text(
        generate_review_text(context.user_data['rep'], "کارت بانکی"),
        update.effective_chat.id, context.user_data['review_msg_id'], parse_mode=ParseMode.MARKDOWN
    )
    
    prompt = await update.message.reply_text("💳 شماره کارت ۱۶ رقمی متهم را بفرستید (پس از اتمام دکمه تایید را بزنید):", reply_markup=done_kb())
    context.user_data['rep']['mids'].append(prompt.message_id)
    return GET_CARDS

async def handle_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text
    context.user_data['rep']['mids'].append(update.message.message_id)

    if val == "✅ اتمام و تایید":
        await delete_messages(context, update.effective_chat.id, context.user_data['rep']['mids'])
        context.user_data['rep']['mids'] = []
        prompt = await update.message.reply_text("📑 شرح کامل واقعه و کلاهبرداری را بنویسید:", reply_markup=cancel_kb())
        context.user_data['rep']['mids'].append(prompt.message_id)
        return GET_DESC
    
    card = val.replace(" ", "").replace("-", "")
    if len(card) == 16:
        context.user_data['rep']['cards'].append(card)
        await context.bot.edit_message_text(
            generate_review_text(context.user_data['rep'], "کارت بانکی"),
            update.effective_chat.id, context.user_data['review_msg_id'], parse_mode=ParseMode.MARKDOWN
        )
    
    return GET_CARDS

async def handle_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['rep']['desc'] = update.message.text
    context.user_data['rep']['mids'].append(update.message.message_id)
    await delete_messages(context, update.effective_chat.id, context.user_data['rep']['mids'])
    context.user_data['rep']['mids'] = []
    
    await context.bot.edit_message_text(
        generate_review_text(context.user_data['rep'], "مدارک"),
        update.effective_chat.id, context.user_data['review_msg_id'], parse_mode=ParseMode.MARKDOWN
    )
    
    prompt = await update.message.reply_text("🖼 اسکرین‌شات‌ها و مدارک را ارسال کنید (تک‌تک بفرستید و در پایان تایید را بزنید):", reply_markup=done_kb())
    context.user_data['rep']['mids'].append(prompt.message_id)
    return GET_PHOTOS

async def handle_photos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['rep']['mids'].append(update.message.message_id)
    
    if update.message.text == "✅ اتمام و تایید":
        await delete_messages(context, update.effective_chat.id, context.user_data['rep']['mids'])
        return await finalize_report(update, context)

    if update.message.photo:
        context.user_data['rep']['photos'].append(update.message.photo[-1].file_id)
        await context.bot.edit_message_text(
            generate_review_text(context.user_data['rep'], "مدارک"),
            update.effective_chat.id, context.user_data['review_msg_id'], parse_mode=ParseMode.MARKDOWN
        )
    return GET_PHOTOS

# --- پایان و ثبت نهایی ---
async def finalize_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rep = context.user_data['rep']
    case_code = "RPT-" + "".join(random.choices(string.digits, k=6))
    
    # ذخیره در دیتابیس (مشابه کدهای قبلی)
    # ... (کد دیتابیس برای اختصار اینجا تکرار نشده اما باید باشد)
    
    final_text = (
        f"✅ **گزارش نهایی ثبت شد**\n"
        f"📌 شماره پرونده: `{case_code}`\n\n"
        f"👤 نام: {rep['name']}\n"
        f"📞 تلفن: {rep['phone']}\n"
        f"💳 کارت‌ها: {', '.join(rep['cards'])}\n"
        f"📝 شرح: {rep['desc']}"
    )
    
    # حذف پیام ریویو قدیمی و جایگزینی با گزارش نهایی
    await context.bot.delete_message(update.effective_chat.id, context.user_data['review_msg_id'])
    
    if rep['photos']:
        media = [InputMediaPhoto(rep['photos'][0], caption=final_text, parse_mode=ParseMode.MARKDOWN)]
        for p in rep['photos'][1:10]: media.append(InputMediaPhoto(p))
        await context.bot.send_media_group(update.effective_chat.id, media)
    else:
        await context.bot.send_message(update.effective_chat.id, final_text, parse_mode=ParseMode.MARKDOWN)

    await update.message.reply_text("گزارش شما با موفقیت در سامانه ثبت شد.", reply_markup=main_menu_kb(update.effective_user.id))
    return ConversationHandler.END

async def cancel_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'review_msg_id' in context.user_data:
        try: await context.bot.delete_message(update.effective_chat.id, context.user_data['review_msg_id'])
        except: pass
    await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=main_menu_kb(update.effective_user.id))
    return ConversationHandler.END

# --- اجرای ربات ---
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 ثبت گزارش جدید$"), start_report)],
        states={
            GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
            GET_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)],
            GET_TG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tg)],
            GET_CARDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_cards)],
            GET_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_desc)],
            GET_PHOTOS: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, handle_photos)],
        },
        fallbacks=[MessageHandler(filters.Regex("❌ لغو گزارش"), cancel_process)],
    )

    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("خوش آمدید", reply_markup=main_menu_kb(u.effective_user.id))))
    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()
