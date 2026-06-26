import os
import re
import html
import sqlite3
import logging
from typing import Optional, Dict, Any

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_IDS = set()
for x in os.getenv("ADMIN_IDS", "").split(","):
    x = x.strip()
    if x.isdigit():
        ADMIN_IDS.add(int(x))

DB_PATH = os.getenv("DB_PATH", "bot.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger(__name__)

# =========================================================
# STATES
# =========================================================

USER_STATES: Dict[int, Dict[str, Any]] = {}

REPORT_STEPS = [
    "card_number",
    "full_name",
    "phone",
    "telegram_id",
    "amount",
    "description",
    "evidence",
]

STEP_LABELS = {
    "card_number": "شماره کارت",
    "full_name": "نام و نام خانوادگی",
    "phone": "شماره تماس",
    "telegram_id": "آیدی تلگرام",
    "amount": "مبلغ",
    "description": "شرح گزارش",
    "evidence": "مدارک",
}

CASE_STATUS_LABELS = {
    "pending": "در انتظار بررسی",
    "approved": "تایید شده",
    "rejected": "رد شده",
    "need_more": "نیازمند مدارک بیشتر",
    "removed": "حذف شده",
}

# =========================================================
# DB
# =========================================================

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        is_blocked INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_code TEXT UNIQUE,
        reporter_user_id INTEGER,
        target_card_number TEXT,
        target_full_name TEXT,
        target_phone TEXT,
        target_telegram_id TEXT,
        amount TEXT,
        description TEXT,
        evidence_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        admin_reason TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS evidences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER,
        file_id TEXT,
        file_type TEXT,
        caption TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS status_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER,
        old_status TEXT,
        new_status TEXT,
        reason TEXT,
        admin_user_id INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


def upsert_user(tg_user):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO users (user_id, username, first_name, last_name)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(user_id) DO UPDATE SET
        username=excluded.username,
        first_name=excluded.first_name,
        last_name=excluded.last_name
    """, (
        tg_user.id,
        tg_user.username,
        tg_user.first_name,
        tg_user.last_name,
    ))
    conn.commit()
    conn.close()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_blocked(user_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row["is_blocked"]) if row else False


def set_block_status(user_id: int, blocked: bool):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    UPDATE users
    SET is_blocked = ?
    WHERE user_id = ?
    """, (1 if blocked else 0, user_id))
    conn.commit()
    conn.close()


def create_report(data: Dict[str, Any], reporter_user_id: int) -> int:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO reports (
        reporter_user_id,
        target_card_number,
        target_full_name,
        target_phone,
        target_telegram_id,
        amount,
        description,
        evidence_count,
        status
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
    """, (
        reporter_user_id,
        data.get("card_number"),
        data.get("full_name"),
        data.get("phone"),
        data.get("telegram_id"),
        data.get("amount"),
        data.get("description"),
        len(data.get("evidences", [])),
    ))
    report_id = cur.lastrowid

    case_code = f"RPT-{report_id:06d}"
    cur.execute(
        "UPDATE reports SET case_code = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (case_code, report_id)
    )

    for ev in data.get("evidences", []):
        cur.execute("""
        INSERT INTO evidences (report_id, file_id, file_type, caption)
        VALUES (?, ?, ?, ?)
        """, (
            report_id,
            ev["file_id"],
            ev["file_type"],
            ev.get("caption"),
        ))

    cur.execute("""
    INSERT INTO status_history (report_id, old_status, new_status, reason, admin_user_id)
    VALUES (?, ?, ?, ?, ?)
    """, (
        report_id, None, "pending", "ثبت اولیه", None
    ))

    conn.commit()
    conn.close()
    return report_id


def get_report_by_id(report_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_evidences(report_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM evidences WHERE report_id = ? ORDER BY id ASC", (report_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def update_report_status(report_id: int, new_status: str, admin_user_id: int, reason: Optional[str] = None):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT status FROM reports WHERE id = ?", (report_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False

    old_status = row["status"]

    cur.execute("""
    UPDATE reports
    SET status = ?, admin_reason = ?, updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (new_status, reason, report_id))

    cur.execute("""
    INSERT INTO status_history (report_id, old_status, new_status, reason, admin_user_id)
    VALUES (?, ?, ?, ?, ?)
    """, (report_id, old_status, new_status, reason, admin_user_id))

    conn.commit()
    conn.close()
    return True


def list_reports_by_status(status: str, limit: int = 20):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT * FROM reports
    WHERE status = ?
    ORDER BY id DESC
    LIMIT ?
    """, (status, limit))
    rows = cur.fetchall()
    conn.close()
    return rows


def search_reports(query: str, limit: int = 20):
    q = f"%{query.strip()}%"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT * FROM reports
    WHERE
        status = 'approved'
        AND (
            case_code LIKE ?
            OR target_card_number LIKE ?
            OR target_full_name LIKE ?
            OR target_phone LIKE ?
            OR target_telegram_id LIKE ?
            OR amount LIKE ?
            OR description LIKE ?
        )
    ORDER BY id DESC
    LIMIT ?
    """, (q, q, q, q, q, q, q, limit))
    rows = cur.fetchall()
    conn.close()
    return rows


def list_blocked_users(limit: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT * FROM users
    WHERE is_blocked = 1
    ORDER BY user_id DESC
    LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


def list_reporters(limit: int = 50):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT
        u.user_id,
        u.username,
        u.first_name,
        u.last_name,
        u.is_blocked,
        COUNT(r.id) AS reports_count
    FROM users u
    LEFT JOIN reports r ON u.user_id = r.reporter_user_id
    GROUP BY u.user_id
    ORDER BY reports_count DESC, u.user_id DESC
    LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_reporter_reports(user_id: int, limit: int = 20):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT * FROM reports
    WHERE reporter_user_id = ?
    ORDER BY id DESC
    LIMIT ?
    """, (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows


def count_similar_approved(report_row) -> int:
    if not report_row:
        return 0

    conditions = []
    params = []

    if report_row["target_card_number"]:
        conditions.append("target_card_number = ?")
        params.append(report_row["target_card_number"])
    if report_row["target_phone"]:
        conditions.append("target_phone = ?")
        params.append(report_row["target_phone"])
    if report_row["target_telegram_id"]:
        conditions.append("target_telegram_id = ?")
        params.append(report_row["target_telegram_id"])
    if report_row["target_full_name"]:
        conditions.append("target_full_name = ?")
        params.append(report_row["target_full_name"])

    if not conditions:
        return 0

    where_clause = " OR ".join(conditions)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"""
    SELECT COUNT(*) AS c FROM reports
    WHERE status = 'approved' AND ({where_clause})
    """, params)
    row = cur.fetchone()
    conn.close()
    return row["c"] if row else 0


# =========================================================
# HELPERS
# =========================================================

def esc(text: Any) -> str:
    if text is None:
        return "—"
    return html.escape(str(text))


def normalize_text(text: str) -> str:
    return text.strip()


def validate_card_number(text: str) -> bool:
    text = text.replace(" ", "").replace("-", "")
    return bool(re.fullmatch(r"\d{16}", text))


def validate_phone(text: str) -> bool:
    text = text.strip()
    return bool(re.fullmatch(r"(\+98|0)?9\d{9}", text))


def validate_amount(text: str) -> bool:
    text = text.replace(",", "").strip()
    return bool(re.fullmatch(r"\d+", text))


def make_report_state() -> Dict[str, Any]:
    return {
        "mode": "report",
        "step_index": 0,
        "message_id": None,
        "chat_id": None,
        "data": {
            "card_number": None,
            "full_name": None,
            "phone": None,
            "telegram_id": None,
            "amount": None,
            "description": None,
            "evidences": [],
        }
    }


def current_step(state: Dict[str, Any]) -> str:
    return REPORT_STEPS[state["step_index"]]


def step_prompt(step: str) -> str:
    prompts = {
        "card_number": "شماره کارت ۱۶ رقمی را وارد کنید یا رد کنید.",
        "full_name": "نام و نام خانوادگی فرد را وارد کنید یا رد کنید.",
        "phone": "شماره تماس را وارد کنید یا رد کنید.",
        "telegram_id": "آیدی تلگرام را وارد کنید یا رد کنید. مثل: @username",
        "amount": "مبلغ را وارد کنید یا رد کنید.",
        "description": "شرح گزارش را وارد کنید. این بخش اجباری است.",
        "evidence": "عکس یا فایل‌های مدرک را ارسال کنید. اگر تمام شد، روی «پایان مدارک» بزنید.",
    }
    return prompts.get(step, "مقدار این بخش را وارد کنید.")


def user_main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 ثبت گزارش", callback_data="menu_report")],
        [InlineKeyboardButton("🔍 جستجو", callback_data="menu_search")],
        [InlineKeyboardButton("ℹ️ راهنما", callback_data="menu_help")],
    ])


def admin_main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 در انتظار بررسی", callback_data="admin_list_pending")],
        [InlineKeyboardButton("✅ تایید شده‌ها", callback_data="admin_list_approved")],
        [InlineKeyboardButton("❌ رد شده‌ها", callback_data="admin_list_rejected")],
        [InlineKeyboardButton("🟡 نیازمند مدرک بیشتر", callback_data="admin_list_need_more")],
        [InlineKeyboardButton("🗑 حذف شده‌ها", callback_data="admin_list_removed")],
        [InlineKeyboardButton("👥 گزارش‌دهنده‌ها", callback_data="admin_reporters")],
        [InlineKeyboardButton("⛔ بلاک‌شده‌ها", callback_data="admin_blocked")],
    ])


def report_form_keyboard(step: str):
    rows = []
    if step != "description":
        rows.append([InlineKeyboardButton("⏭ رد کردن", callback_data="report_skip")])

    if step == "evidence":
        rows.append([InlineKeyboardButton("✅ پایان مدارک", callback_data="report_finish_evidence")])

    if step != "card_number":
        rows.append([InlineKeyboardButton("⬅️ قبلی", callback_data="report_prev")])

    rows.append([InlineKeyboardButton("❌ لغو", callback_data="report_cancel")])
    return InlineKeyboardMarkup(rows)


def review_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ثبت نهایی", callback_data="report_submit")],
        [InlineKeyboardButton("✏️ ویرایش از ابتدا", callback_data="report_restart")],
        [InlineKeyboardButton("❌ لغو", callback_data="report_cancel")],
    ])


def search_result_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 جستجوی جدید", callback_data="menu_search")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="back_main")],
    ])


def admin_report_actions_keyboard(report_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ تایید", callback_data=f"admin_approve_{report_id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"admin_reject_{report_id}"),
        ],
        [
            InlineKeyboardButton("🟡 نیاز به مدرک", callback_data=f"admin_needmore_{report_id}"),
            InlineKeyboardButton("🗑 حذف", callback_data=f"admin_remove_{report_id}"),
        ],
        [
            InlineKeyboardButton("👤 گزارش‌دهنده", callback_data=f"admin_reporter_{report_id}"),
        ],
        [
            InlineKeyboardButton("🔙 بازگشت", callback_data="admin_home"),
        ]
    ])


def format_report_form(state: Dict[str, Any]) -> str:
    data = state["data"]
    step = current_step(state)
    evidences_count = len(data["evidences"])

    return f"""
📋 <b>فرم ثبت گزارش</b>

1) <b>شماره کارت:</b> {esc(data.get("card_number"))}
2) <b>نام و نام خانوادگی:</b> {esc(data.get("full_name"))}
3) <b>شماره تماس:</b> {esc(data.get("phone"))}
4) <b>آیدی تلگرام:</b> {esc(data.get("telegram_id"))}
5) <b>مبلغ:</b> {esc(data.get("amount"))}
6) <b>شرح گزارش:</b> {esc(data.get("description"))}
7) <b>مدارک:</b> {evidences_count} فایل

━━━━━━━━━━
<b>مرحله فعلی:</b> {esc(STEP_LABELS[step])}
<b>راهنما:</b> {esc(step_prompt(step))}
""".strip()


def format_review(state: Dict[str, Any]) -> str:
    data = state["data"]
    return f"""
📋 <b>مرور نهایی گزارش</b>

<b>شماره کارت:</b> {esc(data.get("card_number"))}
<b>نام و نام خانوادگی:</b> {esc(data.get("full_name"))}
<b>شماره تماس:</b> {esc(data.get("phone"))}
<b>آیدی تلگرام:</b> {esc(data.get("telegram_id"))}
<b>مبلغ:</b> {esc(data.get("amount"))}
<b>شرح گزارش:</b>
{esc(data.get("description"))}

<b>تعداد مدارک:</b> {len(data.get("evidences", []))}

اگر اطلاعات درست است، ثبت نهایی را بزنید.
""".strip()


def risk_label(similar_count: int, evidence_count: int) -> str:
    score = 0
    if similar_count >= 4:
        score += 4
    elif similar_count >= 2:
        score += 3
    elif similar_count >= 1:
        score += 1

    if evidence_count >= 3:
        score += 2
    elif evidence_count >= 1:
        score += 1

    if score >= 5:
        return "🔴 بالا"
    elif score >= 3:
        return "🟠 متوسط"
    elif score >= 1:
        return "🟡 کم"
    return "⚪ نامشخص"


def format_report_public(report_row) -> str:
    similar_count = count_similar_approved(report_row)
    risk = risk_label(similar_count, report_row["evidence_count"])
    status_label = CASE_STATUS_LABELS.get(report_row["status"], report_row["status"])

    return f"""
📁 <b>پرونده: {esc(report_row["case_code"])}</b>

<b>وضعیت:</b> {esc(status_label)}
<b>ریسک:</b> {esc(risk)}
<b>تعداد گزارش‌های مشابه تاییدشده:</b> {similar_count}

<b>نام:</b> {esc(report_row["target_full_name"])}
<b>شماره کارت:</b> {esc(report_row["target_card_number"])}
<b>شماره تماس:</b> {esc(report_row["target_phone"])}
<b>آیدی تلگرام:</b> {esc(report_row["target_telegram_id"])}
<b>مبلغ:</b> {esc(report_row["amount"])}

<b>شرح گزارش:</b>
{esc(report_row["description"])}

<b>تعداد مدارک:</b> {report_row["evidence_count"]}
""".strip()


def format_report_admin(report_row) -> str:
    similar_count = count_similar_approved(report_row)
    risk = risk_label(similar_count, report_row["evidence_count"])
    status_label = CASE_STATUS_LABELS.get(report_row["status"], report_row["status"])

    return f"""
🛠 <b>پرونده ادمین</b>

<b>شماره پرونده:</b> {esc(report_row["case_code"])}
<b>شناسه داخلی:</b> {report_row["id"]}
<b>وضعیت:</b> {esc(status_label)}
<b>ریسک:</b> {esc(risk)}
<b>گزارش‌دهنده:</b> <code>{report_row["reporter_user_id"]}</code>

<b>نام:</b> {esc(report_row["target_full_name"])}
<b>شماره کارت:</b> {esc(report_row["target_card_number"])}
<b>شماره تماس:</b> {esc(report_row["target_phone"])}
<b>آیدی تلگرام:</b> {esc(report_row["target_telegram_id"])}
<b>مبلغ:</b> {esc(report_row["amount"])}

<b>شرح گزارش:</b>
{esc(report_row["description"])}

<b>تعداد مدارک:</b> {report_row["evidence_count"]}
<b>دلیل ادمین:</b> {esc(report_row["admin_reason"])}
<b>ثبت:</b> {esc(report_row["created_at"])}
<b>آخرین بروزرسانی:</b> {esc(report_row["updated_at"])}
""".strip()


async def safe_edit_message(query, text: str, reply_markup=None):
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


async def send_report_evidences(chat_id: int, report_id: int, context: ContextTypes.DEFAULT_TYPE):
    evs = get_evidences(report_id)
    if not evs:
        return

    for ev in evs:
        try:
            if ev["file_type"] == "photo":
                await context.bot.send_photo(chat_id=chat_id, photo=ev["file_id"], caption="📎 مدرک پرونده")
            else:
                await context.bot.send_document(chat_id=chat_id, document=ev["file_id"], caption="📎 مدرک پرونده")
        except Exception as e:
            logger.warning(f"Could not send evidence {ev['id']}: {e}")


def reset_user_state(user_id: int):
    USER_STATES.pop(user_id, None)


# =========================================================
# COMMANDS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return

    upsert_user(user)

    if is_blocked(user.id):
        await update.message.reply_text("⛔ شما از استفاده از ربات مسدود شده‌اید.")
        return

    text = "سلام 👋\n\nبه ربات ثبت و جستجوی گزارش خوش آمدید.\nاز منوی زیر استفاده کنید."

    if is_admin(user.id):
        text += "\n\nشما به عنوان ادمین شناسایی شدید."
        await update.message.reply_text(text, reply_markup=admin_main_menu_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=user_main_menu_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = """
ℹ️ راهنما

📝 ثبت گزارش:
فرم را مرحله‌به‌مرحله تکمیل کنید.
بیشتر فیلدها اختیاری هستند و می‌توانید رد کنید.

🔍 جستجو:
می‌توانید با یکی از موارد زیر جستجو کنید:
- شماره کارت
- نام
- شماره تماس
- آیدی تلگرام
- مبلغ
- متن گزارش
- شماره پرونده

🛠 ادمین:
ادمین می‌تواند پرونده‌ها را بررسی، تایید، رد، حذف یا نیازمند مدرک بیشتر کند.
""".strip()

    await update.message.reply_text(text, reply_markup=user_main_menu_keyboard())


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return

    upsert_user(user)

    if not is_admin(user.id):
        await update.message.reply_text("⛔ شما ادمین نیستید.")
        return

    await update.message.reply_text("پنل ادمین:", reply_markup=admin_main_menu_keyboard())


# =========================================================
# REPORT FLOW
# =========================================================

async def start_report_flow(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    USER_STATES[user_id] = make_report_state()
    USER_STATES[user_id]["chat_id"] = chat_id

    text = format_report_form(USER_STATES[user_id])
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=report_form_keyboard(current_step(USER_STATES[user_id])),
    )
    USER_STATES[user_id]["message_id"] = msg.message_id


async def show_review(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    state = USER_STATES.get(user_id)
    if not state:
        return

    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=state["message_id"],
        text=format_review(state),
        parse_mode=ParseMode.HTML,
        reply_markup=review_keyboard(),
    )


def is_report_valid(data: Dict[str, Any]) -> bool:
    return bool(data.get("description"))


async def handle_report_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return

    state = USER_STATES.get(user.id)
    if not state or state.get("mode") != "report":
        return

    step = current_step(state)
    text = normalize_text(update.message.text or "")

    if step == "evidence":
        await update.message.reply_text("در این مرحله لطفاً عکس یا فایل بفرستید، یا «پایان مدارک» را بزنید.")
        return

    error = None

    if step == "card_number":
        card = text.replace(" ", "").replace("-", "")
        if not validate_card_number(card):
            error = "شماره کارت باید ۱۶ رقمی باشد."
        else:
            state["data"]["card_number"] = card

    elif step == "full_name":
        state["data"]["full_name"] = text

    elif step == "phone":
        if not validate_phone(text):
            error = "شماره تماس معتبر نیست."
        else:
            state["data"]["phone"] = text

    elif step == "telegram_id":
        state["data"]["telegram_id"] = text

    elif step == "amount":
        clean_amount = text.replace(",", "")
        if not validate_amount(clean_amount):
            error = "مبلغ باید فقط عدد باشد."
        else:
            state["data"]["amount"] = clean_amount

    elif step == "description":
        if len(text) < 5:
            error = "شرح گزارش خیلی کوتاه است."
        else:
            state["data"]["description"] = text

    if error:
        await update.message.reply_text(f"⚠️ {error}")
        return

    try:
        await update.message.delete()
    except Exception:
        pass

    if state["step_index"] < len(REPORT_STEPS) - 1:
        state["step_index"] += 1

    await context.bot.edit_message_text(
        chat_id=state["chat_id"],
        message_id=state["message_id"],
        text=format_report_form(state),
        parse_mode=ParseMode.HTML,
        reply_markup=report_form_keyboard(current_step(state)),
    )


async def handle_report_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return

    state = USER_STATES.get(user.id)
    if not state or state.get("mode") != "report":
        return

    if current_step(state) != "evidence":
        return

    file_id = None
    file_type = None
    caption = update.message.caption

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_type = "photo"
    elif update.message.document:
        file_id = update.message.document.file_id
        file_type = "document"

    if not file_id:
        return

    state["data"]["evidences"].append({
        "file_id": file_id,
        "file_type": file_type,
        "caption": caption,
    })

    try:
        await update.message.delete()
    except Exception:
        pass

    await context.bot.edit_message_text(
        chat_id=state["chat_id"],
        message_id=state["message_id"],
        text=format_report_form(state),
        parse_mode=ParseMode.HTML,
        reply_markup=report_form_keyboard("evidence"),
    )


# =========================================================
# SEARCH FLOW
# =========================================================

async def start_search_prompt(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE):
    USER_STATES[user_id] = {
        "mode": "search",
        "chat_id": chat_id,
    }

    text = """
🔍 <b>جستجو</b>

می‌توانید با یکی از موارد زیر جستجو کنید:
- شماره کارت
- نام و نام خانوادگی
- شماره تماس
- آیدی تلگرام
- مبلغ
- بخشی از متن گزارش
- شماره پرونده

عبارت موردنظر را ارسال کنید.
""".strip()

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=search_result_keyboard(),
    )


async def handle_search_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return

    state = USER_STATES.get(user.id)
    if not state or state.get("mode") != "search":
        return

    query = normalize_text(update.message.text or "")
    if len(query) < 2:
        await update.message.reply_text("عبارت جستجو خیلی کوتاه است.")
        return

    try:
        await update.message.delete()
    except Exception:
        pass

    results = search_reports(query, limit=10)

    if not results:
        await update.message.reply_text(
            "❌ نتیجه‌ای در پرونده‌های تاییدشده پیدا نشد.",
            reply_markup=search_result_keyboard(),
        )
        return

    await update.message.reply_text(f"✅ {len(results)} نتیجه پیدا شد:")

    for row in results:
        await update.message.reply_text(
            format_report_public(row),
            parse_mode=ParseMode.HTML,
            reply_markup=search_result_keyboard(),
        )
        await send_report_evidences(update.effective_chat.id, row["id"], context)

    reset_user_state(user.id)


# =========================================================
# ADMIN FLOW
# =========================================================

async def show_admin_home(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=chat_id, text="پنل ادمین:", reply_markup=admin_main_menu_keyboard())


async def show_admin_report_list(chat_id: int, status: str, context: ContextTypes.DEFAULT_TYPE):
    rows = list_reports_by_status(status)

    if not rows:
        await context.bot.send_message(chat_id=chat_id, text="موردی پیدا نشد.", reply_markup=admin_main_menu_keyboard())
        return

    status_label = CASE_STATUS_LABELS.get(status, status)
    await context.bot.send_message(chat_id=chat_id, text=f"📂 لیست پرونده‌های {status_label}:")

    for row in rows:
        txt = (
            f"• <b>{esc(row['case_code'])}</b>\n"
            f"نام: {esc(row['target_full_name'])}\n"
            f"کارت: {esc(row['target_card_number'])}\n"
            f"تماس: {esc(row['target_phone'])}\n"
            f"مدارک: {row['evidence_count']}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 مشاهده پرونده", callback_data=f"admin_view_{row['id']}")]
        ])
        await context.bot.send_message(chat_id=chat_id, text=txt, parse_mode=ParseMode.HTML, reply_markup=kb)


async def show_admin_report(chat_id: int, report_id: int, context: ContextTypes.DEFAULT_TYPE):
    row = get_report_by_id(report_id)
    if not row:
        await context.bot.send_message(chat_id=chat_id, text="پرونده پیدا نشد.")
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=format_report_admin(row),
        parse_mode=ParseMode.HTML,
        reply_markup=admin_report_actions_keyboard(report_id),
    )
    await send_report_evidences(chat_id, report_id, context)


async def show_blocked_users(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    rows = list_blocked_users()
    if not rows:
        await context.bot.send_message(chat_id=chat_id, text="هیچ کاربر بلاک‌شده‌ای وجود ندارد.", reply_markup=admin_main_menu_keyboard())
        return

    lines = ["⛔ <b>کاربران بلاک‌شده</b>\n"]
    for r in rows:
        username = f"@{r['username']}" if r["username"] else "—"
        first_name = r["first_name"] if r["first_name"] else "—"
        lines.append(f"• <code>{r['user_id']}</code> | {esc(username)} | {esc(first_name)}")

    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=admin_main_menu_keyboard(),
    )


async def show_reporters(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    rows = list_reporters()
    if not rows:
        await context.bot.send_message(chat_id=chat_id, text="گزارش‌دهنده‌ای پیدا نشد.", reply_markup=admin_main_menu_keyboard())
        return

    await context.bot.send_message(chat_id=chat_id, text="👥 لیست گزارش‌دهنده‌ها:")

    for r in rows:
        first_name = r["first_name"] if r["first_name"] else "—"
        last_name = r["last_name"] if r["last_name"] else ""
        username = f"@{r['username']}" if r["username"] else "—"

        txt = (
            f"👤 <b>{esc(first_name)} {esc(last_name)}</b>\n"
            f"ID: <code>{r['user_id']}</code>\n"
            f"Username: {esc(username)}\n"
            f"تعداد گزارش: {r['reports_count']}\n"
            f"وضعیت بلاک: {'بله' if r['is_blocked'] else 'خیر'}"
        )
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📄 گزارش‌ها", callback_data=f"admin_reporterlist_{r['user_id']}"),
                InlineKeyboardButton("⛔/✅ بلاک", callback_data=f"admin_toggleblock_{r['user_id']}"),
            ]
        ])
        await context.bot.send_message(chat_id=chat_id, text=txt, parse_mode=ParseMode.HTML, reply_markup=kb)


async def show_reporter_reports(chat_id: int, reporter_user_id: int, context: ContextTypes.DEFAULT_TYPE):
    rows = get_reporter_reports(reporter_user_id)
    if not rows:
        await context.bot.send_message(chat_id=chat_id, text="برای این گزارش‌دهنده پرونده‌ای ثبت نشده.")
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"📄 پرونده‌های گزارش‌دهنده <code>{reporter_user_id}</code>:",
        parse_mode=ParseMode.HTML,
    )

    for row in rows:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 مشاهده پرونده", callback_data=f"admin_view_{row['id']}")]
        ])
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{esc(row['case_code'])} | {esc(CASE_STATUS_LABELS.get(row['status'], row['status']))}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )


# =========================================================
# CALLBACKS
# =========================================================

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user

    if not query or not user:
        return

    upsert_user(user)
    await query.answer()
    data = query.data

    if is_blocked(user.id):
        await safe_edit_message(query, "⛔ شما از استفاده از ربات مسدود شده‌اید.")
        return

    if data == "menu_report":
        await start_report_flow(update.effective_chat.id, user.id, context)
        return

    if data == "menu_search":
        await start_search_prompt(update.effective_chat.id, user.id, context)
        return

    if data == "menu_help":
        await safe_edit_message(
            query,
            """
ℹ️ <b>راهنما</b>

- برای ثبت گزارش از بخش «ثبت گزارش» استفاده کنید.
- برای پیدا کردن سابقه، از بخش «جستجو» استفاده کنید.
- فقط پرونده‌های تاییدشده در جستجوی عمومی نمایش داده می‌شوند.
""".strip(),
            reply_markup=user_main_menu_keyboard(),
        )
        return

    if data == "back_main":
        if is_admin(user.id):
            await safe_edit_message(query, "منوی اصلی ادمین:", reply_markup=admin_main_menu_keyboard())
        else:
            await safe_edit_message(query, "منوی اصلی:", reply_markup=user_main_menu_keyboard())
        reset_user_state(user.id)
        return

    state = USER_STATES.get(user.id)

    if data == "report_cancel":
        reset_user_state(user.id)
        await safe_edit_message(query, "❌ عملیات ثبت گزارش لغو شد.", reply_markup=user_main_menu_keyboard())
        return

    if data == "report_restart":
        await start_report_flow(update.effective_chat.id, user.id, context)
        return

    if state and state.get("mode") == "report":
        if data == "report_skip":
            step = current_step(state)
            if step == "description":
                await query.answer("شرح گزارش قابل رد کردن نیست.", show_alert=True)
                return

            if state["step_index"] < len(REPORT_STEPS) - 1:
                state["step_index"] += 1

            await safe_edit_message(
                query,
                format_report_form(state),
                reply_markup=report_form_keyboard(current_step(state)),
            )
            return

        if data == "report_prev":
            if state["step_index"] > 0:
                state["step_index"] -= 1

            await safe_edit_message(
                query,
                format_report_form(state),
                reply_markup=report_form_keyboard(current_step(state)),
            )
            return

        if data == "report_finish_evidence":
            if not is_report_valid(state["data"]):
                await query.answer("شرح گزارش الزامی است.", show_alert=True)
                return

            await show_review(update.effective_chat.id, user.id, context)
            return

        if data == "report_submit":
            if not is_report_valid(state["data"]):
                await query.answer("شرح گزارش الزامی است.", show_alert=True)
                return

            report_id = create_report(state["data"], user.id)
            report = get_report_by_id(report_id)

            reset_user_state(user.id)

            await safe_edit_message(
                query,
                f"""
✅ <b>گزارش شما ثبت شد</b>

<b>شماره پرونده:</b> {esc(report["case_code"])}
<b>وضعیت:</b> {esc(CASE_STATUS_LABELS.get(report["status"], report["status"]))}

این شماره را برای پیگیری نگه دارید.
""".strip(),
                reply_markup=user_main_menu_keyboard(),
            )

            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text="📥 پرونده جدید ثبت شد:\n\n" + format_report_admin(report),
                        parse_mode=ParseMode.HTML,
                        reply_markup=admin_report_actions_keyboard(report_id),
                    )
                    await send_report_evidences(admin_id, report_id, context)
                except Exception as e:
                    logger.warning(f"Could not notify admin {admin_id}: {e}")
            return

    if data == "admin_home":
        if not is_admin(user.id):
            return
        await safe_edit_message(query, "پنل ادمین:", reply_markup=admin_main_menu_keyboard())
        return

    if not is_admin(user.id):
        return

    if data.startswith("admin_list_"):
        status = data.replace("admin_list_", "")
        await show_admin_report_list(update.effective_chat.id, status, context)
        return

    if data == "admin_blocked":
        await show_blocked_users(update.effective_chat.id, context)
        return

    if data == "admin_reporters":
        await show_reporters(update.effective_chat.id, context)
        return

    if data.startswith("admin_reporterlist_"):
        reporter_id = int(data.split("_")[-1])
        await show_reporter_reports(update.effective_chat.id, reporter_id, context)
        return

    if data.startswith("admin_toggleblock_"):
        target_id = int(data.split("_")[-1])
        blocked = is_blocked(target_id)
        set_block_status(target_id, not blocked)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"وضعیت کاربر <code>{target_id}</code> به {'بلاک' if not blocked else 'آزاد'} تغییر کرد.",
            parse_mode=ParseMode.HTML,
        )
        return

    if data.startswith("admin_view_"):
        report_id = int(data.split("_")[-1])
        await show_admin_report(update.effective_chat.id, report_id, context)
        return

    if data.startswith("admin_reporter_"):
        report_id = int(data.split("_")[-1])
        report = get_report_by_id(report_id)
        if report:
            await show_reporter_reports(update.effective_chat.id, report["reporter_user_id"], context)
        return

    status_map = {
        "admin_approve_": "approved",
        "admin_reject_": "rejected",
        "admin_needmore_": "need_more",
        "admin_remove_": "removed",
    }

    for prefix, new_status in status_map.items():
        if data.startswith(prefix):
            report_id = int(data.replace(prefix, ""))

            reason = {
                "approved": "توسط ادمین تایید شد",
                "rejected": "توسط ادمین رد شد",
                "need_more": "نیازمند مدارک بیشتر",
                "removed": "توسط ادمین حذف شد",
            }.get(new_status)

            ok = update_report_status(report_id, new_status, user.id, reason)
            if not ok:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="خطا در بروزرسانی وضعیت.")
                return

            row = get_report_by_id(report_id)

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ وضعیت پرونده {row['case_code']} به «{CASE_STATUS_LABELS.get(new_status, new_status)}» تغییر کرد."
            )

            try:
                await context.bot.send_message(
                    chat_id=row["reporter_user_id"],
                    text=f"""
📢 <b>بروزرسانی پرونده</b>

<b>شماره پرونده:</b> {esc(row["case_code"])}
<b>وضعیت جدید:</b> {esc(CASE_STATUS_LABELS.get(row["status"], row["status"]))}
<b>توضیح:</b> {esc(row["admin_reason"])}
""".strip(),
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.warning(f"Could not notify reporter {row['reporter_user_id']}: {e}")

            await show_admin_report(update.effective_chat.id, report_id, context)
            return


# =========================================================
# ROUTERS
# =========================================================

async def route_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    user = update.effective_user
    upsert_user(user)

    if is_blocked(user.id):
        await update.message.reply_text("⛔ شما از استفاده از ربات مسدود شده‌اید.")
        return

    state = USER_STATES.get(user.id)

    if state and state.get("mode") == "report":
        await handle_report_text(update, context)
        return

    if state and state.get("mode") == "search":
        await handle_search_text(update, context)
        return

    if is_admin(user.id):
        await update.message.reply_text("از منوی ادمین استفاده کنید.", reply_markup=admin_main_menu_keyboard())
    else:
        await update.message.reply_text("از منوی اصلی استفاده کنید.", reply_markup=user_main_menu_keyboard())


async def route_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    user = update.effective_user
    upsert_user(user)

    if is_blocked(user.id):
        await update.message.reply_text("⛔ شما از استفاده از ربات مسدود شده‌اید.")
        return

    state = USER_STATES.get(user.id)
    if state and state.get("mode") == "report":
        await handle_report_media(update, context)
        return

    await update.message.reply_text("فعلاً در حالت ثبت گزارش نیستید.")


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN تنظیم نشده است.")

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, route_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, route_text))

    logger.info("Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
