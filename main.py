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
    {
        "key": "card_number",
        "title": "💳 شماره کارت",
        "question": "💳 شماره کارت فرد موردنظر را وارد کنید",
        "required": False,
    },
    {
        "key": "full_name",
        "title": "👤 نام و نام خانوادگی",
        "question": "👤 نام و نام خانوادگی فرد موردنظر را وارد کنید",
        "required": True,
    },
    {
        "key": "phone",
        "title": "📞 شماره تماس",
        "question": "📞 شماره تماس فرد موردنظر را وارد کنید",
        "required": False,
    },
    {
        "key": "username",
        "title": "🆔 آیدی تلگرام",
        "question": "🆔 آیدی تلگرام فرد موردنظر را وارد کنید، مثل @username",
        "required": False,
    },
    {
        "key": "amount",
        "title": "💰 مبلغ",
        "question": "💰 مبلغ یا حدود مبلغ را وارد کنید",
        "required": False,
    },
    {
        "key": "report_text",
        "title": "📝 شرح گزارش",
        "question": "📝 شرح کامل گزارش را وارد کنید",
        "required": True,
    },
    {
        "key": "media",
        "title": "📎 مدارک",
        "question": "📎 عکس، اسکرین‌شات، فایل یا PDF مدارک را ارسال کنید",
        "required": False,
    },
]

REPORT_STATUS_LABELS = {
    "pending": "📥 در انتظار بررسی",
    "approved": "✅ تاییدشده",
    "rejected": "❌ ردشده",
    "disputed": "⚠️ دارای اعتراض",
    "removed": "🗑 حذف‌شده",
    "need_more": "📎 نیازمند مدرک بیشتر",
}

PUBLIC_SEARCH_LIMIT = 10
ADMIN_LIST_LIMIT = 10


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return str(value).strip()


def display_value(value: Optional[str]) -> str:
    value = clean_text(value)
    return value if value else "ثبت نشده"


def short_text(value: Optional[str], limit: int = 800) -> str:
    value = display_value(value)
    if len(value) <= limit:
        return value
    return value[:limit] + "..."


def is_admin(user_id: Optional[int]) -> bool:
    return bool(user_id and user_id in ADMIN_IDS)


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def db_execute(query: str, params: Tuple[Any, ...] = ()) -> None:
    with get_conn() as conn:
        conn.execute(query, params)
        conn.commit()


def db_fetchone(query: str, params: Tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(query, params).fetchone()


def db_fetchall(query: str, params: Tuple[Any, ...] = ()) -> List[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(query, params).fetchall()


def table_columns(table_name: str) -> List[str]:
    rows = db_fetchall(f"PRAGMA table_info({table_name})")
    return [row["name"] for row in rows]


def add_column_if_missing(table_name: str, column_name: str, column_sql: str) -> None:
    if column_name not in table_columns(table_name):
        db_execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def init_db() -> None:
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

    db_execute(
        """
        CREATE TABLE IF NOT EXISTS appeals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER,
            user_id INTEGER,
            text TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT
        )
        """
    )

    add_column_if_missing("reports", "reporter_id", "reporter_id INTEGER")
    add_column_if_missing("reports", "reporter_username", "reporter_username TEXT")
    add_column_if_missing("reports", "card_number", "card_number TEXT")
    add_column_if_missing("reports", "full_name", "full_name TEXT")
    add_column_if_missing("reports", "phone", "phone TEXT")
    add_column_if_missing("reports", "username", "username TEXT")
    add_column_if_missing("reports", "amount", "amount TEXT")
    add_column_if_missing("reports", "report_text", "report_text TEXT")
    add_column_if_missing("reports", "status", "status TEXT DEFAULT 'pending'")
    add_column_if_missing("reports", "admin_note", "admin_note TEXT")
    add_column_if_missing("reports", "risk_score", "risk_score INTEGER DEFAULT 0")
    add_column_if_missing("reports", "created_at", "created_at TEXT")
    add_column_if_missing("reports", "updated_at", "updated_at TEXT")

    db_execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)")
    db_execute("CREATE INDEX IF NOT EXISTS idx_reports_full_name ON reports(full_name)")
    db_execute("CREATE INDEX IF NOT EXISTS idx_reports_card ON reports(card_number)")
    db_execute("CREATE INDEX IF NOT EXISTS idx_reports_username ON reports(username)")
    db_execute("CREATE INDEX IF NOT EXISTS idx_media_report_id ON report_media(report_id)")


def save_user(update: Update) -> None:
    user = update.effective_user
    if not user:
        return

    existing = db_fetchone("SELECT user_id FROM users WHERE user_id = ?", (user.id,))
    if existing:
        db_execute(
            """
            UPDATE users
            SET username = ?, first_name = ?, last_name = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (
                user.username or "",
                user.first_name or "",
                user.last_name or "",
                now_text(),
                user.id,
            ),
        )
    else:
        db_execute(
            """
            INSERT INTO users (
                user_id, username, first_name, last_name,
                is_blocked, reports_count, rejected_reports_count,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 0, 0, 0, ?, ?)
            """,
            (
                user.id,
                user.username or "",
                user.first_name or "",
                user.last_name or "",
                now_text(),
                now_text(),
            ),
        )


def is_user_blocked(user_id: int) -> bool:
    row = db_fetchone("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
    return bool(row and row["is_blocked"] == 1)


def calculate_risk_score(report: Dict[str, str], media_count: int) -> int:
    score = 0

    if clean_text(report.get("card_number")):
        score += 20
    if clean_text(report.get("full_name")):
        score += 20
    if clean_text(report.get("phone")):
        score += 10
    if clean_text(report.get("username")):
        score += 10
    if clean_text(report.get("amount")):
        score += 10

    report_text = clean_text(report.get("report_text"))
    if len(report_text) >= 40:
        score += 20
    elif report_text:
        score += 10

    if media_count > 0:
        score += min(20, media_count * 10)

    return min(score, 100)


def risk_label(score: int) -> str:
    if score >= 80:
        return "بالا"
    if score >= 50:
        return "متوسط"
    return "پایین"


def main_menu_keyboard(user_id: Optional[int] = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📝 ثبت گزارش", callback_data="menu:report")],
        [InlineKeyboardButton("🔎 جستجو", callback_data="menu:search")],
        [InlineKeyboardButton("ℹ️ راهنما", callback_data="menu:help")],
    ]

    if is_admin(user_id):
        rows.append([InlineKeyboardButton("👮 پنل ادمین", callback_data="admin:home")])

    return InlineKeyboardMarkup(rows)


def report_keyboard(step_index: int, media_count: int = 0) -> InlineKeyboardMarkup:
    step = REPORT_STEPS[step_index]
    question = step["question"]

    rows = [
        [InlineKeyboardButton(question, callback_data="report:noop")],
    ]

    if step["key"] == "media":
        rows.append(
            [
                InlineKeyboardButton(
                    f"✅ پایان ارسال مدارک ({media_count})",
                    callback_data="report:finish_media",
                )
            ]
        )

    nav_row = []
    if step_index > 0:
        nav_row.append(InlineKeyboardButton("🔙 مرحله قبل", callback_data="report:back"))

    if not step["required"]:
        nav_row.append(InlineKeyboardButton("⏭ رد کردن", callback_data="report:skip"))

    if nav_row:
        rows.append(nav_row)

    rows.append([InlineKeyboardButton("❌ لغو ثبت گزارش", callback_data="report:cancel")])

    return InlineKeyboardMarkup(rows)


def build_report_form_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    step_index = context.user_data.get("report_step", 0)
    report = context.user_data.get("report", {})
    media = context.user_data.get("report_media", [])

    total = len(REPORT_STEPS)
    current = step_index + 1
    progress_done = "█" * current
    progress_left = "░" * (total - current)

    lines = [
        "📝 <b>ثبت گزارش جدید</b>",
        "",
        f"📍 مرحله {current} از {total}",
        f"<code>{progress_done}{progress_left}</code> {current}/{total}",
        "",
        "📋 <b>وضعیت فرم:</b>",
    ]

    for index, step in enumerate(REPORT_STEPS, start=1):
        key = step["key"]
        title = step["title"]

        if key == "media":
            count = l count:
                lines.append(f"✅ {index}. {title}: {count} مدرک")
            else:
                lines.append(f"⬜ {index}. {title}: هنوز ارسال نشده")
            continue

        value = clean_text(report.get(key))
        if value:
            lines.append(f"✅ {index}. {title}: {short_text(value, 70)}")
        else:
            lines.append(f"⬜ {index}. {title}: هنوز وارد نشده")

    lines.extend(
        [
            "",
            "لطفاً به سؤال داخل باکس زیر پاسخ بده.",
        ]
    )

    return "\n".join(lines)


def build_report_summary(report: Dict[str, str], media_count: int, status: str = "pending") -> str:
    score = calculate_risk_score(report, media_count)

    return "\n".join(
        [
            "📄 <b>خلاصه گزارش</b>",
            "",
            f"💳 شماره کارت: <code>{display_value(report.g('card_number'))}</code>",
            f"👤 نام: {display_value(repor.get('full_name'))}",
            f"📞 تماس: <code>{display_value(report.get('phone'))}</code>",
            f"🆔 آیدی: {display_value(report
