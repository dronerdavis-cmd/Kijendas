import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "database.db")

ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "123456789").split(",")
    if x.strip().isdigit()
]

MENU, REPORT_INPUT, MEDIA_INPUT, SEARCH_INPUT = range(4)

REPORT_STEPS = [
    {"key": "card_number", "title": "💳 شماره کارت", "question": "💳 شماره کارت فرد موردنظر را وارد کنید", "required": False},
    {"key": "full_name", "title": "👤 نام و نام خانوادگی", "question": "👤 نام و نام خانوادگی فرد موردنظر را وارد کنید", "required": True},
    {"key": "phone", "title": "📞 شماره تماس", "question": "📞 شماره تماس فرد موردنظر را وارد کنید", "required": False},
    {"key": "username", "title": "🆔 آیدی تلگرام", "question": "🆔 آیدی تلگرام فرد موردنظر را وارد کنید، مثل @username", "required": False},
    {"key": "amount", "title": "💰 مبلغ", "question": "💰 مبلغ یا حدود مبلغ را وارد کنید", "required": False},
    {"key": "report_text", "title": "📝 شرح گزارش", "question": "📝 شرح کامل گزارش را وارد کنید", "required": True},
    {"key": "media", "title": "📎 مدارک", "question": "📎 عکس، اسکرین‌شات، فایل یا PDF مدارک را ارسال کنید", "required": False},
]

REPORT_STATUS_LABELS = {
    "pending": "📥 در انتظار بررسی",
    "approved": "✅ تاییدشده",
    "rejected": "❌ ردشده",
    "disputed": "⚠️ دارای اعتراض",
    "removed": "🗑 حذف‌شده",
    "need_more": "📎 نیازمند مدرک بیشتر",
}

def now_text(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def clean_text(v): return str(v).strip() if v else ""
def display_value(v): return clean_text(v) if clean_text(v) else "ثبت نشده"
def is_admin(u_id): return bool(u_id and u_id in ADMIN_IDS)
def get_conn():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def db_execute(q, p=()):
    with get_conn() as conn:
        conn.execute(q, p)
        conn.commit()

def db_fetchone(q, p=()):
    with get_conn() as conn: return conn.execute(q, p).fetchone()

def db_fetchall(q, p=()):
    with get_conn() as conn: return conn.execute(q, p).fetchall()

def init_db():
    db_execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT, is_blocked INTEGER DEFAULT 0, reports_count INTEGER DEFAULT 0, rejected_reports_count INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT)")
    db_execute("CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER, reporter_username TEXT, card_number TEXT, full_name TEXT, phone TEXT, username TEXT, amount TEXT, report_text TEXT, status TEXT DEFAULT 'pending', admin_note TEXT, risk_score INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT)")
    db_execute("CREATE TABLE IF NOT EXISTS report_media (id INTEGER PRIMARY KEY AUTOINCREMENT, report_id INTEGER, file_id TEXT, file_type TEXT, file_name TEXT, created_at TEXT)")
    
    # Update columns for older db
    cols = [row["name"] for row in db_fetchall("PRAGMA table_info(reports)")]
    if "status" not in cols: db_execute("ALTER TABLE reports ADD COLUMN status TEXT DEFAULT 'pending'")
    if "reporter_id" not in cols: db_execute("ALTER TABLE reports ADD COLUMN reporter_id INTEGER")

def save_user(update):
    user = update.effective_user
    if not user: return
    existing = db_fetchone("SELECT user_id FROM users WHERE user_id = ?", (user.id,))
    if existing:
        db_execute("UPDATE users SET username=?, first_name=?, last_name=?, updated_at=? WHERE user_id=?", (user.username or "", user.first_name or "", user.last_name or "", now_text(), user.id))
    else:
        db_execute("INSERT INTO users (user_id, username, first_name, last_name, is_blocked, created_at, updated_at) VALUES (?, ?, ?, ?, 0, ?, ?)", (user.id, user.username or "", user.first_name or "", user.last_name or "", now_text(), now_text()))

def calculate_risk_score(report, media_count):
    score = 0
    if clean_text(report.get("card_number")): score += 20
    if clean_text(report.get("full_name")): score += 20
    if clean_text(report.get("report_text")): score += 20
    if media_count > 0: score += 20
    return min(score + 20, 100)

def main_menu_keyboard(u_id=None):
    btns = [[InlineKeyboardButton("📝 ثبت گزارش", callback_data="menu:report")], [InlineKeyboardButton("🔎 جستجو", callback_data="menu:search")], [InlineKeyboardButton("ℹ️ راهنما", callback_data="menu:help")]]
    if is_admin(u_id): btns.append([InlineKeyboardButton("👮 پنل ادمین", callback_data="admin:home")])
    return InlineKeyboardMarkup(btns)

def report_keyboard(step_idx, media_count=0):
    step = REPORT_STEPS[step_idx]
    rows = [[InlineKeyboardButton(f"❓ {step['question']}", callback_data="noop")]]
    if step["key"] == "media":
        rows.append([InlineKeyboardButton(f"✅ پایان ارسال مدارک ({media_count})", callback_data="report:finish_media")])
    nav = []
    if step_idx > 0: nav.append(InlineKeyboardButton("🔙 قبلی", callback_data="report:back"))
    if not step["required"]: nav.append(InlineKeyboardButton("⏭ رد کردن", callback_data="report:skip"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("❌ لغو", callback_data="report:cancel")])
    return InlineKeyboardMarkup(rows)

async def show_main_menu(update, context):
    save_user(update)
    u = update.effective_user
    if u and db_fetchone("SELECT user_id FROM users WHERE user_id=? AND is_blocked=1", (u.id,)):
        await update.effective_chat.send_message("🚫 دسترسی شما مسدود شده است.")
        return ConversationHandler.END
    txt = "سلام 👋\nبه سامانه ثبت گزارش تخلف خوش آمدید.\nیکی از گزینه‌های زیر را انتخاب کنید:"
    if update.callback_query: await update.callback_query.edit_message_text(txt, reply_markup=main_menu_keyboard(u.id if u else None))
    else: await update.effective_chat.send_message(txt, reply_markup=main_menu_keyboard(u.id if u else None))
    return MENU

async def start(u, c): return await show_main_menu(u, c)

async def handle_report_input(update, context):
    step_idx = context.user_data.get("report_step", 0)
    step = REPORT_STEPS[step_idx]
    val = update.message.text
    if step["key"] == "media":
        await update.message.delete()
        return MEDIA_INPUT
    context.user_data.setdefault("report", {})[step["key"]] = val
    await update.message.delete()
    return await next_step(update, context)

async def handle_media(update, context):
    m = context.user_data.setdefault("report_media", [])
    f_id = ""
    if update.message.photo: f_id = update.message.photo[-1].file_id
    elif update.message.document: f_id = update.message.document.file_id
    if f_id: m.append({"file_id": f_id})
    await update.message.delete()
    step_idx = context.user_data.get("report_step", 0)
    await update.effective_chat.send_message(f"✅ مدرک دریافت شد. تعداد کل: {len(m)}\nمی‌توانید مدارک بیشتری بفرستید یا تایید نهایی کنید.", reply_markup=report_keyboard(step_idx, len(m)))
    return MEDIA_INPUT

async def next_step(update, context):
    idx = context.user_data.get("report_step", 0) + 1
    if idx >= len(REPORT_STEPS): return await finish_report(update, context)
    context.user_data["report_step"] = idx
    txt = f"📍 مرحله {idx+1} از {len(REPORT_STEPS)}\n\nلطفاً به سوال نمایش داده شده در دکمه پاسخ دهید."
    await update.effective_chat.send_message(txt, reply_markup=report_keyboard(idx, len(context.user_data.get("report_media", []))))
    return MEDIA_INPUT if REPORT_STEPS[idx]["key"] == "media" else REPORT_INPUT

async def finish_report(update, context):
    rep = context.user_data.get("report", {})
    med = context.user_data.get("report_media", [])
    u = update.effective_user
    risk = calculate_risk_score(rep, len(med))
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO reports (reporter_id, reporter_username, card_number, full_name, phone, username, amount, report_text, risk_score, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (u.id, u.username, rep.get("card_number"), rep.get("full_name"), rep.get("phone"), rep.get("username"), rep.get("amount"), rep.get("report_text"), risk, now_text()))
        r_id = cur.lastrowid
        for i in med: conn.execute("INSERT INTO report_media (report_id, file_id, created_at) VALUES (?,?,?)", (r_id, i["file_id"], now_text()))
    context.user_data.clear()
    await update.effective_chat.send_message(f"✅ گزارش شما با شماره {r_id} ثبت شد و پس از تایید ادمین قابل جستجو خواهد بود.", reply_markup=main_menu_keyboard(u.id))
    return MENU

async def search(update, context):
    query = f"%{update.message.text}%"
    await update.message.delete()
    rows = db_fetchall("SELECT * FROM reports WHERE status='approved' AND (card_number LIKE ? OR full_name LIKE ? OR username LIKE ? OR report_text LIKE ?)", (query, query, query, query))
    if not rows:
        await update.effective_chat.send_message("🔍 نتیجه‌ای یافت نشد (فقط گزارش‌های تایید شده نمایش داده می‌شوند).", reply_markup=main_menu_keyboard(update.effective_user.id))
        return MENU
    for r in rows:
        txt = f"📄 گزارش شماره {r['id']}\n👤 نام: {r['full_name']}\n💳 کارت: {r['card_number'] or '---'}\n📝 شرح: {r['report_text'][:200]}..."
        await update.effective_chat.send_message(txt)
    await update.effective_chat.send_message("✅ پایان نتایج جستجو", reply_markup=main_menu_keyboard(update.effective_user.id))
    return MENU

async def admin_home(update, context):
    if not is_admin(update.effective_user.id): return MENU
    txt = "👮 پنل مدیریت\nیکی از بخش‌ها را انتخاب کنید:"
    btns = [
        [InlineKeyboardButton("📥 گزارش‌های در انتظار", callback_data="admin:list:pending")],
        [InlineKeyboardButton("✅ گزارش‌های تایید شده", callback_data="admin:list:approved")],
        [InlineKeyboardButton("📊 آمار کلی", callback_data="admin:stats")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu:home")]
    ]
    await update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(btns))
    return MENU
async def admin_callbacks(update, context):
    query = update.callback_query
    data = query.data
    u_id = update.effective_user.id
    if not is_admin(u_id): return
    
    if data == "admin:stats":
        total = db_fetchone("SELECT COUNT(*) as c FROM reports")["c"]
        pend = db_fetchone("SELECT COUNT(*) as c FROM reports WHERE status='pending'")["c"]
        usr = db_fetchone("SELECT COUNT(*) as c FROM users")["c"]
        txt = f"📊 آمار سیستم:\n\n👥 کل کاربران: {usr}\n📝 کل گزارش‌ها: {total}\n📥 در انتظار بررسی: {pend}"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")]]))
    
    elif data.startswith("admin:list:"):
        st = data.split(":")[-1]
        rows = db_fetchall("SELECT id, full_name FROM reports WHERE status=? LIMIT 10", (st,))
        if not rows:
            await query.answer("گزارشی یافت نشد.")
            return
        btns = [[InlineKeyboardButton(f"📄 {r['full_name']} (#{r['id']})", callback_data=f"admin:view:{r['id']}")] for r in rows]
        btns.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")])
        await query.edit_message_text(f"لیست گزارش‌های {st}:", reply_markup=InlineKeyboardMarkup(btns))

    elif data.startswith("admin:view:"):
        r_id = data.split(":")[-1]
        r = db_fetchone("SELECT * FROM reports WHERE id=?", (r_id,))
        txt = f"📄 جزئیات گزارش {r_id}:\n\n👤 نام: {r['full_name']}\n💳 کارت: {r['card_number']}\n📞 تماس: {r['phone']}\n🆔 یوزرنیم: {r['username']}\n💰 مبلغ: {r['amount']}\n📝 متن: {r['report_text']}\n📌 وضعیت: {r['status']}"
        btns = [
            [InlineKeyboardButton("✅ تایید", callback_data=f"admin:set:approved:{r_id}"), InlineKeyboardButton("❌ رد", callback_data=f"admin:set:rejected:{r_id}")],
            [InlineKeyboardButton("🗑 حذف", callback_data=f"admin:set:removed:{r_id}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")]
        ]
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(btns))

    elif data.startswith("admin:set:"):
        _, _, status, r_id = data.split(":")
        db_execute("UPDATE reports SET status=? WHERE id=?", (status, r_id))
        await query.answer(f"وضعیت به {status} تغییر یافت.")
        await admin_home(update, context)

    elif data == "admin:reset_confirm":
        db_execute("DROP TABLE IF EXISTS reports")
        db_execute("DROP TABLE IF EXISTS report_media")
        init_db()
        await query.answer("دیتابیس گزارش‌ها ریست شد.", show_alert=True)
        await admin_home(update, context)

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(filters.ALL, start)],
        states={
            MENU: [CallbackQueryHandler(admin_home, pattern="^admin:home$"), CallbackQueryHandler(admin_callbacks, pattern="^admin:"), CallbackQueryHandler(show_main_menu, pattern="^menu:home$"), CallbackQueryHandler(lambda u,c: MENU, pattern="^noop$"), CallbackQueryHandler(lambda u,c: ConversationHandler.END, pattern="^report:cancel$"), CallbackQueryHandler(lambda u,c: next_step(u,c), pattern="^report:skip$"), CallbackQueryHandler(finish_report, pattern="^report:finish_media$"), CallbackQueryHandler(show_main_menu, pattern="^menu:home$"), CallbackQueryHandler(lambda u,c: start(u,c), pattern="^menu:report$"), CallbackQueryHandler(lambda u,c: SEARCH_INPUT, pattern="^menu:search$")],
            REPORT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_report_input)],
            MEDIA_INPUT: [MessageHandler((filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND, handle_media), CallbackQueryHandler(finish_report, pattern="^report:finish_media$")],
            SEARCH_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, search)]
        },
        fallbacks=[CommandHandler("start", start)]
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("myid", lambda u,c: u.message.reply_text(f"ID: {u.effective_user.id}")))
    app.add_handler(CommandHandler("resetdb", lambda u,c: u.message.reply_text("آیا مطمئنید؟", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("بله", callback_data="admin:reset_confirm")]]))))
    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
        
