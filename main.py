import os
import logging
import sqlite3
import random
import string
from datetime import datetime
from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(i.strip()) for i in os.getenv("ADMIN_IDS", "").split(",") if i.strip().isdigit()]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- DB SETUP ---
def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS reports 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, case_code TEXT, reporter_id INTEGER, 
                  name TEXT, phone TEXT, tg_id TEXT, description TEXT, status TEXT, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS cards 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, report_id INTEGER, card_number TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS evidence 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, report_id INTEGER, file_id TEXT)''')
    conn.commit()
    conn.close()

# --- HELPERS ---
def generate_case_code():
    return "RPT-" + ''.join(random.choices(string.digits, k=5))

def get_main_keyboard(uid):
    kb = [["📝 ثبت گزارش"], ["🔎 استعلام سریع"], ["👤 پروفایل من"]]
    if uid in ADMIN_IDS:
        kb.insert(0, ["🛡 پنل مدیریت ادمین"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def get_report_dashboard_kb(data):
    def check(val): return "✅" if val else "⬜"
    def check_list(lst): return "✅" if lst else "⬜"
    
    keyboard = [
        [InlineKeyboardButton(f"{check(data['name'])} نام فرد", callback_data="set_name"),
         InlineKeyboardButton(f"{check_list(data['cards'])} شماره کارت‌ها", callback_data="set_cards")],
        [InlineKeyboardButton(f"{check(data['phone'])} شماره تماس", callback_data="set_phone"),
         InlineKeyboardButton(f"{check(data['tg_id'])} آیدی تلگرام", callback_data="set_tg")],
        [InlineKeyboardButton(f"{check(data['desc'])} شرح گزارش (اجباری)", callback_data="set_desc")],
        [InlineKeyboardButton(f"{check_list(data['evidence'])} آپلود مدارک ({len(data['evidence'])}/10)", callback_data="set_evidence")],
        [InlineKeyboardButton("🚀 ثبت نهایی گزارش", callback_data="finalize_report")],
        [InlineKeyboardButton("❌ لغو و بازگشت", callback_data="cancel_report")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- CORE HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
    uid = update.effective_user.id
    await update.message.reply_text("خوش آمدید. برای شروع یکی از گزینه‌ها را انتخاب کنید:", reply_markup=get_main_keyboard(uid))

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if text == "📝 ثبت گزارش":
        context.user_data['rep'] = {'cards': [], 'name': None, 'phone': None, 'tg_id': None, 'desc': None, 'evidence': [], 'step': None}
        msg = await update.message.reply_text("📋 **داشبورد ثبت گزارش**\nلطفاً فیلدها را انتخاب و پر کنید:", 
                                            reply_markup=get_report_dashboard_kb(context.user_data['rep']), parse_mode=ParseMode.MARKDOWN)
        context.user_data['dashboard_id'] = msg.message_id

    elif text == "👤 پروفایل من":
        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        c.execute("SELECT case_code, status, created_at FROM reports WHERE reporter_id = ?", (uid,))
        reps = c.fetchall()
        conn.close()
        if not reps:
            await update.message.reply_text("شما هنوز گزارشی ثبت نکرده‌اید.")
        else:
            txt = "👤 **تاریخچه گزارش‌های شما:**\n\n"
            for r in reps:
                txt += f"📄 کد: `{r[0]}` | وضعیت: {r[1]} | تاریخ: {r[2]}\n"
            await update.message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)

    elif text == "🛡 پنل مدیریت ادمین" and uid in ADMIN_IDS:
        await show_admin_dashboard(update, context)

# --- REPORTING LOGIC (EDITING MESSAGE) ---
async def report_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = update.effective_user.id
    
    if data.startswith("set_"):
        context.user_data['rep']['step'] = data
        field_names = {"set_name": "نام", "set_cards": "شماره کارت (۱۶ رقمی)", "set_phone": "شماره تماس", "set_tg": "آیدی تلگرام", "set_desc": "شرح کامل", "set_evidence": "عکس مدارک"}
        await query.message.reply_text(f"👇 لطفاً {field_names[data]} را ارسال کنید:")
        await query.answer()
        
    elif data == "finalize_report":
        rep = context.user_data['rep']
        if not rep['desc'] or not (rep['cards'] or rep['tg_id'] or rep['name']):
            await query.answer("⚠️ حداقل یک شناسه (کارت/آیدی/نام) + شرح گزارش الزامی است!", show_alert=True)
            return
        
        # ثبت در دیتابیس
        case_code = generate_case_code()
        conn = sqlite3.connect("database.db")
        c = conn.cursor()
        c.execute("INSERT INTO reports (case_code, reporter_id, name, phone, tg_id, description, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                  (case_code, uid, rep['name'], rep['phone'], rep['tg_id'], rep['desc'], 'pending', datetime.now().strftime("%Y-%m-%d")))
        rid = c.lastrowid
        for card in rep['cards']: c.execute("INSERT INTO cards (report_id, card_number) VALUES (?,?)", (rid, card))
        for img in rep['evidence']: c.execute("INSERT INTO evidence (report_id, file_id) VALUES (?,?)", (rid, img))
        conn.commit()
        conn.close()

        await query.message.edit_text(f"✅ گزارش با موفقیت ثبت شد.\n📌 شماره پرونده: `{case_code}`", parse_mode=ParseMode.MARKDOWN)
        # اطلاع رسانی به ادمین
        for aid in ADMIN_IDS:
            await context.bot.send_message(aid, f"📥 گزارش جدید: `{case_code}`\nبرای بررسی دکمه پنل مدیریت را بزنید.")
        
    elif data == "cancel_report":
        await query.message.delete()
        await context.bot.send_message(uid, "❌ عملیات لغو شد.", reply_markup=get_main_keyboard(uid))

async def handle_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'rep' not in context.user_data or not context.user_data['rep']['step']: return

    step = context.user_data['rep']['step']
    val = update.message.text
    
    if step == "set_name": context.user_data['rep']['name'] = val
    elif step == "set_phone": context.user_data['rep']['phone'] = val
    elif step == "set_tg": context.user_data['rep']['tg_id'] = val
    elif step == "set_desc": context.user_data['rep']['desc'] = val
    elif step == "set_cards":
        card = val.replace(" ", "")
        if len(card) == 16: context.user_data['rep']['cards'].append(card)
    
    if update.message.photo and step == "set_evidence":
        if len(context.user_data['rep']['evidence']) < 10:
            context.user_data['rep']['evidence'].append(update.message.photo[-1].file_id)

    # حذف پیام کاربر برای تمیز ماندن چت
    try: await update.message.delete() 
    except: pass

    # آپدیت داشبورد اصلی
    await context.bot.edit_message_reply_markup(
        chat_id=update.effective_chat.id,
        message_id=context.user_data['dashboard_id'],
        reply_markup=get_report_dashboard_kb(context.user_data['rep'])
    )

# --- ADMIN LOGIC ---
async def show_admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("SELECT id, case_code, reporter_id FROM reports WHERE status = 'pending'")
    pending = c.fetchall()
    conn.close()
    
    if not pending:
        await update.message.reply_text("✅ گزارش بررسی نشده‌ای وجود ندارد.")
        return

    for r in pending:
        btn = [[InlineKeyboardButton("👁 مشاهده کامل و مدارک", callback_data=f"view_{r[0]}"),
                InlineKeyboardButton("✅ تایید", callback_data=f"adm_app_{r[0]}"),
                InlineKeyboardButton("❌ رد", callback_data=f"adm_rej_{r[0]}")]]
        await update.message.reply_text(f"📄 پرونده: `{r[1]}`\nگزارش دهنده: `{r[2]}`", 
                                       reply_markup=InlineKeyboardMarkup(btn), parse_mode=ParseMode.MARKDOWN)

async def admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    if data.startswith("view_"):
        rid = data.split("_")[1]
        c.execute("SELECT * FROM reports WHERE id = ?", (rid,))
        r = c.fetchone()
        c.execute("SELECT card_number FROM cards WHERE report_id = ?", (rid,))
        cards = [x[0] for x in c.fetchall()]
        c.execute("SELECT file_id FROM evidence WHERE report_id = ?", (rid,))
        imgs = [x[0] for x in c.fetchall()]
        
        info = f"📝 **جزئیات پرونده:** {r[1]}\n👤 نام: {r[3]}\n📞 تماس: {r[4]}\n🆔 تلگرام: {r[5]}\n💳 کارت‌ها: {', '.join(cards)}\n\nشرح: {r[6]}"
        await query.message.reply_text(info)
        for img in imgs: await query.message.reply_photo(img)
        
    elif data.startswith("adm_"):
        _, action, rid = data.split("_")
        status = "approved" if action == "app" else "rejected"
        c.execute("UPDATE reports SET status = ? WHERE id = ?", (status, rid))
        conn.commit()
        await query.edit_message_text(f"تغییر وضعیت به {status} انجام شد.")

    conn.close()
    await query.answer()

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^(📝 ثبت گزارش|🔎 استعلام سریع|👤 پروفایل من|🛡 پنل مدیریت ادمین)$"), handle_menu))
    app.add_handler(CallbackQueryHandler(report_callbacks, pattern="^(set_|finalize_|cancel_)"))
    app.add_handler(CallbackQueryHandler(admin_actions, pattern="^(view_|adm_)"))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_inputs))
    
    app.run_polling()

if __name__ == "__main__":
    main()
