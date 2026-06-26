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
        "title": "Ø´Ù…Ø§Ø±Ù‡ Ú©Ø§Ø±Øª",
        "question": "ðŸ’³ Ø´Ù…Ø§Ø±Ù‡ Ú©Ø§Ø±Øª ÙØ±Ø¯ Ù…ÙˆØ±Ø¯Ù†Ø¸Ø± Ø±Ø§ ÙˆØ§Ø±Ø¯ Ú©Ù†ÛŒØ¯",
        "required": False,
    },
    {
        "key": "full_name",
        "title": "Ù†Ø§Ù… Ùˆ Ù†Ø§Ù… Ø®Ø§Ù†ÙˆØ§Ø¯Ú¯ÛŒ",
        "question": "ðŸ‘¤ Ù†Ø§Ù… Ùˆ Ù†Ø§Ù… Ø®Ø§Ù†ÙˆØ§Ø¯Ú¯ÛŒ ÙØ±Ø¯ Ù…ÙˆØ±Ø¯Ù†Ø¸Ø± Ø±Ø§ ÙˆØ§Ø±Ø¯ Ú©Ù†ÛŒØ¯",
        "required": True,
    },
    {
        "key": "phone",
        "title": "Ø´Ù…Ø§Ø±Ù‡ ØªÙ…Ø§Ø³",
        "question": "ðŸ“ž Ø´Ù…Ø§Ø±Ù‡ ØªÙ…Ø§Ø³ ÙØ±Ø¯ Ù…ÙˆØ±Ø¯Ù†Ø¸Ø± Ø±Ø§ ÙˆØ§Ø±Ø¯ Ú©Ù†ÛŒØ¯",
        "required": False,
    },
    {
        "key": "username",
        "title": "Ø¢ÛŒØ¯ÛŒ ØªÙ„Ú¯Ø±Ø§Ù…",
        "question": "ðŸ†” Ø¢ÛŒØ¯ÛŒ ØªÙ„Ú¯Ø±Ø§Ù… ÙØ±Ø¯ Ù…ÙˆØ±Ø¯Ù†Ø¸Ø± Ø±Ø§ ÙˆØ§Ø±Ø¯ Ú©Ù†ÛŒØ¯ØŒ Ù…Ø«Ù„ @username",
        "required": False,
    },
    {
        "key": "amount",
        "title": "Ù…Ø¨Ù„Øº",
        "question": "ðŸ’° Ù…Ø¨Ù„Øº ÛŒØ§ Ø­Ø¯ÙˆØ¯ Ù…Ø¨Ù„Øº Ø±Ø§ ÙˆØ§Ø±Ø¯ Ú©Ù†ÛŒØ¯",
        "required": False,
    },
    {
        "key": "report_text",
        "title": "Ø´Ø±Ø­ Ú¯Ø²Ø§Ø±Ø´",
        "question": "ðŸ“ Ø´Ø±Ø­ Ú©Ø§Ù…Ù„ Ú¯Ø²Ø§Ø±Ø´ Ø±Ø§ ÙˆØ§Ø±Ø¯ Ú©Ù†ÛŒØ¯",
        "required": True,
    },
    {
        "key": "media",
        "title": "Ù…Ø¯Ø§Ø±Ú©",
        "question": "ðŸ“Ž Ø¹Ú©Ø³ØŒ Ø§Ø³Ú©Ø±ÛŒÙ†â€ŒØ´Ø§ØªØŒ ÙØ§ÛŒÙ„ ÛŒØ§ PDF Ù…Ø¯Ø§Ø±Ú© Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†ÛŒØ¯",
        "required": False,
    },
]

STATUS_LABELS = {
    "pending": "ðŸ“¥ Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø± Ø¨Ø±Ø±Ø³ÛŒ",
    "approved": "âœ… ØªØ§ÛŒÛŒØ¯Ø´Ø¯Ù‡",
    "rejected": "âŒ Ø±Ø¯Ø´Ø¯Ù‡",
    "removed": "ðŸ—‘ Ø­Ø°Ùâ€ŒØ´Ø¯Ù‡",
    "need_more": "ðŸ“Ž Ù†ÛŒØ§Ø²Ù…Ù†Ø¯ Ù…Ø¯Ø±Ú© Ø¨ÛŒØ´ØªØ±",
    "disputed": "âš ï¸ Ø¯Ø§Ø±Ø§ÛŒ Ø§Ø¹ØªØ±Ø§Ø¶",
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
    return value if value else "Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡"


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
    if clean(report.get("full_name")):
        score += 20
    if clean(report.get("card_number")):
        score += 15
    if clean(report.get("phone")):
        score += 10
    if clean(report.get("username")):
        score += 10
    if clean(report.get("report_text")):
        score += 15
    if media_count > 0:
        score += 10
    return min(score, 100)

# =========================
# Keyboards
# =========================
def main_menu_keyboard(user_id: Optional[int] = None):
    rows = [
        [InlineKeyboardButton("ðŸ“ Ø«Ø¨Øª Ú¯Ø²Ø§Ø±Ø´", callback_data="menu:report")],
        [InlineKeyboardButton("ðŸ”Ž Ø¬Ø³ØªØ¬Ùˆ", callback_data="menu:search")],
        [InlineKeyboardButton("â„¹ï¸ Ø±Ø§Ù‡Ù†Ù…Ø§", callback_data="menu:help")],
    ]
    if is_admin(user_id):
        rows.append([InlineKeyboardButton("ðŸ‘® Ù¾Ù†Ù„ Ø§Ø¯Ù…ÛŒÙ†", callback_data="admin:home")])
    return InlineKeyboardMarkup(rows)


def report_keyboard(step_index: int, media_count: int = 0):
    step = REPORT_STEPS[step_index]
    rows = [[InlineKeyboardButton(f"â“ {step['question']}", callback_data="noop")]]

    if step["key"] == "media":
        rows.append([InlineKeyboardButton(f"âœ… Ù¾Ø§ÛŒØ§Ù† Ø§Ø±Ø³Ø§Ù„ Ù…Ø¯Ø§Ø±Ú© ({media_count})", callback_data="report:finish_media")])

    nav = []
    if step_index > 0:
        nav.append(InlineKeyboardButton("ðŸ”™ Ù‚Ø¨Ù„ÛŒ", callback_data="report:back"))
    if not step["required"]:
        nav.append(InlineKeyboardButton("â­ Ø±Ø¯ Ú©Ø±Ø¯Ù†", callback_data="report:skip"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("âŒ Ù„ØºÙˆ", callback_data="report:cancel")])
    return InlineKeyboardMarkup(rows)


def admin_home_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("ðŸ“¥ Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø± Ø¨Ø±Ø±Ø³ÛŒ", callback_data="admin:list:pending")],
            [InlineKeyboardButton("âœ… ØªØ§ÛŒÛŒØ¯Ø´Ø¯Ù‡â€ŒÙ‡Ø§", callback_data="admin:list:approved")],
            [InlineKeyboardButton("âŒ Ø±Ø¯Ø´Ø¯Ù‡â€ŒÙ‡Ø§", callback_data="admin:list:rejected")],
            [InlineKeyboardButton("ðŸ“Š Ø¢Ù…Ø§Ø±", callback_data="admin:stats")],
            [InlineKeyboardButton("ðŸ”™ Ø¨Ø§Ø²Ú¯Ø´Øª", callback_data="menu:home")],
        ]
    )

# =========================
# User Handlers
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
    user = update.effective_user

    if user and user_is_blocked(user.id):
        await update.effective_chat.send_message("ðŸš« Ø¯Ø³ØªØ±Ø³ÛŒ Ø´Ù…Ø§ Ø¨Ù‡ Ø±Ø¨Ø§Øª Ù…Ø³Ø¯ÙˆØ¯ Ø´Ø¯Ù‡ Ø§Ø³Øª.")
        return ConversationHandler.END

    context.user_data.clear()
    text = (
        "Ø³Ù„Ø§Ù… ðŸ‘‹\n\n"
        "Ø¨Ù‡ Ø³Ø§Ù…Ø§Ù†Ù‡ Ø«Ø¨Øª Ùˆ Ø¬Ø³ØªØ¬ÙˆÛŒ Ú¯Ø²Ø§Ø±Ø´ Ø®ÙˆØ´ Ø¢Ù…Ø¯ÛŒØ¯.\n"
        "Ù„Ø·ÙØ§Ù‹ ÛŒÚ©ÛŒ Ø§Ø² Ú¯Ø²ÛŒÙ†Ù‡â€ŒÙ‡Ø§ÛŒ Ø²ÛŒØ± Ø±Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†ÛŒØ¯."
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
        await query.edit_message_text("ðŸš« Ø¯Ø³ØªØ±Ø³ÛŒ Ø´Ù…Ø§ Ø¨Ù‡ Ø±Ø¨Ø§Øª Ù…Ø³Ø¯ÙˆØ¯ Ø´Ø¯Ù‡ Ø§Ø³Øª.")
        return ConversationHandler.END

    if data == "menu:home":
        return await start(update, context)

    if data == "menu:help":
        text = (
            "â„¹ï¸ Ø±Ø§Ù‡Ù†Ù…Ø§\n\n"
            "ðŸ“ Ø«Ø¨Øª Ú¯Ø²Ø§Ø±Ø´: Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ø±Ø§ Ù…Ø±Ø­Ù„Ù‡â€ŒØ¨Ù‡â€ŒÙ…Ø±Ø­Ù„Ù‡ ÙˆØ§Ø±Ø¯ Ú©Ù†ÛŒØ¯.\n"
            "ðŸ“Ž Ø¯Ø± Ø¨Ø®Ø´ Ù…Ø¯Ø§Ø±Ú© Ù…ÛŒâ€ŒØªÙˆØ§Ù†ÛŒØ¯ Ø¹Ú©Ø³ØŒ Ø§Ø³Ú©Ø±ÛŒÙ†â€ŒØ´Ø§ØªØŒ ÙØ§ÛŒÙ„ ÛŒØ§ PDF Ø¨ÙØ±Ø³ØªÛŒØ¯.\n"
            "ðŸ”Ž Ø¬Ø³ØªØ¬Ùˆ ÙÙ‚Ø· Ø¨ÛŒÙ† Ú¯Ø²Ø§Ø±Ø´â€ŒÙ‡Ø§ÛŒ ØªØ§ÛŒÛŒØ¯Ø´Ø¯Ù‡ Ø§Ù†Ø¬Ø§Ù… Ù…ÛŒâ€ŒØ´ÙˆØ¯.\n\n"
            "âš ï¸ Ú¯Ø²Ø§Ø±Ø´â€ŒÙ‡Ø§ Ù‚Ø¨Ù„ Ø§Ø² Ù†Ù…Ø§ÛŒØ´ Ø¹Ù…ÙˆÙ…ÛŒ ØªÙˆØ³Ø· Ø§Ø¯Ù…ÛŒÙ† Ø¨Ø±Ø±Ø³ÛŒ Ù…ÛŒâ€ŒØ´ÙˆÙ†Ø¯."
        )
        await query.edit_message_text(text, reply_markup=main_menu_keyboard(user.id if user else None))
        return MENU

    if data == "menu:report":
        context.user_data.clear()
        context.user_data["report"] = {}
        context.user_data["report_media"] = []
        context.user_data["report_step"] = 0
        await query.edit_message_text(
            "ðŸ“ Ø«Ø¨Øª Ú¯Ø²Ø§Ø±Ø´ Ø¬Ø¯ÛŒØ¯\n\n"
            "Ù„Ø·ÙØ§Ù‹ Ø¨Ù‡ Ø³ÙˆØ§Ù„ Ù†Ù…Ø§ÛŒØ´â€ŒØ¯Ø§Ø¯Ù‡â€ŒØ´Ø¯Ù‡ Ø¯Ø± Ø¯Ú©Ù…Ù‡ Ù¾Ø§Ø³Ø® Ø¯Ù‡ÛŒØ¯.",
            reply_markup=report_keyboard(0, 0),
        )
        return REPORT_INPUT

    if data == "menu:search":
        context.user_data.clear()
        await query.edit_message_text(
            "ðŸ”Ž Ø¹Ø¨Ø§Ø±Øª Ø¬Ø³ØªØ¬Ùˆ Ø±Ø§ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†ÛŒØ¯.\n\n"
            "Ù…ÛŒâ€ŒØªÙˆØ§Ù†ÛŒØ¯ Ù†Ø§Ù…ØŒ Ø´Ù…Ø§Ø±Ù‡ Ú©Ø§Ø±ØªØŒ Ø´Ù…Ø§Ø±Ù‡ ØªÙ…Ø§Ø³ØŒ Ø¢ÛŒØ¯ÛŒ ØªÙ„Ú¯Ø±Ø§Ù… ÛŒØ§ Ø¨Ø®Ø´ÛŒ Ø§Ø² Ù…ØªÙ† Ú¯Ø²Ø§Ø±Ø´ Ø±Ø§ Ø¨ÙØ±Ø³ØªÛŒØ¯.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ”™ Ø¨Ø§Ø²Ú¯Ø´Øª", callback_data="menu:home")]]),
        )
        return SEARCH_INPUT

    return MENU


async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Ø§ÛŒÙ† Ø¯Ú©Ù…Ù‡ ÙÙ‚Ø· Ø¨Ø±Ø§ÛŒ Ù†Ù…Ø§ÛŒØ´ Ø³ÙˆØ§Ù„ Ø§Ø³Øª.", show_alert=False)
    return None


async def cancel_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Ù„ØºÙˆ Ø´Ø¯")
    context.user_data.clear()
    await query.edit_message_text("âŒ Ø¹Ù…Ù„ÛŒØ§Øª Ù„ØºÙˆ Ø´Ø¯.", reply_markup=main_menu_keyboard(update.effective_user.id))
    return MENU


async def go_previous_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    step_index = context.user_data.get("report_step", 0)
    if step_index > 0:
        step_index -= 1
    context.user_data["report_step"] = step_index

    await query.edit_message_text(
        f"ðŸ“ Ù…Ø±Ø­Ù„Ù‡ {step_index + 1} Ø§Ø² {len(REPORT_STEPS)}\n\n"
        "Ù„Ø·ÙØ§Ù‹ Ø¨Ù‡ Ø³ÙˆØ§Ù„ Ù†Ù…Ø§ÛŒØ´â€ŒØ¯Ø§Ø¯Ù‡â€ŒØ´Ø¯Ù‡ Ø¯Ø± Ø¯Ú©Ù…Ù‡ Ù¾Ø§Ø³Ø® Ø¯Ù‡ÛŒØ¯.",
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
        f"ðŸ“ Ù…Ø±Ø­Ù„Ù‡ {next_index + 1} Ø§Ø² {len(REPORT_STEPS)}\n\n"
        "Ù„Ø·ÙØ§Ù‹ Ø¨Ù‡ Ø³ÙˆØ§Ù„ Ù†Ù…Ø§ÛŒØ´â€ŒØ¯Ø§Ø¯Ù‡â€ŒØ´Ø¯Ù‡ Ø¯Ø± Ø¯Ú©Ù…Ù‡ Ù¾Ø§Ø³Ø® Ø¯Ù‡ÛŒØ¯."
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
        await update.message.reply_text("ðŸ“Ž Ù„Ø·ÙØ§Ù‹ Ø¯Ø± Ø§ÛŒÙ† Ù…Ø±Ø­Ù„Ù‡ ÙØ§ÛŒÙ„ØŒ Ø¹Ú©Ø³ ÛŒØ§ PDF Ø§Ø±Ø³Ø§Ù„ Ú©Ù†ÛŒØ¯ ÛŒØ§ Ø¯Ú©Ù…Ù‡ Ù¾Ø§ÛŒØ§Ù† Ø§Ø±Ø³Ø§Ù„ Ù…Ø¯Ø§Ø±Ú© Ø±Ø§ Ø¨Ø²Ù†ÛŒØ¯.")
        return MEDIA_INPUT

    value = clean(update.message.text)
    if step["required"] and not value:
        await update.message.reply_text("âš ï¸ Ø§ÛŒÙ† Ù…Ø±Ø­Ù„Ù‡ Ø§Ø¬Ø¨Ø§Ø±ÛŒ Ø§Ø³Øª. Ù„Ø·ÙØ§Ù‹ Ù…Ù‚Ø¯Ø§Ø± Ù…Ø¹ØªØ¨Ø± ÙˆØ§Ø±Ø¯ Ú©Ù†ÛŒØ¯.")
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
        await update.message.reply_text("âš ï¸ ÙÙ‚Ø· Ø¹Ú©Ø³ØŒ ÙØ§ÛŒÙ„ØŒ PDF ÛŒØ§ Ø§Ø³Ú©Ø±ÛŒÙ†â€ŒØ´Ø§Øª Ù‚Ø§Ø¨Ù„ Ø¯Ø±ÛŒØ§ÙØª Ø§Ø³Øª.")
        return MEDIA_INPUT

    media_items.append({"file_id": file_id, "file_type": file_type, "file_name": file_name})

    try:
        await update.message.delete()
    except Exception:
        pass

    step_index = context.user_data.get("report_step", 0)
    await update.effective_chat.send_message(
        f"âœ… Ù…Ø¯Ø±Ú© Ø¯Ø±ÛŒØ§ÙØª Ø´Ø¯.\nØªØ¹Ø¯Ø§Ø¯ Ù…Ø¯Ø§Ø±Ú© Ø«Ø¨Øªâ€ŒØ´Ø¯Ù‡: {len(media_items)}\n\n"
        "Ø§Ú¯Ø± Ù…Ø¯Ø±Ú© Ø¯ÛŒÚ¯Ø±ÛŒ Ø¯Ø§Ø±ÛŒØ¯ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†ÛŒØ¯Ø› Ø¯Ø± ØºÛŒØ± Ø§ÛŒÙ† ØµÙˆØ±Øª Ø¯Ú©Ù…Ù‡ Ù¾Ø§ÛŒØ§Ù† Ø§Ø±Ø³Ø§Ù„ Ù…Ø¯Ø§Ø±Ú© Ø±Ø§ Ø¨Ø²Ù†ÛŒØ¯.",
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
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "âš ï¸ Ú¯Ø²Ø§Ø±Ø´ Ù†Ø§Ù‚Øµ Ø§Ø³Øª. Ù†Ø§Ù… Ùˆ Ø´Ø±Ø­ Ú¯Ø²Ø§Ø±Ø´ Ø§Ø¬Ø¨Ø§Ø±ÛŒ Ù‡Ø³ØªÙ†Ø¯.",
                reply_markup=main_menu_keyboard(user.id if user else None),
            )
        else:
            await update.effective_chat.send_message(
                "âš ï¸ Ú¯Ø²Ø§Ø±Ø´ Ù†Ø§Ù‚Øµ Ø§Ø³Øª. Ù†Ø§Ù… Ùˆ Ø´Ø±Ø­ Ú¯Ø²Ø§Ø±Ø´ Ø§Ø¬Ø¨Ø§Ø±ÛŒ Ù‡Ø³ØªÙ†Ø¯.",
                reply_markup=main_menu_keyboard(user.id if user else None),
            )
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
        f"âœ… Ú¯Ø²Ø§Ø±Ø´ Ø´Ù…Ø§ Ø¨Ø§ Ø´Ù…Ø§Ø±Ù‡ {report_id} Ø«Ø¨Øª Ø´Ø¯.\n\n"
        "ÙˆØ¶Ø¹ÛŒØª ÙØ¹Ù„ÛŒ: ðŸ“¥ Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø± Ø¨Ø±Ø±Ø³ÛŒ\n"
        "Ø¨Ø¹Ø¯ Ø§Ø² ØªØ§ÛŒÛŒØ¯ Ø§Ø¯Ù…ÛŒÙ†ØŒ Ø¯Ø± Ù†ØªØ§ÛŒØ¬ Ø¬Ø³ØªØ¬Ùˆ Ù‚Ø§Ø¨Ù„ Ù…Ø´Ø§Ù‡Ø¯Ù‡ Ø®ÙˆØ§Ù‡Ø¯ Ø¨ÙˆØ¯."
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(user.id if user else None))
    else:
        await update.effective_chat.send_message(text, reply_markup=main_menu_keyboard(user.id if user else None))

    return MENU


async def handle_search_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    term = clean(update.message.text)
    try:
        await update.message.delete()
    except Exception:
        pass

    if not term:
        await update.effective_chat.send_message("âš ï¸ Ù„Ø·ÙØ§Ù‹ ÛŒÚ© Ø¹Ø¨Ø§Ø±Øª Ù…Ø¹ØªØ¨Ø± Ø¨Ø±Ø§ÛŒ Ø¬Ø³ØªØ¬Ùˆ Ø§Ø±Ø³Ø§Ù„ Ú©Ù†ÛŒØ¯.")
        return SEARCH_INPUT

    like = f"%{term}%"
    rows = db_fetchall(
        """
        SELECT * FROM reports
        WHERE status='approved'
        AND (
            card_number LIKE ? OR
            full_name LIKE ? OR
            phone LIKE ? OR
            username LIKE ? OR
            amount LIKE ? OR
            report_text LIKE ?
        )
        ORDER BY id DESC
        LIMIT 10
        """,
        (like, like, like, like, like, like),
    )

    if not rows:
        await update.effective_chat.send_message(
            "ðŸ” Ù†ØªÛŒØ¬Ù‡â€ŒØ§ÛŒ ÛŒØ§ÙØª Ù†Ø´Ø¯.\n\nÙÙ‚Ø· Ú¯Ø²Ø§Ø±Ø´â€ŒÙ‡Ø§ÛŒ ØªØ§ÛŒÛŒØ¯Ø´Ø¯Ù‡ Ù†Ù…Ø§ÛŒØ´ Ø¯Ø§Ø¯Ù‡ Ù…ÛŒâ€ŒØ´ÙˆÙ†Ø¯.",
            reply_markup=main_menu_keyboard(update.effective_user.id),
        )
        return MENU

    for row in rows:
        media_count = db_fetchone("SELECT COUNT(*) AS c FROM report_media WHERE report_id=?", (row["id"],))["c"]
        text = (
            f"ðŸ“„ Ú¯Ø²Ø§Ø±Ø´ Ø´Ù…Ø§Ø±Ù‡: {row['id']}\n"
            f"ðŸ“Œ ÙˆØ¶Ø¹ÛŒØª: {STATUS_LABELS.get(row['status'], row['status'])}\n\n"
            f"ðŸ‘¤ Ù†Ø§Ù…: {show(row['full_name'])}\n"
            f"ðŸ’³ Ø´Ù…Ø§Ø±Ù‡ Ú©Ø§Ø±Øª: {show(row['card_number'])}\n"
            f"ðŸ“ž Ø´Ù…Ø§Ø±Ù‡ ØªÙ…Ø§Ø³: {show(row['phone'])}\n"
            f"ðŸ†” Ø¢ÛŒØ¯ÛŒ ØªÙ„Ú¯Ø±Ø§Ù…: {show(row['username'])}\n"
            f"ðŸ’° Ù…Ø¨Ù„Øº: {show(row['amount'])}\n"
            f"ðŸ“Ž ØªØ¹Ø¯Ø§Ø¯ Ù…Ø¯Ø§Ø±Ú©: {media_count}\n\n"
            f"ðŸ“ Ø´Ø±Ø­:\n{show(row['report_text'])}"
        )
        await update.effective_chat.send_message(text)

    await update.effective_chat.send_message("âœ… Ù¾Ø§ÛŒØ§Ù† Ù†ØªØ§ÛŒØ¬ Ø¬Ø³ØªØ¬Ùˆ", reply_markup=main_menu_keyboard(update.effective_user.id))
    return MENU

# =========================
# Admin Handlers
# =========================
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("â›”ï¸ Ø´Ù…Ø§ Ø§Ø¯Ù…ÛŒÙ† Ù†ÛŒØ³ØªÛŒØ¯.")
        return MENU
    await update.message.reply_text("ðŸ‘® Ù¾Ù†Ù„ Ù…Ø¯ÛŒØ±ÛŒØª", reply_markup=admin_home_keyboard())
    return MENU


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("â›”ï¸ Ø´Ù…Ø§ Ø§Ø¯Ù…ÛŒÙ† Ù†ÛŒØ³ØªÛŒØ¯.")
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
        "ðŸ“Š Ø¢Ù…Ø§Ø± Ø³ÛŒØ³ØªÙ…\n\n"
        f"ðŸ‘¥ Ú©Ø§Ø±Ø¨Ø±Ø§Ù†: {total_users}\n"
        f"ðŸš« Ú©Ø§Ø±Ø¨Ø±Ø§Ù† Ù…Ø³Ø¯ÙˆØ¯: {blocked_users}\n"
        f"ðŸ“ Ú©Ù„ Ú¯Ø²Ø§Ø±Ø´â€ŒÙ‡Ø§: {total_reports}\n"
        f"ðŸ“¥ Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø± Ø¨Ø±Ø±Ø³ÛŒ: {pending}\n"
        f"âœ… ØªØ§ÛŒÛŒØ¯Ø´Ø¯Ù‡: {approved}\n"
        f"âŒ Ø±Ø¯Ø´Ø¯Ù‡: {rejected}"
    )


async def dbpath_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("â›”ï¸ Ø´Ù…Ø§ Ø§Ø¯Ù…ÛŒÙ† Ù†ÛŒØ³ØªÛŒØ¯.")
        return
    await update.message.reply_text(f"ðŸ“ DATABASE_PATH:\n{DATABASE_PATH}")


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"ðŸ†” Your Telegram ID:\n{update.effective_user.id}")


async def resetdb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("â›”ï¸ Ø´Ù…Ø§ Ø§Ø¯Ù…ÛŒÙ† Ù†ÛŒØ³ØªÛŒØ¯.")
        return
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("âš ï¸ Ø¨Ù„Ù‡ØŒ Ø±ÛŒØ³Øª Ú©Ù†", callback_data="admin:reset_confirm")],
            [InlineKeyboardButton("Ù„ØºÙˆ", callback_data="admin:home")],
        ]
    )
    await update.message.reply_text(
        "âš ï¸ Ù‡Ø´Ø¯Ø§Ø± Ø¬Ø¯ÛŒ\n\n"
        "Ø¨Ø§ Ø§ÛŒÙ† Ú©Ø§Ø± ØªÙ…Ø§Ù… Ú¯Ø²Ø§Ø±Ø´â€ŒÙ‡Ø§ Ùˆ Ù…Ø¯Ø§Ø±Ú© Ø«Ø¨Øªâ€ŒØ´Ø¯Ù‡ Ø­Ø°Ù Ù…ÛŒâ€ŒØ´ÙˆÙ†Ø¯.\n"
        "Ø¢ÛŒØ§ Ù…Ø·Ù…Ø¦Ù† Ù‡Ø³ØªÛŒØ¯ØŸ",
        reply_markup=keyboard,
    )


async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update.effective_user.id):
        await query.edit_message_text("â›”ï¸ Ø´Ù…Ø§ Ø§Ø¯Ù…ÛŒÙ† Ù†ÛŒØ³ØªÛŒØ¯.")
        return MENU

    data = query.data

    if data == "admin:home":
        await query.edit_message_text("ðŸ‘® Ù¾Ù†Ù„ Ù…Ø¯ÛŒØ±ÛŒØª", reply_markup=admin_home_keyboard())
        return MENU

    if data == "admin:stats":
        await query.edit_message_text(
            get_stats_text(),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ”™ Ø¨Ø§Ø²Ú¯Ø´Øª", callback_data="admin:home")]]),
        )
        return MENU

    if data == "admin:reset_confirm":
        db_execute("DROP TABLE IF EXISTS report_media")
        db_execute("DROP TABLE IF EXISTS reports")
        init_db()
        await query.edit_message_text("âœ… Ø¯ÛŒØªØ§Ø¨ÛŒØ³ Ú¯Ø²Ø§Ø±Ø´â€ŒÙ‡Ø§ Ø±ÛŒØ³Øª Ø´Ø¯.", reply_markup=admin_home_keyboard())
        return MENU

    if data.startswith("admin:list:"):
        status = data.split(":", 2)[2]
        rows = db_fetchall(
            "SELECT id, full_name, created_at FROM reports WHERE status=? ORDER BY id DESC LIMIT 20",
            (status,),
        )
        if not rows:
            await query.edit_message_text(
                f"Ø¨Ø±Ø§ÛŒ ÙˆØ¶Ø¹ÛŒØª {STATUS_LABELS.get(status, status)} Ú¯Ø²Ø§Ø±Ø´ÛŒ ÙˆØ¬ÙˆØ¯ Ù†Ø¯Ø§Ø±Ø¯.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ðŸ”™ Ø¨Ø§Ø²Ú¯Ø´Øª", callback_data="admin:home")]]),
            )
            return MENU

        buttons = []
        for row in rows:
            title = show(row["full_name"])
            buttons.append([InlineKeyboardButton(f"ðŸ“„ #{row['id']} - {title}", callback_data=f"admin:view:{row['id']}")])
        buttons.append([InlineKeyboardButton("ðŸ”™ Ø¨Ø§Ø²Ú¯Ø´Øª", callback_data="admin:home")])

        await query.edit_message_text(
            f"Ù„ÛŒØ³Øª Ú¯Ø²Ø§Ø±Ø´â€ŒÙ‡Ø§: {STATUS_LABELS.get(status, status)}",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return MENU

    if data.startswith("admin:view:"):
        report_id = int(data.split(":", 2)[2])
        return await show_admin_report(query, report_id)

    if data.startswith("admin:set:"):
        parts = data.split(":")
        status = parts[2]
        report_id = int(parts[3])
        db_execute("UPDATE reports SET status=?, updated_at=? WHERE id=?", (status, now_text(), report_id))
        await query.answer(f"ÙˆØ¶Ø¹ÛŒØª ØªØºÛŒÛŒØ± Ú©Ø±Ø¯: {STATUS_LABELS.get(status, status)}", show_alert=False)
        return await show_admin_report(query, report_id)

    if data.startswith("admin:block_reporter:"):
        report_id = int(data.split(":", 2)[2])
        row = db_fetchone("SELECT reporter_id FROM reports WHERE id=?", (report_id,))
        if row and row["reporter_id"]:
            db_execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (row["reporter_id"],))
            await query.answer("Ú©Ø§Ø±Ø¨Ø± Ú¯Ø²Ø§Ø±Ø´â€ŒØ¯Ù‡Ù†Ø¯Ù‡ Ù…Ø³Ø¯ÙˆØ¯ Ø´Ø¯.", show_alert=True)
        return await show_admin_report(query, report_id)

    return MENU


async def show_admin_report(query, report_id: int):
    row = db_fetchone("SELECT * FROM reports WHERE id=?", (report_id,))
    if not row:
        await query.edit_message_text("Ú¯Ø²Ø§Ø±Ø´ Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", reply_markup=admin_home_keyboard())
        return MENU

    media_count = db_fetchone("SELECT COUNT(*) AS c FROM report_media WHERE report_id=?", (report_id,))["c"]
    text = (
        f"ðŸ“„ Ø¬Ø²Ø¦ÛŒØ§Øª Ú¯Ø²Ø§Ø±Ø´ #{row['id']}\n"
        f"ðŸ“Œ ÙˆØ¶Ø¹ÛŒØª: {STATUS_LABELS.get(row['status'], row['status'])}\n"
        f"â­ï¸ Ø§Ù…ØªÛŒØ§Ø² ØªÚ©Ù…ÛŒÙ„ Ø§Ø·Ù„Ø§Ø¹Ø§Øª: {show(row['risk_score'])}\n\n"
        f"ðŸ‘¤ Ù†Ø§Ù…: {show(row['full_name'])}\n"
        f"ðŸ’³ Ø´Ù…Ø§Ø±Ù‡ Ú©Ø§Ø±Øª: {show(row['card_number'])}\n"
        f"ðŸ“ž Ø´Ù…Ø§Ø±Ù‡ ØªÙ…Ø§Ø³: {show(row['phone'])}\n"
        f"ðŸ†” Ø¢ÛŒØ¯ÛŒ ÙØ±Ø¯: {show(row['username'])}\n"
        f"ðŸ’° Ù…Ø¨Ù„Øº: {show(row['amount'])}\n"
        f"ðŸ“Ž ØªØ¹Ø¯Ø§Ø¯ Ù…Ø¯Ø§Ø±Ú©: {media_count}\n\n"
        f"ðŸ‘¤ Ú¯Ø²Ø§Ø±Ø´â€ŒØ¯Ù‡Ù†Ø¯Ù‡: {show(row['reporter_username'])} / {show(row['reporter_id'])}\n"
        f"ðŸ•’ ØªØ§Ø±ÛŒØ® Ø«Ø¨Øª: {show(row['created_at'])}\n\n"
        f"ðŸ“ Ø´Ø±Ø­:\n{show(row['report_text'])}"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("âœ… ØªØ§ÛŒÛŒØ¯", callback_data=f"admin:set:approved:{report_id}"),
                InlineKeyboardButton("âŒ Ø±Ø¯", callback_data=f"admin:set:rejected:{report_id}"),
            ],
            [
                InlineKeyboardButton("ðŸ“Ž Ù…Ø¯Ø±Ú© Ø¨ÛŒØ´ØªØ±", callback_data=f"admin:set:need_more:{report_id}"),
                InlineKeyboardButton("ðŸ—‘ Ø­Ø°Ù", callback_data=f"admin:set:removed:{report_id}"),
            ],
            [InlineKeyboardButton("ðŸš« Ø¨Ù„Ø§Ú© Ú¯Ø²Ø§Ø±Ø´â€ŒØ¯Ù‡Ù†Ø¯Ù‡", callback_data=f"admin:block_reporter:{report_id}")],
            [InlineKeyboardButton("ðŸ”™ Ø¨Ø§Ø²Ú¯Ø´Øª Ø¨Ù‡ Ù¾Ù†Ù„", callback_data="admin:home")],
        ]
    )

    await query.edit_message_text(text, reply_markup=keyboard)
    return MENU

# =========================
# Error Handler
# =========================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("ERROR:", context.error)

# =========================
# Main
# =========================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Please set BOT_TOKEN in Railway Variables.")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
        ],
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
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_command),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)

    # Commands available outside conversation too
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
