import os
import sqlite3
from datetime import datetime
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# =========================
# Config
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "database.db").strip()

ADMIN_IDS = []
for item in os.getenv("ADMIN_IDS", "").split(","):
    item = item.strip()
    if item.isdigit():
        ADMIN_IDS.append(int(item))

MENU, REPORT_INPUT, MEDIA_INPUT, SEARCH_INPUT = range(4)

REPORT_STEPS = [
    {
        "key": "card_number",
        "title": "شماره کارت",
        "question": "💳 شماره کارت فرد موردنظر را وارد کنید",
        "required": False,
    },
    {
        "key": "full_name",
        "title": "نام و نام خانوادگی",
        "question": "👤 نام و نام خانوادگی فرد موردنظر را وارد کنید",
        "required": True,
    },
    {
        "key": "phone",
        "title": "شماره تماس",
        "question": "📞 شماره تماس فرد موردنظر را وارد کنید",
        "required": False,
    },
    {
        "key": "username",
        "title": "آیدی تلگرام",
        "question": "🆔 آیدی تلگرام فرد موردنظر را وارد کنید، مثل @username",
        "required": False,
    },
    {
        "key": "amount",
        "title": "مبلغ",
        "question": "💰 مبلغ یا حدود مبلغ را وارد کنید",
        "required": False,
    },
    {
        "key": "report_text",
        "title": "شرح گزارش",
        "question": "📝 شرح کامل گزارش را وارد کنید",
        "required": True,
    },
    {
        "key": "media",
        "title": "مدارک",
        "question": "📎 عکس، اسکرین‌شات، فایل یا PDF مدارک را ارسال کنید",
        "required": False,
    },
]

STATUS_LABELS = {
    "pending": "📥 در انتظار بررسی",
    "approved": "✅ تایید شده",
    "rejected": "❌ رد شده",
    "removed": "🗑️ حذف شده",
    "need_more": "📎 نیازمند مدرک بیشتر",
    "disputed": "⚠️ دارای اعتراض",
}

# =========================
# Helpers
# =========================
def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def show(value) -> str:
    value = clean(value)
    return value if value else "ثبت نشده"


def is_admin(user_id: Optional[int]) -> bool:
    return bool(user_id and user_id in ADMIN_IDS)


def get_conn():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def db_execute(query, params=()):
    with get_conn() as conn:
        conn.execute(query, params)
        conn.commit()


def db_fetchone(query, params=()):
    with get_conn() as conn:
        return conn.execute(query, params).fetchone()


def db_fetchall(query, params=()):
    with get_conn() as conn:
        return conn.execute(query, params).fetchall()


def init_db():
    db_execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            is_blocked INTEGER DEFAULT 0,
            reports_count INTEGER DEFAULT 0,
            rejected_reports_count INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    db_execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER,
            reporter_username TEXT,
            card_number TEXT,
            full_name TEXT,
            phone TEXT,
            username TEXT,
            amount TEXT,
            report_text TEXT,
            status TEXT DEFAULT 'pending',
            admin_note TEXT,
            risk_score INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    db_execute(
        """
        CREATE TABLE IF NOT EXISTS report_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER,
            file_id TEXT,
            file_type TEXT,
            file_name TEXT,
            created_at TEXT
        )
        """
    )

    # Safe migration for old databases
    try:
        report_cols = [row["name"] for row in db_fetchall("PRAGMA table_info(reports)")]
        needed_report_cols = {
            "reporter_id": "INTEGER",
            "reporter_username": "TEXT",
            "card_number": "TEXT",
            "full_name": "TEXT",
            "phone": "TEXT",
            "username": "TEXT",
            "amount": "TEXT",
            "report_text": "TEXT",
            "status": "TEXT DEFAULT 'pending'",
            "admin_note": "TEXT",
            "risk_score": "INTEGER DEFAULT 0",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        }
        for col, col_type in needed_report_cols.items():
            if col not in report_cols:
                db_execute(f"ALTER TABLE reports ADD COLUMN {col} {col_type}")
    except Exception:
        pass


def save_user(update: Update):
    user = update.effective_user
    if not user:
        return

    old = db_fetchone("SELECT user_id FROM users WHERE user_id=?", (user.id,))
    if old:
        db_execute(
            """
            UPDATE users
            SET username=?, first_name=?, last_name=?, updated_at=?
            WHERE user_id=?
            """,
            (user.username or "", user.first_name or "", user.last_name or "", now_text(), user.id),
        )
    else:
        db_execute(
            """
            INSERT INTO users
            (user_id, username, first_name, last_name, is_blocked, reports_count, rejected_reports_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, 0, 0, ?, ?)
            """,
            (user.id, user.username or "", user.first_name or "", user.last_name or "", now_text(), now_text()),
        )


def user_is_blocked(user_id: int) -> bool:
    row = db_fetchone("SELECT is_blocked FROM users WHERE user_id=?", (user_id,))
    return bool(row and row["is_blocked"] == 1)


def calculate_risk_score(report: dict, media_count: int) -> int:
    score = 20
    if clean(report.get("full_name")): score += 20
    if clean(report.get("card_number")): score += 15
    if clean(report.get("phone")): score += 10
    if clean(report.get("username")): score += 10
    if clean(report.get("report_text")): score += 15
    if media_count > 0: score += 10
    return min(score, 100)

# =========================
# Keyboards
# =========================
def main_menu_keyboard(user_id: Optional[int] = None):
    rows = [
        [InlineKeyboardButton("📝 ثبت گزارش", callback_data="menu:report")],
        [InlineKeyboardButton("🔍 جستجو", callback_data="menu:search")],
        [InlineKeyboardButton("ℹ️ راهنما", callback_data="menu:help")],
    ]
    if is_admin(user_id):
        rows.append([InlineKeyboardButton("👮 پنل ادمین", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def report_keyboard(step_index: int, media_count: int = 0):
    step = REPORT_STEPS[step_index]
    rows = [[InlineKeyboardButton(f"❓ {step['question']}", callback_data="noop")]]

    if step["key"] == "media":
        rows.append([InlineKeyboardButton(f"✅ پایان ارسال مدارک ({media_count})", callback_data="report:finish_media")])

    nav = []
    if step_index > 0:
        nav.append(InlineKeyboardButton("🔙 قبلی", callback_data="report:back"))
    if not step["required"]:
        nav.append(InlineKeyboardButton("⏭️ رد کردن", callback_data="report:skip"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("❌ لغو", callback_data="report:cancel")])
    return InlineKeyboardMarkup(rows)


def admin_home_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📥 در انتظار بررسی", callback_data="admin:list:pending")],
            [InlineKeyboardButton("✅ تایید شده‌ها", callback_data="admin:list:approved")],
            [InlineKeyboardButton("❌ رد شده‌ها", callback_data="admin:list:rejected")],
            [InlineKeyboardButton("📊 آمار", callback_data="admin:stats")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="menu:home")],
        ]
    )

# =========================
# User Handlers
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
    user = update.effective_user

    if user and user_is_blocked(user.id):
        await update.effective_chat.send_message("🚫 دسترسی شما به ربات مسدود شده است.")
        return ConversationHandler.END

    context.user_data.clear()
    text = (
        "سلام 👋\n\n"
        "به سامانه ثبت و جستجوی گزارش خوش آمدید.\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید."
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(user.id if user else None))
    else:
        await update.effective_chat.send_message(text, reply_markup=main_menu_keyboard(user.id if user else None))

    return MENU


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    save_user(update)

    data = query.data
    user = update.effective_user

    if user and user_is_blocked(user.id):
        await query.edit_message_text("🚫 دسترسی شما به ربات مسدود شده است.")
        return ConversationHandler.END

    if data == "menu:home":
        return await start(update, context)

    if data == "menu:help":
        text = (
            "ℹ️ راهنما\n\n"
            "📝 ثبت گزارش: اطلاعات را مرحله‌به‌مرحله وارد کنید.\n"
            "📎 در بخش مدارک می‌توانید عکس، اسکرین‌شات، فایل یا PDF بفرستید.\n"
            "🔍 جستجو فقط بین گزارش‌های تایید شده انجام می‌شود.\n\n"
            "⚠️ گزارش‌ها قبل از نمایش عمومی توسط ادمین بررسی می‌شوند."
        )
        await query.edit_message_text(text, reply_markup=main_menu_keyboard(user.id if user else None))
        return MENU

    if data == "menu:report":
        context.user_data.clear()
        context.user_data["report"] = {}
        context.user_data["report_media"] = []
        context.user_data["report_step"] = 0
        await query.edit_message_text(
            "📝 ثبت گزارش جدید\n\nلطفاً به سوال نمایش‌داده‌شده در دکمه پاسخ دهید.",
            reply_markup=report_keyboard(0, 0),
        )
        return REPORT_INPUT

    if data == "menu:search":
        context.user_data.clear()
        await query.edit_message_text(
            "🔍 عبارت جستجو را ارسال کنید.\n\n"
            "می‌توانید نام، شماره کارت، شماره تماس، آیدی تلگرام یا بخشی از متن گزارش را بفرستید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu:home")]]),
        )
        return SEARCH_INPUT

    return MENU


async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("این دکمه فقط برای نمایش سوال است.", show_alert=False)
    return None


async def cancel_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("لغو شد")
    context.user_data.clear()
    await query.edit_message_text("❌ عملیات لغو شد.", reply_markup=main_menu_keyboard(update.effective_user.id))
    return MENU


async def go_previous_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    step_index = context.user_data.get("report_step", 0)
    if step_index > 0:
        step_index -= 1
    context.user_data["report_step"] = step_index

    await query.edit_message_text(
        f"📝 مرحله {step_index + 1} از {len(REPORT_STEPS)}\n\n"
        "لطفاً به سوال نمایش‌داده‌شده در دکمه پاسخ دهید.",
        reply_markup=report_keyboard(step_index, len(context.user_data.get("report_media", []))),
    )
    return MEDIA_INPUT if REPORT_STEPS[step_index]["key"] == "media" else REPORT_INPUT


async def skip_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await move_next(update, context, edit=True)


async def move_next(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    current = context.user_data.get("report_step", 0)
    next_index = current + 1

    if next_index >= len(REPORT_STEPS):
        return await finish_report(update, context)

    context.user_data["report_step"] = next_index
    text = (
        f"📝 مرحله {next_index + 1} از {len(REPORT_STEPS)}\n\n"
        "لطفاً به سوال نمایش‌داده‌شده در دکمه پاسخ دهید."
    )
    keyboard = report_keyboard(next_index, len(context.user_data.get("report_media", [])))

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.effective_chat.send_message(text, reply_markup=keyboard)

    return MEDIA_INPUT if REPORT_STEPS[next_index]["key"] == "media" else REPORT_INPUT


async def handle_report_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step_index = context.user_data.get("report_step", 0)
    step = REPORT_STEPS[step_index]

    if step["key"] == "media":
        await update.message.reply_text("📎 لطفاً در این مرحله فایل، عکس یا PDF ارسال کنید یا دکمه پایان ارسال مدارک را بزنید.")
        return MEDIA_INPUT

    value = clean(update.message.text)
    if step["required"] and not value:
        await update.message.reply_text("⚠️ این مرحله اجباری است. لطفاً مقدار معتبر وارد کنید.")
        return REPORT_INPUT

    context.user_data.setdefault("report", {})[step["key"]] = value

    try:
        await update.message.delete()
    except Exception:
        pass

    return await move_next(update, context)


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    media_items = context.user_data.setdefault("report_media", [])

    file_id = None
    file_type = None
    file_name = ""

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_type = "photo"
    elif update.message.document:
        file_id = update.message.document.file_id
        file_type = "document"
        file_name = update.message.document.file_name or ""
    elif update.message.video:
        file_id = update.message.video.file_id
        file_type = "video"
    elif update.message.audio:
        file_id = update.message.audio.file_id
        file_type = "audio"

    if not file_id:
        await update.message.reply_text("⚠️ فقط عکس، فایل، PDF یا اسکرین‌شات قابل دریافت است.")
        return MEDIA_INPUT

    media_items.append({"file_id": file_id, "file_type": file_type, "file_name": file_name})

    try:
        await update.message.delete()
    except Exception:
        pass

    step_index = context.user_data.get("report_step", 0)
    await update.effective_chat.send_message(
        f"✅ مدرک دریافت شد.\nتعداد مدارک ثبت‌شده: {len(media_items)}\n\n"
        "اگر مدرک دیگری دارید ارسال کنید؛ در غیر این صورت دکمه پایان ارسال مدارک را بزنید.",
        reply_markup=report_keyboard(step_index, len(media_items)),
    )
    return MEDIA_INPUT


async def finish_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    return await finish_report(update, context)


async def finish_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    report = context.user_data.get("report", {})
    media_items = context.user_data.get("report_media", [])

    if not clean(report.get("full_name")) or not clean(report.get("report_text")):
        msg = "⚠️ گزارش ناقص است. نام و شرح گزارش اجباری هستند."
        if update.callback_query:
            await update.callback_query.edit_message_text(msg, reply_markup=main_menu_keyboard(user.id if user else None))
        else:
            await update.effective_chat.send_message(msg, reply_markup=main_menu_keyboard(user.id if user else None))
        context.user_data.clear()
        return MENU

    risk_score = calculate_risk_score(report, len(media_items))

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO reports
            (reporter_id, reporter_username, card_number, full_name, phone, username, amount, report_text, status, risk_score, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                user.id if user else None,
                user.username if user and user.username else "",
                clean(report.get("card_number")),
                clean(report.get("full_name")),
                clean(report.get("phone")),
                clean(report.get("username")),
                clean(report.get("amount")),
                clean(report.get("report_text")),
                risk_score,
                now_text(),
                now_text(),
            ),
        )
        report_id = cur.lastrowid

        for item in media_items:
            conn.execute(
                """
                INSERT INTO report_media (report_id, file_id, file_type, file_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (report_id, item.get("file_id"), item.get("file_type"), item.get("file_name"), now_text()),
            )

        if user:
            conn.execute("UPDATE users SET reports_count = reports_count + 1 WHERE user_id=?", (user.id,))
        conn.commit()

    context.user_data.clear()
    text = (
        f"✅ گزارش شما با شماره {report_id} ثبت شد.\n\n"
        "وضعیت فعلی: 📥 در انتظار بررسی\n"
        "بعد از تایید ادمین، در نتایج جستجو قابل مشاهده خواهد بود."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(user.id if user else None))
    else:
        await update.effective_chat.send_message(text, reply_markup=main_menu_keyboard(user.id if user else None))
    return MENU


async def handle_search_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    term = clean(update.message.text)
    try: await update.message.delete()
    except Exception: pass

    if not term:
        await update.effective_chat.send_message("⚠️ لطفاً یک عبارت معتبر برای جستجو ارسال کنید.")
        return SEARCH_INPUT

    like = f"%{term}%"
    rows = db_fetchall(
        """
        SELECT * FROM reports
        WHERE status='approved'
        AND (card_number LIKE ? OR full_name LIKE ? OR phone LIKE ? OR username LIKE ? OR amount LIKE ? OR report_text LIKE ?)
        ORDER BY id DESC LIMIT 10
        """,
        (like, like, like, like, like, like),
    )

    if not rows:
        await update.effective_chat.send_message(
            "🔍 نتیجه‌ای یافت نشد.\n\nفقط گزارش‌های تاییدشده نمایش داده می‌شوند.",
            reply_markup=main_menu_keyboard(update.effective_user.id),
        )
        return MENU

    for row in rows:
        media_count = db_fetchone("SELECT COUNT(*) AS c FROM report_media WHERE report_id=?", (row["id"],))["c"]
        text = (
            f"📄 گزارش شماره: {row['id']}\n"
            f"📍 وضعیت: {STATUS_LABELS.get(row['status'], row['status'])}\n\n"
            f"👤 نام: {show(row['full_name'])}\n"
            f"💳 شماره کارت: {show(row['card_number'])}\n"
            f"📞 شماره تماس: {show(row['phone'])}\n"
            f"🆔 آیدی تلگرام: {show(row['username'])}\n"
            f"💰 مبلغ: {show(row['amount'])}\n"
            f"📎 تعداد مدارک: {media_count}\n\n"
            f"📝 شرح:\n{show(row['report_text'])}"
        )
        await update.effective_chat.send_message(text)

    await update.effective_chat.send_message("✅ پایان نتایج جستجو", reply_markup=main_menu_keyboard(update.effective_user.id))
    return MENU

# =========================
# Admin Handlers
# =========================
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ شما ادمین نیستید.")
        return MENU
    await update.message.reply_text("👮 پنل مدیریت", reply_markup=admin_home_keyboard())
    return MENU


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ شما ادمین نیستید.")
        return
    await update.message.reply_text(get_stats_text())


def get_stats_text() -> str:
    total_users = db_fetchone("SELECT COUNT(*) AS c FROM users")["c"]
    blocked_users = db_fetchone("SELECT COUNT(*) AS c FROM users WHERE is_blocked=1")["c"]
    total_reports = db_fetchone("SELECT COUNT(*) AS c FROM reports")["c"]
    pending = db_fetchone("SELECT COUNT(*) AS c FROM reports WHERE status='pending'")["c"]
    approved = db_fetchone("SELECT COUNT(*) AS c FROM reports WHERE status='approved'")["c"]
    rejected = db_fetchone("SELECT COUNT(*) AS c FROM reports WHERE status='rejected'")["c"]

    return (
        "📊 آمار سیستم\n\n"
        f"👥 کاربران: {total_users}\n"
        f"🚫 کاربران مسدود: {blocked_users}\n"
        f"📝 کل گزارش‌ها: {total_reports}\n"
        f"📥 در انتظار بررسی: {pending}\n"
        f"✅ تایید شده: {approved}\n"
        f"❌ رد شده: {rejected}"
    )


async def dbpath_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text(f"📁 DATABASE_PATH:\n{DATABASE_PATH}")


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 Your Telegram ID:\n{update.effective_user.id}")


async def resetdb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⚠️ بله، ریست کن", callback_data="admin:reset_confirm")],
         [InlineKeyboardButton("لغو", callback_data="admin:home")]]
    )
    await update.message.reply_text(
        "⚠️ هشدار جدی\n\nبا این کار تمام گزارش‌ها و مدارک حذف می‌شوند.\nآیا مطمئن هستید؟",
        reply_markup=keyboard,
    )


async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id): return MENU

    data = query.data
    if data == "admin:home":
        await query.edit_message_text("👮 پنل مدیریت", reply_markup=admin_home_keyboard())
        return MENU

    if data == "admin:stats":
        await query.edit_message_text(get_stats_text(), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")]]))
        return MENU

    if data == "admin:reset_confirm":
        db_execute("DROP TABLE IF EXISTS report_media")
        db_execute("DROP TABLE IF EXISTS reports")
        init_db()
        await query.edit_message_text("✅ دیتابیس گزارش‌ها ریست شد.", reply_markup=admin_home_keyboard())
        return MENU

    if data.startswith("admin:list:"):
        status = data.split(":", 2)[2]
        rows = db_fetchall("SELECT id, full_name FROM reports WHERE status=? ORDER BY id DESC LIMIT 20", (status,))
        if not rows:
            await query.edit_message_text(f"گزارشی با وضعیت {STATUS_LABELS.get(status, status)} وجود ندارد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")]]))
            return MENU
        buttons = [[InlineKeyboardButton(f"📄 #{row['id']} - {show(row['full_name'])}", callback_data=f"admin:view:{row['id']}")] for row in rows]
        buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")])
        await query.edit_message_text(f"لیست گزارش‌ها: {STATUS_LABELS.get(status, status)}", reply_markup=InlineKeyboardMarkup(buttons))
        return MENU

    if data.startswith("admin:view:"):
        return await show_admin_report(query, int(data.split(":")[2]))

    if data.startswith("admin:set:"):
        parts = data.split(":")
        st, rid = parts[2], int(parts[3])
        db_execute("UPDATE reports SET status=?, updated_at=? WHERE id=?", (st, now_text(), rid))
        return await show_admin_report(query, rid)

    if data.startswith("admin:block_reporter:"):
        rid = int(data.split(":")[2])
        row = db_fetchone("SELECT reporter_id FROM reports WHERE id=?", (rid,))
        if row and row["reporter_id"]:
            db_execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (row["reporter_id"],))
            await query.answer("کاربر گزارش‌دهنده مسدود شد.", show_alert=True)
        return await show_admin_report(query, rid)
    return MENU


async def show_admin_report(query, report_id: int):
    row = db_fetchone("SELECT * FROM reports WHERE id=?", (report_id,))
    if not row: return MENU
    media_count = db_fetchone("SELECT COUNT(*) AS c FROM report_media WHERE report_id=?", (report_id,))["c"]
    text = (
        f"📄 جزئیات گزارش #{row['id']}\n📍 وضعیت: {STATUS_LABELS.get(row['status'], row['status'])}\n"
        f"⭐️ امتیاز تکمیل: {row['risk_score']}\n\n👤 نام: {show(row['full_name'])}\n"
        f"💳 شماره کارت: {show(row['card_number'])}\n📞 تماس: {show(row['phone'])}\n"
        f"🆔 آیدی فرد: {show(row['username'])}\n💰 مبلغ: {show(row['amount'])}\n"
        f"📎 مدارک: {media_count}\n👤 گزارش‌دهنده: {show(row['reporter_username'])} ({row['reporter_id']})\n"
        f"🕒 ثبت: {row['created_at']}\n\n📝 شرح:\n{show(row['report_text'])}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید", callback_data=f"admin:set:approved:{report_id}"), InlineKeyboardButton("❌ رد", callback_data=f"admin:set:rejected:{report_id}")],
        [InlineKeyboardButton("📎 مدرک بیشتر", callback_data=f"admin:set:need_more:{report_id}"), InlineKeyboardButton("🗑️ حذف", callback_data=f"admin:set:removed:{report_id}")],
        [InlineKeyboardButton("🚫 بلاک گزارش‌دهنده", callback_data=f"admin:block_reporter:{report_id}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin:home")]
    ])
    await query.edit_message_text(text, reply_markup=keyboard)
    return MENU

# =========================
# Error Handler
# =========================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"ERROR: {context.error}")

# =========================
# Main
# =========================
def main():
    if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN is not set.")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MENU: [
                CallbackQueryHandler(noop_callback, pattern="^noop$"),
                CallbackQueryHandler(admin_callbacks, pattern="^admin:"),
                CallbackQueryHandler(menu_callback, pattern="^menu:"),
                CommandHandler("admin", admin_command),
            ],
            REPORT_INPUT: [
                CallbackQueryHandler(noop_callback, pattern="^noop$"),
                CallbackQueryHandler(cancel_report, pattern="^report:cancel$"),
                CallbackQueryHandler(go_previous_step, pattern="^report:back$"),
                CallbackQueryHandler(skip_step, pattern="^report:skip$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_report_text),
            ],
            MEDIA_INPUT: [
                CallbackQueryHandler(noop_callback, pattern="^noop$"),
                CallbackQueryHandler(cancel_report, pattern="^report:cancel$"),
                CallbackQueryHandler(go_previous_step, pattern="^report:back$"),
                CallbackQueryHandler(skip_step, pattern="^report:skip$"),
                CallbackQueryHandler(finish_media, pattern="^report:finish_media$"),
                MessageHandler((filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.AUDIO) & ~filters.COMMAND, handle_media),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_media),
            ],
            SEARCH_INPUT: [
                CallbackQueryHandler(menu_callback, pattern="^menu:home$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_text),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("myid", myid_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("dbpath", dbpath_command))
    app.add_handler(CommandHandler("resetdb", resetdb_command))
    app.add_handler(CallbackQueryHandler(admin_callbacks, pattern="^admin:"))
    app.add_error_handler(error_handler)
    print("Bot started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
